# lemony_llm_provider 设计

纯异步的进程内 LLM 访问层: 把三种主流协议归一化成一个内部模型, 在同一组端点上做多 key 轮询与冷却熔断。
不做服务端, 不做跨协议代理, 只管"发请求 / 收流 / 记账 / 挑端点"。路线图条目见 `docs/roadmap.md`。

## 目标与边界

做:

- 三种协议: OpenAI chat completions, OpenAI responses, Anthropic messages
- 流式与整段两种调用方式, 共用一条归一化路径
- 工具调用(由调用方执行)、图片输入、JSON Schema 结构化输出、reasoning 与正文分离
- 多端点(多 key / 多 provider)轮询、冷却熔断、失败换端点
- 用量统计(输入 / 输出 / 缓存命中与写入 / reasoning token)

不做:

- 上游内置工具(`web_search` / `file_search` / `code_interpreter` / MCP)一律不传, 也不做跨厂商等价替代。
  内部模型里没有它们的字段, 需要时只能用 `extra_body` 自己塞, 行为与计费由调用方自己承担。
- embeddings / rerank
- 服务端形态(HTTP 网关)、跨进程共享配额
- 服务端会话状态: 一律 `store: false`, 多轮上下文由调用方持有
- 同步 API

依赖: `openai` 与 `anthropic` 两个官方 SDK 作为传输层, 自己只写协议翻译、路由与错误映射。
这比手写 HTTP 多几个传递依赖(`httpx2` / `jiter` / `opentelemetry-api` / `docstring-parser`),
换来的是两套流式解析、参数校验和错误类型都是现成的。

## 协议现状

以下为 2026-10-18 核对的一手信息, 版本是本地实际安装的 SDK。

chat completions 没有被弃用。OpenAI 的迁移指南仍把它列为支持, 弃用页没有下线日期; 2026-08-26 关停的是 Assistants API,
替代品是 responses 加 conversations。压力来自模型侧: 迁移指南写明自 GPT-5.4 起 chat completions 只在
`reasoning_effort=none` 时支持工具调用, 且 GPT-6 Astra 与 GPT-6.1 Sol 的工具调用必须走 responses。
因此"只做 chat completions"会随着模型换代逐步失去工具能力。

DeepSeek 在文档里按三种格式分别给出思维链的开关与强度。这张表是 DeepSeek 专属的, 不能当成通用规则:

| 控制项 | chat completions | Anthropic 格式 | responses |
| --- | --- | --- | --- |
| 关闭 | `thinking.type = disabled`(经 extra_body) | 文档未给开关写法 | `reasoning.effort = none` |
| 强度 | `reasoning_effort = low \| high \| max` | `output_config.effort` | `reasoning.effort` |

DeepSeek 的 effort 折叠: `minimal`/`low` 折成 `low`, `medium`/`high`/`xhigh` 折成 `high`, `max`/`ultra` 折成 `max`。
默认开启, 默认 `high`。这层折叠只对声明了 `deepseek_*` quirks 的端点生效; OpenAI 与 Anthropic 的取值集合不同,
由各自的 quirks 决定, 不能统一降级。

DeepSeek responses 是无状态实现: `store` / `previous_response_id` / `conversation` / `background` / `metadata` /
`include` / `prompt` / `truncation` / `service_tier` / `stream_options` 都不支持, 未支持的参数静默忽略而不是报错;
响应里的 `store` 恒为 `false`、`previous_response_id` 恒为 `null`。内置工具只有 `function` 生效, `custom` 仅认
`apply_patch`(为 Codex 兼容), 其余内置工具忽略。

DeepSeek 的流式用量与 OpenAI 不同: 它不会单独下发只含 usage 的块, 统计信息附在最后一个内容块上, 该块 `choices`
只有一个元素、无新增内容且 `finish_reason` 非 null。OpenAI 的做法是 finish_reason 之后再来一个只含 usage 的块。

DeepSeek 带 `tools` 的请求有一个硬约束: 历史轮次的 `reasoning_content` 必须完整回传, 否则返回 400, 即使某轮没有
实际发生工具调用。不带 `tools` 时回传会被忽略。这意味着内部模型里的 assistant 消息必须能携带 reasoning 原文,
"为了省 token 把思维链丢掉"这个优化在工具场景下不成立, 而且正文为空、只有 `reasoning_content` 与 `tool_calls`
的那条 assistant 消息不能被当成空消息丢掉。

