## 🤖 Assistant

# 自己写一个纯异步 OpenAI 兼容层的可行性分析

## 先看看现有方案的生态

让我先快速了解下现有项目的状况，方便做对比：

好的，信息够了。下面给出全面的分析。

---

## 一、总体结论

**难度：中等偏低。实用性：很高。值得做。**

你的定位非常精准——"当库用"而非"当服务跑"，只做 OpenAI 兼容协议内的事，这就把问题域砍掉了一大半。核心工作量集中在 **SSE 流式转发 + 多 key 路由 + 厂商非标字段适配** 三块，这些每块单独都不难，组合起来的架构也很清晰。

---

## 二、与现有方案的对比——为什么不直接用 LiteLLM

| 维度 | LiteLLM | 自己写 |
|---|---|---|
| 覆盖面 | 100+ 提供商，含 Bedrock/VertexAI 等非 OpenAI 协议 | 只做 OpenAI 兼容协议 |
| 依赖 | 巨大（18000+ commits，引入大量可选依赖） | `httpx` + `pydantic` 即可 |
| 代码控制 | 黑盒，升级常有 breaking change | 完全可控 |
| 异步支持 | 有，但混合了 sync/async，内部用 ThreadPoolExecutor | 纯 async，干净 |
| 非标字段 | 覆盖面广但抽象层厚，出了问题难调 | 按需写，透明 |
| 部署形态 | SDK + Proxy Server 双模式，但作为库用时仍拖着 proxy 的代码 | 纯库 |

**核心痛点**：LiteLLM 是"做大做全"的思路，对于你这种"只在 Python 进程内当库用、只关心 OpenAI 兼容协议"的场景来说，它太重了，而且你无法精细控制路由逻辑和错误处理。

---

## 三、技术难度拆解

### 3.1 核心层：OpenAI Chat Completion 兼容（难度 ★★☆☆☆）

这是最基础的部分。协议本身就是 HTTP POST + SSE，用 `httpx.AsyncClient` 几十行就能搞定：

```python
from dataclasses import dataclass, field
from typing import AsyncIterator
import httpx

@dataclass
class Endpoint:
    base_url: str
    api_key: str
    model: str
    # 厂商非标字段注入
    extra_headers: dict[str, str] = field(default_factory=dict)
    extra_body: dict[str, object] = field(default_factory=dict)

async def stream_completion(
    client: httpx.AsyncClient,
    endpoint: Endpoint,
    messages: list[dict],
    **kwargs,
) -> AsyncIterator[bytes]:
    """核心：流式 SSE 转发"""
    body = {"model": endpoint.model, "messages": messages, "stream": True, **kwargs}
    body.update(endpoint.extra_body)

    headers = {"Authorization": f"Bearer {endpoint.api_key}", **endpoint.extra_headers}

    async with client.stream(
        "POST",
        f"{endpoint.base_url}/v1/chat/completions",
        json=body,
        headers=headers,
        timeout=120.0,
    ) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if line.startswith("data: "):
                yield line
```

### 3.2 厂商非标字段适配（难度 ★★★☆☆）

这是最繁琐但不算难的部分。以下是主要差异的整理：

| 厂商 | 非标行为 |
|---|---|
| **DeepSeek** | `reasoning_content` 字段（思维链）在 delta 中；`usage` 在流式中需要 `stream_options: {"include_usage": true}` |
| **Qwen (通义)** | `enable_search` 参数；`result_format: "message"` 历史遗留；`top_k` 叫 `top_p` 但行为微妙不同 |
| **智谱 (GLM)** | `tool_choice` 格式略有差异；部分模型不支持 `temperature` < 0.01 |
| **月之暗面 (Kimi)** | `search_result` 在 choices 里额外返回；超长上下文走不同 endpoint |
| **百度 (ERNIE)** | token 是 access_token 而非 Bearer；但其 OpenAI 兼容层基本标准 |
| **Minimax** | `reply_constraints` 等非标参数；`bot_setting` |
| **各家通用** | `usage.prompt_tokens_details` / `completion_tokens_details` 字段不统一 |

**推荐策略**：不要为每个厂商写 adapter class，而是用声明式配置：

