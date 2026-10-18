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

## 协议对照

| 项目 | chat completions | responses | Anthropic messages |
| --- | --- | --- | --- |
| 系统提示 | `messages[0].role=system` | `instructions` | `system` 顶层参数 |
| 状态 | 无状态 | 可 `store`, 也可无状态 | 无状态 |
| 工具声明 | `tools[].function.{name,description,parameters}` | `tools[]` 扁平 `{type,name,parameters}` | `tools[].{name,description,input_schema}` |
| 工具结果 | `role=tool` + `tool_call_id` | `function_call_output` + `call_id` | user 消息里的 `tool_result` + `tool_use_id`, 同一轮的多个结果合并进同一条 user 消息 |
| 历史里的工具调用 | assistant 的 `tool_calls` | `function_call` item | assistant 的 `tool_use` 块 |
| 图片 | `image_url`(url 或 data url) | `input_image` | `image.source`(base64 / url / file) |
| 结构化输出 | `response_format.json_schema`(带 name) | `text.format`(带 name) | `output_config.format`(无 name) |
| 思维链 | `reasoning_content`(DeepSeek) | `reasoning` item | `thinking` 块 + `signature` |
| 流式 | `data:` 行, 以 `[DONE]` 结尾 | 命名事件 | 命名事件 |
| 增量事件名 | `choices[].delta` | `response.output_text.delta` / `response.reasoning_text.delta` / `response.function_call_arguments.delta` | `content_block_delta` 里的 `text_delta` / `thinking_delta` / `input_json_delta` / `signature_delta` |
| 正常结束 | `finish_reason` 非空 + `[DONE]` | `response.completed` | `message_delta`(带 `stop_reason`) + `message_stop` |
| 异常结束 | 流内 error 块(抛无 status 的 `APIError`) | `response.failed` / 流内 `error` 事件, SDK 都不抛 | 流内 error(抛 `APIStatusError`, 但此时 HTTP 200 已发, `status` 不可信) |
| 未完成 | `finish_reason=length` | `response.incomplete` + `incomplete_details.reason` | `stop_reason=max_tokens` / `model_context_window_exceeded` |
| 用量到达 | finish_reason 之后(OpenAI) / 末块附带(DeepSeek) | `response.completed` 里 | `message_start`(输入) + `message_delta`(输出) |
| 缓存明细 | `prompt_tokens_details.{cached_tokens,cache_write_tokens}` | `input_tokens_details.{cached_tokens,cache_write_tokens}` | `cache_read_input_tokens` / `cache_creation_input_tokens` |
| 推理明细 | `completion_tokens_details.reasoning_tokens` | `output_tokens_details.reasoning_tokens` | `output_tokens_details.thinking_tokens` |
| 采样参数 | temperature/top_p/stop | temperature/top_p, 无 stop | 无 temperature/top_p, 有 stop_sequences |
| 最大输出 | `max_tokens` 或 `max_completion_tokens` | `max_output_tokens` | `max_tokens`(必填) |

工具选择的三套写法:

| 统一取值 | chat completions | responses | Anthropic messages |
| --- | --- | --- | --- |
| auto | `"auto"` | `"auto"` | `{"type": "auto"}` |
| none | `"none"` | `"none"` | `{"type": "none"}` |
| required | `"required"` | `"required"` | `{"type": "any"}` |
| 指定工具 | `{"type":"function","function":{"name":...}}` | `{"type":"function","name":...}` | `{"type":"tool","name":...}` |

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
流已经打开之后, `status` 不可信(Anthropic 的流内错误挂在 200 响应上), 分类要以异常类型和阶段为准。

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
| 400 / 422, 错误信息指向参数不支持 | 不冷却 | 换下一个端点(该端点的 quirks 需要修正) |
| 400 / 422, 请求本身非法 | 不冷却 | 立即抛 |
| 流内报错 / `response.failed` / 干净 EOF | 记一次失败, 不重试 | 抛 `StreamAborted` |