Token 记账有两个不能混的口径: OpenAI 系(`prompt_tokens` / `input_tokens`)已经把缓存命中的部分算在内,
`cached_tokens` 只是明细, 再加一次就会翻倍; Anthropic 的 `input_tokens` 只算未命中缓存的余量,
总输入是 `input_tokens + cache_creation_input_tokens + cache_read_input_tokens`(SDK 的 `RawMessageDeltaEvent`
docstring 原文就是这么写的)。统一模型里 `input_tokens` 取总输入, 两个缓存字段只作明细。

Anthropic SDK 1.15.0 的 `messages.create` 没有 `temperature` / `top_p` / `top_k`, 也就是协议层已经移除了采样参数;
停止词仍在(`stop_sequences`)。结构化输出走 `output_config.format`, 只有 `schema`, 没有 OpenAI 侧的 `name`。
`thinking` 有四种配置: `enabled`(必带 `budget_tokens`, 可选 `display`)、`disabled`、`between_tools`、`adaptive`。
`budget_tokens` 至少 1024 且必须小于 `max_tokens`。

两个 SDK 都会自己从环境变量发现凭据与端点: `openai` 在 `api_key=None` 且没有 `OPENAI_API_KEY` 时构造即抛
"Missing credentials"; `anthropic` 会读 `ANTHROPIC_API_KEY` 与 `ANTHROPIC_BASE_URL`。所以库必须显式传入 key
(本地端点用哨兵字符串)与 `base_url`, 不能依赖 SDK 的自动发现, 否则宿主环境里的 key 会被发到配置之外的地方。

两个 SDK 的传输层都已切到 `httpx2`, 不再依赖 `httpx`。构造参数里都有 `http_client` / `base_url` / `max_retries` /
`timeout`, 路由与重试由我们自己接管, 两处都设 `max_retries=0`。代理、超时与连接池通过
`httpx2.AsyncClient(proxy=..., timeout=httpx2.Timeout(connect=..., read=...), limits=...)` 注入, 一个端点一个客户端。
另外两个 SDK 每次请求都会自动生成 `Idempotency-Key`(`stainless-python-retry-{uuid4}`), 接管重试之后必须为一次逻辑
请求固定同一个 key, 否则上游即便支持幂等也认不出是同一次请求。

Gemini 这一代换的是原生 wire: 官方 `google-genai` 客户端把请求发到
`{base_url}/v1beta/models/{model}:streamGenerateContent?alt=sse`, 请求体是 `contents` + `generationConfig`(SDK 侧是
`config`)。三处硬性要求写在协议里:

- 回传工具调用时必须带上那次调用自己的 `thought_signature`, 否则上游 400 明确拒绝; 所以统一的 `ToolCall` 多了一个
  `signature` 字段, 流式拼装时按调用保存, 序列化回请求时放回 `functionCall` part。
- 没有 `tool` 角色, 函数结果放在 user 回合的 `functionResponse` 里, 而且要写函数名而不是 id。
- 思考过程只下发签名不下发正文, `thoughtsTokenCount` 单独计, 不计入 `candidatesTokenCount`。

SDK 的 `http_options` 只能在构造客户端时给, 而 OpenCode Go 要求每个请求都带 `x-opencode-session`, 所以 Gemini 这条路
每次请求现建一个客户端, 跟着流一起关。这是目前唯一的性能妥协, 会话数固定之后再考虑按会话缓存客户端。
`google-genai` 自带自己的 HTTP 客户端(基于 httpx), 不走上面那个 `httpx2.AsyncClient`, 代理与连接池要另配。


## 协议对照