```python
@dataclass
class ProviderQuirks:
    """声明式厂商兼容配置"""
    # 流式时自动注入 stream_options
    inject_stream_options: bool = False
    # 思维链字段名映射
    reasoning_content_field: str | None = None
    # 需要移除的不支持参数
    unsupported_params: set[str] = field(default_factory=set)
    # 请求体字段重命名
    param_aliases: dict[str, str] = field(default_factory=dict)
    # 温度下限
    min_temperature: float | None = None

PROVIDER_QUIRKS: dict[str, ProviderQuirks] = {
    "deepseek": ProviderQuirks(
        inject_stream_options=True,
        reasoning_content_field="reasoning_content",
    ),
    "glm": ProviderQuirks(
        min_temperature=0.01,
        unsupported_params={"logprobs"},
    ),
    # ...按需扩展
}
```

这样每个新厂商接入只需要增加一个配置条目，不用写代码。

### 3.3 多 Key / 多服务商路由与负载均衡（难度 ★★★☆☆）

这是你方案里最有价值的部分。核心设计：

```python
import asyncio
import time
import random
from enum import Enum

class EndpointStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"    # 高延迟/部分失败
    COOLDOWN = "cooldown"    # 冷却中，暂不使用

@dataclass
class EndpointState:
    endpoint: Endpoint
    status: EndpointStatus = EndpointStatus.HEALTHY
    # 指数退避冷却
    consecutive_failures: int = 0
    cooldown_until: float = 0.0
    # 统计
    total_requests: int = 0
    total_failures: int = 0
    avg_latency_ms: float = 0.0
    # 并发控制
    inflight: int = 0

class Router:
    """多 key 负载均衡路由器"""
    def __init__(self, endpoints: list[Endpoint], strategy: str = "weighted_random"):
        self._states = [EndpointState(ep) for ep in endpoints]
        self._strategy = strategy
        self._lock = asyncio.Lock()

    def _available(self) -> list[EndpointState]:
        now = time.monotonic()
        return [s for s in self._states
                if s.status != EndpointStatus.COOLDOWN or now >= s.cooldown_until]

    async def pick(self) -> EndpointState:
        """选择一个可用 endpoint"""
        available = self._available()
        if not available:
            # 所有都在冷却 -> 选冷却时间最短的（低可靠性容错）
            available = sorted(self._states, key=lambda s: s.cooldown_until)
        if self._strategy == "least_inflight":
            return min(available, key=lambda s: s.inflight)
        else:  # weighted_random: 按成功率加权
            weights = [1.0 / (1 + s.consecutive_failures) for s in available]
            return random.choices(available, weights=weights, k=1)[0]

    async def report_success(self, state: EndpointState, latency_ms: float) -> None:
        state.consecutive_failures = 0
        state.status = EndpointStatus.HEALTHY
        # 指数移动平均更新延迟
        state.avg_latency_ms = state.avg_latency_ms * 0.8 + latency_ms * 0.2

    async def report_failure(self, state: EndpointState) -> None:
        state.consecutive_failures += 1
        state.total_failures += 1
        # 指数退避冷却: 2^n 秒, 最大 120 秒
        cooldown = min(2 ** state.consecutive_failures, 120)
        state.cooldown_until = time.monotonic() + cooldown
        state.status = EndpointStatus.COOLDOWN
```

**低可靠性体验优化**要点：

- 指数退避冷却（不是一刀切拉黑）
- 全部冷却时仍选"最快恢复的"那个尝试（而非直接报错）
- 流式中途断流 -> 记录已收到的 token -> 自动 fallback 到下一个 endpoint 重新请求（可选，但这是杀手级体验优化）
- 请求级别超时 + 首 token 超时（TTFT）分开控制

### 3.4 上层 API 封装（难度 ★★☆☆☆）

作为库使用，对外暴露的 API 应该长这样：

```python
from typing import AsyncIterator
from pydantic import BaseModel

class CompletionChunk(BaseModel):
    """统一的流式 chunk 类型"""
    id: str
    content: str | None = None
    reasoning_content: str | None = None  # 统一提取的思维链
    finish_reason: str | None = None
    usage: dict | None = None

class LLMPool:
    """对外暴露的主入口"""
    def __init__(self, config: PoolConfig):
        self._router = Router(...)
        self._client = httpx.AsyncClient(http2=True, limits=httpx.Limits(...))

    async def completion(
        self,
        messages: list[dict],
        model: str | None = None,
        *,
        stream: bool = True,
        max_retries: int = 3,
        **kwargs,
    ) -> AsyncIterator[CompletionChunk]:
        """带自动重试和 fallback 的 completion"""
        for attempt in range(max_retries):
            state = await self._router.pick()
            try:
                async for chunk in self._do_request(state, messages, **kwargs):
                    yield chunk
                return  # 成功完成
            except (httpx.HTTPStatusError, httpx.ReadTimeout) as e:
                await self._router.report_failure(state)
                if attempt == max_retries - 1:
                    raise

    async def completion_text(self, messages: list[dict], **kwargs) -> str:
        """便捷方法：收集完整文本"""
        parts: list[str] = []
        async for chunk in self.completion(messages, **kwargs):
            if chunk.content:
                parts.append(chunk.content)
        return "".join(parts)
```