重试次数按逻辑请求计(`max_attempts`, 默认 2), 一次逻辑请求在换端点时必须沿用同一个 `Idempotency-Key`。
`Retry-After` 优先于指数退避。

流式失败不重试: 已经吐出去的内容收不回来, 重放会让上层看到重复文本。整段调用因为调用方还没拿到内容,
允许在整个请求层重试。

用量与延迟: 每次调用(含失败)更新端点延迟指数移动平均与用量累计, 用于日志与后续权重策略。当前只做轮询,
不做成功率加权; 也不做端点粘性。DeepSeek 的上下文缓存按前缀命中, 换端点会掉缓存, 要不要粘性取决于真实用量
里缓存命中的占比。

## 调用与清理

对外两个入口: `stream(request)` 给出归一化事件的异步生成器, `complete(request)` 在库内把同一条流聚合成整段结果。
整段调用复用流式路径, 不另写第二套解析; 端点明确不支持流式时才回落到非流式请求, 再把响应转成同样的事件序列。

生成器被取消或提前 `aclose()` 时必须关闭底层 SDK 流, 否则连接会泄在 httpx2 的连接池里。实现上用
`async with stream:` 或显式 `await stream.close()`, 并在 finally 里归还端点的并发额度。

日志记录端点 id、模型、耗时、首 token 耗时、用量、停止原因与错误分类; 不记录 prompt 与正文。需要排查时用
debug 级别单独开关, 截断长度可配。

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
`llm.ds_1.api_key` 对应的环境变量是 `MIRAICHAN_LLM_DS_1_API_KEY`。取不到就报错, 而不是退回 SDK 的环境变量发现。
没有鉴权的本地端点用 `api_key_ref: null`, 库传一个哨兵字符串给 SDK。

库导出 `LLMSettings`、`EndpointSpec` 与 `build_specs(settings)`, 由消费方插件自己
`lemony_settings.require(identifier="llm", model=LLMSettings)` 取配置再构建 `Pool`; 库不替调用方猜标识符。
`timeout` 按端点配置, 默认连接 10 秒、读取 120 秒; 首 token 超时见未决问题。

`quirks` 不是几个字符串而是三样东西:

- 能力声明: 支持哪些协议参数(有没有 stop、有没有 json_schema、图片走哪种形态、能不能带内置工具),
  端点可以用 `capabilities` 覆盖其中一项, 用来吸收同一预设下个别模型的差异
- 参数映射: `max_tokens` 还是 `max_completion_tokens`、thinking 的落点(chat 的 `thinking` / anthropic 的
  `adaptive` 或 `enabled` / responses 的 `reasoning.effort`)、tool_choice 形态、effort 折叠表
- 默认值与约束: chat 必须带 `stream_options={"include_usage": true}` 否则没有用量、Anthropic `max_tokens` 必填、
  `budget_tokens >= 1024 && < max_tokens`、base_url 要不要带 `/v1`、聚合站需要的额外头(
  OpenRouter 的 `HTTP-Referer` / `X-Title`)、`include=["reasoning.encrypted_content"]` 等

随库提供的预设: `deepseek_chat` / `deepseek_responses` / `deepseek_anthropic` / `openai_chat` / `openai_responses` /
`anthropic` / `anthropic_budgeted` / `opencode_go_chat` / `opencode_go_responses` / `opencode_go_anthropic` / `generic`。
`strict_params` 打开之后, 采样参数被丢弃不再是 debug 日志而是 `LLMConfigError`。

## 验证

分两层。

`tests/` 下的假端点按三种协议的真实 SSE 形状返回同一段内容(两段思维链、两段正文、两个工具调用、一份含缓存读写的
用量), 再用真实的 `openai` / `anthropic` SDK 去打它, 断言覆盖:

- 请求翻译: 三套协议的 system / 工具结构 / 结构化输出 / stop / 用量开关落点, 以及哪些参数被记为丢弃
- effort 折叠与 thinking 开关: `minimal`/`xhigh`/`ultra` 的折叠、`none` 关掉 thinking、Anthropic 预算约束提前报错
- 回传: assistant 的 `reasoning_content`、带 signature 的 thinking 块、两个工具调用、合并后的 tool_result
- 路由: 鉴权失败后端点被禁用并换到下一个、429 之后冷却不再被选中、能力缺失在发请求前就拒绝
- 流式: 三条路径的语义(text / reasoning / 工具调用 / 结束原因 / 用量)一致, 工具调用 id 各自非空不重复;
  DeepSeek 末块 usage 形状; 断流在三条路径上都判为截断; `response.failed` 抛错; `response.incomplete` 判为 length

`tools/llm_smoke.py` 打真实端点。2026-10-18 用 OpenCode Go 与 DeepSeek 官方各跑一遍
(chat 走 `deepseek-v4.1-flash`, responses 走 `gpt-6-luna` 与 `deepseek-v4-flash`, anthropic 走 `claude-haiku-5-5`),
五个端点全部通过: 文本流、reasoning、工具调用、工具结果回填后的第二轮、结构化输出。真端点暴露了三件假端点测不到的事:

- 新一代 Claude 拒绝 `thinking.type=enabled`, 要求 `thinking.type=adaptive` 加 `output_config.effort`。
  于是 quirks 里加了 `anthropic_thinking_style`, 老模型才用 `enabled` 加 `budget_tokens`
- DeepSeek 的 chat 侧不接受 `response_format: json_schema`(报 "This response_format type is unavailable now"),
  只有 responses 的 `text.format` 认; 这条差异现在由 `deepseek_chat` 的能力声明表达, 请求会在发送前被拒
- Claude 在 adaptive 加 `display=summarized` 下仍然没有吐出 thinking 块, 所以签名回传这条链路在真端点上还没被验证过

## 未决问题

1. 一条 assistant 消息里出现多个 thinking 块(或 `redacted_thinking`、responses 的 `encrypted_content`)时怎么回传。
   现在只留了单块字段, 升级成有序块列表要动三个翻译层。
2. Claude 的思维链为什么不出现: 是 `display` 取值不对、Go 中转把它剥掉了, 还是这个模型默认不流式吐 thinking。
   签名回传的端到端验证卡在这里。
3. Anthropic 侧 `temperature` 是否还能通过 `extra_body` 透传。SDK 类型层已移除, 服务端是否接受未验证。
4. 首 token 超时(TTFT)如何实现。SDK 只有请求级 `timeout`, 需要自己包一层 `asyncio.wait_for` 并在超时后关闭底层流。
5. 429 的处理: 是换端点还是本端点退避。现在按"换端点 + 记冷却"处理, 单 key 场景下等于直接失败。
6. 多 key 轮询的失败计数粒度: 按端点累计还是按(端点, 错误类型)累计。
7. 是否需要会话粘性(为了 DeepSeek 的前缀缓存), 取决于真实用量里缓存命中的占比。
8. 结构化输出与工具调用同时开启的行为, 三套协议都没有明确文档; 当前实现会照发, 由上游决定。
9. `between_tools` 这种 thinking 配置语义未确认, 暂不暴露。

## 现状与下一步

已经就位: `models.py`(统一模型与事件)、`errors.py`(错误层级与 SDK 映射)、`quirks.py`(预设与能力覆盖)、
`protocols/`(三套 translate 与 parse)、`client.py`(端点池 + 轮询 + 冷却 + 记账)、`settings.py`(配置模型),
配套 `tests/` 的假端点回归与 `tools/llm_smoke.py` 的真端点 smoke。

下一步:

1. 接第一个消费插件(LLM 聊天), 插件侧用 `require(identifier="llm", model=LLMSettings)` 取配置
2. 在插件里补用量记账与按群/按用户的重试与截断策略
3. 未决问题里第 2 条(Claude 思维链)解决之前, Anthropic 侧不保证 thinking 回传可用