| 项目 | chat completions | responses | Anthropic messages | Gemini generateContent |
| --- | --- | --- | --- | --- |
| 系统提示 | `messages[0].role=system` | `instructions` | `system` 顶层参数 | `config.system_instruction` |
| 状态 | 无状态 | 可 `store`, 也可无状态 | 无状态 | 无状态 |
| 工具声明 | `tools[].function.{name,description,parameters}` | `tools[]` 扁平 `{type,name,parameters}` | `tools[].{name,description,input_schema}` | `tools[].function_declarations[]` |
| 工具结果 | `role=tool` + `tool_call_id` | `function_call_output` + `call_id` | user 消息里的 `tool_result` + `tool_use_id`, 同一轮的多个结果合并进同一条 user 消息 | user 回合里的 `function_response`, 用函数名而不是 id; 没有 tool 角色 |
| 历史里的工具调用 | assistant 的 `tool_calls` | `function_call` item | assistant 的 `tool_use` 块 | model 回合的 `functionCall` part, 必须带 `thought_signature` |
| 图片 | `image_url`(url 或 data url) | `input_image` | `image.source`(base64 / url / file) | `inline_data` / `file_data` |
| 结构化输出 | `response_format.json_schema`(带 name) | `text.format`(带 name) | `output_config.format`(无 name) | `response_mime_type` + `response_schema` |
| 思维链 | `reasoning_content`(DeepSeek) | `reasoning` item | `thinking` 块 + `signature` | `thought` part, 只下发 `thought_signature`, 正文为空 |
| 流式 | `data:` 行, 以 `[DONE]` 结尾 | 命名事件 | 命名事件 | `alt=sse` 的 `data:` 行 |
| 增量事件名 | `choices[].delta` | `response.output_text.delta` / `response.reasoning_text.delta` / `response.function_call_arguments.delta` | `content_block_delta` 里的 `text_delta` / `thinking_delta` / `input_json_delta` / `signature_delta` | 每个分块是一整个 `candidates[].content.parts`, 工具调用一次给全 |
| 正常结束 | `finish_reason` 非空 + `[DONE]` | `response.completed` | `message_delta`(带 `stop_reason`) + `message_stop` | 末块的 `candidates[].finishReason` |
| 异常结束 | 流内 error 块(抛无 status 的 `APIError`) | `response.failed` / 流内 `error` 事件, SDK 都不抛 | 流内 error(抛 `APIStatusError`, 但此时 HTTP 200 已发, `status` 不可信) | 抛 `genai.errors.APIError`, 状态在 `code` 上 |
| 未完成 | `finish_reason=length` | `response.incomplete` + `incomplete_details.reason` | `stop_reason=max_tokens` / `model_context_window_exceeded` | `finishReason=MAX_TOKENS` |
| 用量到达 | finish_reason 之后(OpenAI) / 末块附带(DeepSeek) | `response.completed` 里 | `message_start`(输入) + `message_delta`(输出) | 末块的 `usageMetadata` |
| 缓存明细 | `prompt_tokens_details.{cached_tokens,cache_write_tokens}` | `input_tokens_details.{cached_tokens,cache_write_tokens}` | `cache_read_input_tokens` / `cache_creation_input_tokens` | `cachedContentTokenCount` |
| 推理明细 | `completion_tokens_details.reasoning_tokens` | `output_tokens_details.reasoning_tokens` | `output_tokens_details.thinking_tokens` | `thoughtsTokenCount`(不计入 candidates) |
| 采样参数 | temperature/top_p/stop | temperature/top_p, 无 stop | 无 temperature/top_p, 有 stop_sequences | temperature/top_p/stop_sequences |
| 最大输出 | `max_tokens` 或 `max_completion_tokens` | `max_output_tokens` | `max_tokens`(必填) | `max_output_tokens` |
| 思考开关 | `thinking`(DeepSeek) | `reasoning.effort` | `thinking.type` + `effort` | `thinking_config.thinking_level` |

工具选择的三套写法:

| 统一取值 | chat completions | responses | Anthropic messages | Gemini |
| --- | --- | --- | --- | --- |
| auto | `"auto"` | `"auto"` | `{"type": "auto"}` | `AUTO` |
| none | `"none"` | `"none"` | `{"type": "none"}` | `NONE` |
| required | `"required"` | `"required"` | `{"type": "any"}` | `ANY` |
| 指定工具 | `{"type":"function","function":{"name":...}}` | `{"type":"function","name":...}` | `{"type":"tool","name":...}` | `ANY` + `allowed_function_names` |

## 统一内部模型

消息与内容片段:

```python
TextPart(text)
ImagePart(url=None, data=None, media_type="image/png")
ToolCall(id, name, arguments)          # arguments 保持 JSON 字符串, 不在库内解析
Message(role, parts, tool_calls, tool_call_id, reasoning, signature, is_error)
```

assistant 消息额外携带 `reasoning: str | None` 与 `signature: str | None`, 是"原样带回"的字段, 库不加工:
`reasoning` 对应 DeepSeek 必须回传的 `reasoning_content`, `signature` 对应 Anthropic `thinking` 块的签名。
发送时按固定顺序还原成 Anthropic 的 content 块: thinking(带 signature) → 正文 → 各 tool_use。