---

## 四、工作量估算

| 模块 | 预估工作量 | 说明 |
|---|---|---|
| httpx 流式请求核心 | 0.5 天 | 很简单 |
| SSE 解析 + chunk 标准化 | 0.5 天 | 处理 `data:` 行解析、`[DONE]` |
| 厂商非标适配框架 + 首批 3-4 家 | 1 天 | DeepSeek/Qwen/GLM/OpenAI |
| 路由器 + 负载均衡 + 冷却策略 | 1-1.5 天 | 含单测 |
| 错误处理 + 自动重试 + fallback | 1 天 | 包括流式中途失败 |
| pydantic config + 类型注解 | 0.5 天 | |
| 基本测试 | 1 天 | |
| **合计** | **~5-6 天** | 一个人，不赶进度 |

---

## 五、建议的技术栈和依赖

```toml
[project]
requires-python = ">=3.12"
dependencies = [
    "httpx[http2]>=0.28",
    "pydantic>=2.10",
]

[project.optional-dependencies]
server = ["starlette", "uvicorn"]  # 可选的 HTTP 暴露
```

**总共两个依赖**。对比 LiteLLM 的几十个依赖，轻量得多。

---

## 六、注意事项和潜在坑

1. **SSE 解析看似简单但有暗坑**：有些厂商在 chunk 之间发空行、有些不发 `[DONE]`、有些在流的最后一个 chunk 附带 usage。需要做防御性解析。

2. **流式重试的一致性问题**：流式传输中途失败后重试，调用方已经收到了部分内容。你需要决定：(a) 直接报错让上层处理，还是 (b) 重发完整请求但只 yield 后续部分（需要上层配合）。建议先做 (a)，简单可靠。

3. **并发限制**：同一 API key 的 RPM/TPM 限制。可以在 `EndpointState` 里加令牌桶或滑动窗口，按 key 级别限流。

4. **HTTP/2 的收益**：`httpx` 支持 HTTP/2 多路复用，对同一 `base_url` 的多个并发请求可以复用连接，值得开启。

5. **Responses API**：OpenAI 正在推 `/v1/responses` 新协议（取代 `/v1/chat/completions`），目前各厂商基本没跟进，短期内不用管，但架构上可以预留。

---

## 七、关于跨协议兼容（顺带一提）

你说跨协议不在计划内，但提一下：

- **Anthropic Messages API**：与 OpenAI 格式差异很大（`content` 是数组、流式格式完全不同、tool_use 结构不同）。要兼容需要写完整的请求/响应转换层，工作量大概 +2-3 天/厂商。
- **Google Gemini**：也是自己的格式。
- 如果未来需要，建议用 **Adapter 模式** 预留接口，但当前不实现：

```python
class ProtocolAdapter(Protocol):
    async def to_request(self, messages, **kwargs) -> tuple[str, dict, dict]: ...
    async def from_sse_line(self, line: str) -> CompletionChunk | None: ...

class OpenAIAdapter(ProtocolAdapter): ...  # 当前实现这个
# class AnthropicAdapter(ProtocolAdapter): ...  # 未来需要时再加
```

---

## 八、总结

| 维度 | 评估 |
|---|---|
| 难度 | **中等偏低**。纯 I/O 转发 + 路由逻辑，没有复杂算法 |
| 实用性 | **很高**。比 LiteLLM 轻 10 倍，完全可控，纯 async |
| 维护成本 | **低**。新厂商接入 = 加一个配置项 |
| 风险 | **低**。最坏情况也能 fallback 到直接用 `openai` 官方 SDK |
| 建不建议做 | **建议做**。你的场景（Python 进程内当库用、只做 OpenAI 兼容、需要多 key 路由）正好是现有方案覆盖不好的甜点区 |

简单说：**5-6 天的投入，换来一个两个依赖、纯 async、完全可控的 LLM 网关库**，性价比很高。