已知限制: 一条 assistant 消息里只建模一个 thinking 块。`redacted_thinking` 的不透明 `data` 与 responses 的
`reasoning.encrypted_content` 都没有落点, 这两类历史想原样回传时只能走 `extra_body`。真正需要时把
`parts` 改成有序块列表(Text / Thinking / Redacted / Opaque 混排)是升级路径, 但那会牵动三个协议的翻译层。

`tool_result` 消息带 `is_error`; Anthropic 侧同一轮的多个结果合并进紧跟 assistant 的那条 user 消息,
chat 侧是各自独立的 `role=tool` 消息, responses 侧是独立的 `function_call_output` item。

请求:

```python
CompletionRequest(
    messages, system=None, tools=(), tool_choice=None,
    json_schema=None, json_schema_name="output",
    reasoning=None,            # Reasoning(effort=None, budget_tokens=None)
    max_tokens=None, temperature=None, top_p=None, stop=(),
    extra_body={},
)
```

参数分两类处理:

- 采样类(temperature / top_p / stop): 端点不支持的默认丢弃并记 debug 日志, `endpoint.strict=True` 时改为抛错。
- 能力类(tools / json_schema / 图片): 端点没声明支持就在发请求前抛错, 不能静默降级, 否则上层会拿到一段没有结构
  的文本却以为拿到了 JSON。

流式事件(归一化之后):

```python
TextDelta(text)
ReasoningDelta(text)
SignatureDelta(signature)
ToolCallStart(index, id, name)
ToolCallArgsDelta(index, delta)
Completed(finish_reason, tool_calls, usage)   # usage 可能为 None, 表示上游没报
```

三条约定:

- `index` 是本库重新编号的顺序号。协议原生的 index 语义各不相同(chat 是 tool_calls 数组下标, responses 是
  output item 序号, anthropic 是 content block 序号), 透传上去调用方没法拼参数。
- `Completed` 只在收到正常结束标记之后产出。chat completions 的 usage 在 finish_reason 之后才到, 若在
  finish_reason 处就收尾会拿不到用量; 统一在收流时结账, 三条路径自然一致。
- 异常结束时不产出 `Completed`, 而是抛 `StreamAborted`, 带上已经下发的文本、reasoning、工具调用与已有用量。
  干净 EOF、截断、流内报错三种情况都走这条路, 调用方因此能区分"正常结束"和"只拿到半截"。

错误统一成 `LLMError` 层级, 携带 `endpoint_id`、`kind`、`status`、`retryable`、原始响应体摘要。
流已经打开之后, `status` 不可信(Anthropic 的流内错误挂在 200 响应上), 分类要以异常类型和阶段为准;
只要已经下发过事件, 任何异常都会再包一层 `StreamAborted` 把 partial 带出来。

用量有两种合并语义, 不能混: 同一个请求里流式分片之间用 `Usage.merged`(取较大值, 因为输入输出分两处到达),
跨请求累计用 `Usage.plus`(求和)。

## 路由与容错

端点状态: `healthy` / `degraded`(有失败但未过阈值) / `cooling`(冷却中) / `disabled`(鉴权失败)。

挑选规则: 在模型别名对应的端点组内按轮询取下一个可用端点; 全部在冷却时取冷却最早结束的那个硬着头皮试, 而不是
直接报错; 只有整组都不可用(全部 disabled)才把错误抛给调用方。每次选择都要过端点级并发上限(`asyncio.Semaphore`)。

处置判定表:

| 情况 | 端点 | 这一次请求 |
| --- | --- | --- |
| 401 / 403 | `disabled`, 冷却到进程结束 | 换下一个端点 |
| 429 | 按 `Retry-After`(秒)冷却, 没有该头就用 `2 ** 连续失败次数` | 换下一个端点 |
| 5xx / 超时 / 连接错误 / Anthropic `OverloadedError` | 指数退避冷却, 上限 120 秒 | 首 token 之前换端点, 之后抛 `StreamAborted` |
| 400 / 422, 错误信息指向参数不支持 | 只记失败, 不冷却 | 换下一个端点(该端点的 quirks 需要修正) |
| 400 / 422, 请求本身非法 | 不冷却 | 立即抛 |
| 流内报错 / `response.failed` / 干净 EOF | 记一次失败, 短退避(上限 30 秒) | 抛 `StreamAborted`, 已下发的部分在 `partial` 里 |

重试次数按逻辑请求计(`max_attempts`, 默认 2, 配置里可改), 一次逻辑请求在换端点时沿用同一个 `Idempotency-Key`。
这个键由库自己生成: 两个 SDK 不会替 chat completions / responses / messages 发这个头, 所以"不手动传也有人管"是不成立的。
`Retry-After` 优先于指数退避; 目前只解析秒数形式, HTTP-date 会退回指数退避。

流式失败不重试: 已经吐出去的内容收不回来, 重放会让上层看到重复文本。首 token 之前失败才换端点。
`complete()` 复用同一条流式路径, 因此整段调用同样只在这个窗口内重试, 拿到第一个事件之后就不再换端点。

用量与延迟: 每次成功调用更新端点延迟的指数移动平均与用量累计, 失败只计次数。`Pool.stats()` 暴露每个端点的
调用数、失败数、延迟、累计用量、是否 disabled 与剩余冷却时间; 当前不做成功率加权, 也不做端点粘性。
DeepSeek 的上下文缓存按前缀命中, 换端点会掉缓存, 要不要粘性取决于真实用量里缓存命中的占比。

## 调用与清理

对外两个入口: `stream(request, *, alias=None, session_id=None)` 给出归一化事件的异步生成器,
`complete(...)` 在同一条流上聚合成整段结果。整段调用不另写一套解析。

`session_id` 是给端点用的会话标识: 端点在配置里声明 `session_header` 时, 这个值会写进那个头
(OpenCode Go 要求 `x-opencode-session`, 用于它那边的路由与缓存)。不传就不加这个头。

`max_concurrency` 是单个端点同时进行的流数上限, 信号量覆盖整条流的生命周期, 不是"每秒请求数"。

生成器被取消或提前 `aclose()` 时必须关闭底层 SDK 流, 否则连接会泄在 httpx2 的连接池里。实现上用
`contextlib.aclosing` 包住内层生成器, 并在 finally 里关流、归还端点的并发额度; 关流那一步吞掉取消异常,
免得在已取消的任务里再抛一次。

观测现状: 端点级统计通过 `Pool.stats()` 读; 请求级日志还没实现, 只有失败时的 warning 与被丢弃参数的 debug 日志。
首 token 耗时与"请求耗时的结构化记录"留在未决问题里。

## 配置与凭据

配置走 `lemony_settings`, 建议插件以 `identifier="llm"` 取, 落在 `configs/llm/default.json`:

```json
{
  "default_alias": "chat",
  "aliases": {
    "chat": ["ds-1", "ds-2", "oai-mini"],
    "smart": ["ds-pro"]
  },
  "endpoints": {
    "ds-1": {
      "protocol": "chat",
      "base_url": "https://api.deepseek.com",
      "model": "deepseek-flash",
      "api_key_ref": "llm.ds_1.api_key",
      "quirks": "deepseek_chat",
      "capabilities": {"json_schema": false},
      "strict_params": false,
      "max_concurrency": 4,
      "timeout": 120,
      "session_header": null,
      "extra_headers": {},
      "extra_body": {}
    }
  }
}
```

`api_key_ref` 是凭据键名而不是密钥本身, 由 `lemony_settings.get_secret` 解析(环境变量优先, 其次凭据文件),
`llm.ds_1.api_key` 对应的环境变量是 `MIRAICHAN_LLM_DS_1_API_KEY`。取不到或 `base_url` / `model` 为空都直接报错,
而不是退回 SDK 的环境变量发现。没有鉴权的本地端点用 `api_key_ref: null`, 库传一个哨兵字符串给 SDK。
两个 SDK 还会无条件读取 `OPENAI_CUSTOM_HEADERS` / `ANTHROPIC_CUSTOM_HEADERS`(以及 `OPENAI_ORG_ID` /
`OPENAI_PROJECT_ID`)并注入每个请求, 多端点场景下会把凭据或组织信息发给第三方端点, `Pool` 构造时检测到这些
环境变量会直接拒绝启动。

库导出 `LLMSettings`、`EndpointSpec` 与 `build_specs(settings)`, 由消费方插件自己
`lemony_settings.require(identifier="llm", model=LLMSettings)` 取配置再构建 `Pool`(或用 `Pool.from_settings`);
库不替调用方猜标识符。`timeout` 是读取超时, `connect_timeout` 默认 10 秒, 两者与 `max_concurrency`
一起被注入成每个端点独立的 `httpx2.AsyncClient`; `proxy` 可选。首 token 超时见未决问题。

`base_url` 的形状由 SDK 决定, 写错会拼出双 `/v1` 或者 404:

| 协议 | 配置里的 base_url | SDK 追加 | 最终 URL |
| --- | --- | --- | --- |
| chat | `https://api.deepseek.com` | `/chat/completions` | `https://api.deepseek.com/chat/completions` |
| chat(Go) | `https://opencode.ai/inference/go/openai/v1` | `/chat/completions` | `.../go/openai/v1/chat/completions` |
| responses | `https://api.deepseek.com` | `/responses` | `https://api.deepseek.com/responses` |
| anthropic | `https://opencode.ai/inference/go/anthropic` | `/v1/messages` | `.../go/anthropic/v1/messages` |
| gemini | `https://opencode.ai/inference/go/google` | `/v1beta/models/{model}:streamGenerateContent` | `.../go/google/v1beta/models/gemini-4-argon-contributor:streamGenerateContent` |

`quirks` 不是几个字符串而是三样东西:

- 能力声明: 支持哪些协议参数(有没有 stop、有没有 json_schema、图片走哪种形态、能不能带内置工具),
  端点可以用 `capabilities` 覆盖其中一项, 用来吸收同一预设下个别模型的差异
- 参数映射: `max_tokens` 还是 `max_completion_tokens`、thinking 的落点(chat 的 `thinking` / anthropic 的
  `adaptive` 或 `enabled` / responses 的 `reasoning.effort`)、tool_choice 形态、effort 折叠表
- 默认值与约束: chat 必须带 `stream_options={"include_usage": true}` 否则没有用量、Anthropic `max_tokens` 必填、
  `budget_tokens >= 1024 && < max_tokens`、聚合站需要的额外头(
  OpenRouter 的 `HTTP-Referer` / `X-Title`, 配在 `extra_headers`)、`include=["reasoning.encrypted_content"]` 等

SDK 原生签名里没有的字段一律走 `extra_body`, 不能当关键字参数展开, 否则调用处直接 `TypeError`。

随库提供的预设: `deepseek_chat` / `deepseek_responses` / `deepseek_anthropic` / `openai_chat` / `openai_responses` /
`anthropic` / `anthropic_budgeted` / `gemini` / `generic`。预设跟**模型**走而不是跟中转走: OpenCode Go 上的 DeepSeek 一样用
`deepseek_chat`, 聚合站自己的差异(额外头、会话头)放端点配置。
`strict_params` 打开之后, 采样参数被丢弃不再是 debug 日志而是 `LLMConfigError`。

## 验证

分两层。

`tests/` 下的假端点按三种协议的真实 SSE 形状返回同一段内容(两段思维链、两段正文、两个工具调用、一份含缓存读写的
用量), 再用真实的 `openai` / `anthropic` SDK 去打它, 断言覆盖:

- 请求翻译: 三套协议的 system / 工具结构 / 结构化输出 / stop / 用量开关落点, 以及哪些参数被记为丢弃和哪些走
  `extra_body`; 响应侧固定带 `store: false`
- effort 折叠与 thinking 开关: `minimal`/`xhigh`/`ultra` 的折叠、`none` 关掉 thinking、Anthropic 预算约束提前报错
- 回传: assistant 的 `reasoning_content`、带 signature 的 thinking 块、两个工具调用、合并后的 tool_result
- 路由: 鉴权失败后端点被禁用并换到下一个、429 之后冷却不再被选中、换端点时幂等键不变、能力缺失在发请求前就拒绝、
  端点统计可读、提前关闭流之后并发额度立刻归还
- 流式: 三条路径的语义(text / reasoning / 工具调用 / 结束原因 / 用量)一致, 工具调用 id 各自非空不重复;
  DeepSeek 末块 usage 形状; 断流在三条路径上都判为截断并带出 partial(含 reasoning、工具调用、签名);
  `response.failed` 抛错; `response.incomplete` 判为 length

`tools/llm_smoke.py` 打真实端点。2026-10-18 用 OpenCode Go 与 DeepSeek 官方各跑一遍
(chat 走 `deepseek-v4.1-flash`, responses 走 `gpt-6-luna` 与 `deepseek-v4-flash`, anthropic 走 `claude-haiku-5-5`),
五个端点全部通过: 文本流、reasoning、图片输入(纯色小图三套协议都能答对颜色)、工具调用、工具结果回填后的第二轮、
结构化输出。真端点暴露了三件假端点测不到的事:

- 新一代 Claude 拒绝 `thinking.type=enabled`, 要求 `thinking.type=adaptive` 加 `output_config.effort`。
  于是 quirks 里加了 `anthropic_thinking_style`, 老模型才用 `enabled` 加 `budget_tokens`
- DeepSeek 的 chat 侧不接受 `response_format: json_schema`(报 "This response_format type is unavailable now"),
  只有 responses 的 `text.format` 认; 这条差异现在由 `deepseek_chat` 的能力声明表达, 请求会在发送前被拒
- Claude 不出思维链这件事是上游在变: 从 Opus 4.7 起思维链正文默认不下发, 要 `display=summarized` 才给,
  而社区报告里连显式 `summarized` 也有拿到空正文只带签名的情况(theregister 2026-08-14, claude-code#56356)。
  所以这个现象不算本库的问题, 但签名回传因此还没在真端点上验证过

`tools/llm_load_balance.py` 验证多 key 轮询。NVIDIA NIM 那边有 6 个 key, `z-ai/glm-5.3-flash` 可用:
6 次请求正好摊到 6 个端点上; 在最前面插一个无效 key 的端点后, 它被 403 判成鉴权失败并 disabled,
请求自动落到健康的三个 key 上, 后续轮询在两两之间平均分布。这条路径同时验证了鉴权失败后换端点、
冷却/禁用状态跨请求保留, 以及 `Pool.stats()` 的计数。

## 未决问题

1. 一条 assistant 消息里出现多个 thinking 块(或 `redacted_thinking`、responses 的 `encrypted_content`)时怎么回传。
   现在只留了单块字段, 升级成有序块列表要动三个翻译层。
2. Claude 的思维链不出现在响应里: 上游从 Opus 4.7 起默认不下发思维链正文, `display` 设为 `summarized` 是
   官方推荐的做法; 但社区仍报告拿到"空正文 + 签名"的块。实现已经能原样回传只带签名的 thinking 块,
   端到端的签名验证等上游稳定下来再做。
3. Anthropic 侧 `temperature` / `top_p` 已经能按能力声明走 `extra_body`, 但服务端是否接受没有验证。
4. 首 token 超时(TTFT)如何实现。SDK 只有请求级 `timeout`, 需要自己包一层 `asyncio.wait_for` 并在超时后关闭底层流。
5. 429 的处理: 是换端点还是本端点退避。现在按"换端点 + 记冷却"处理, 单 key 场景下等于直接失败。
6. 多 key 轮询的失败计数粒度: 现在按端点累计, 要不要拆成(端点, 错误类型)。
7. 是否需要会话粘性(为了 DeepSeek 的前缀缓存), 取决于真实用量里缓存命中的占比。
8. 结构化输出与工具调用同时开启的行为, 三套协议都没有明确文档; 当前实现会照发, 由上游决定。
9. `between_tools` 这种 thinking 配置语义未确认, 暂不暴露。
10. 请求级日志与首 token 耗时还没做: 现在只有端点级统计(`Pool.stats()`)与失败时的 warning。
11. `Retry-After` 只解析秒数, HTTP-date 形式会退回指数退避。
12. Gemini 每次请求现建客户端(为了逐请求的会话头), 会话数稳定后应按会话缓存, 否则每个请求都要新建连接池。

## 现状与下一步

已经就位: `models.py`(统一模型与事件)、`errors.py`(错误层级与 SDK 映射)、`quirks.py`(预设与能力覆盖)、
`protocols/`(三套 translate 与 parse)、`client.py`(端点池 + 轮询 + 冷却 + 记账)、`settings.py`(配置模型),
配套 `tests/` 的假端点回归与 `tools/llm_smoke.py` 的真端点 smoke。

下一步:

1. 接第一个消费插件(LLM 聊天), 插件侧用 `require(identifier="llm", model=LLMSettings)` 取配置
2. 在插件里补用量记账与按群/按用户的重试与截断策略
3. 未决问题里第 2 条(Claude 思维链)解决之前, Anthropic 侧不保证 thinking 回传可用
