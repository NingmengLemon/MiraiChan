"""端点差异: 能力声明 + 参数映射 + 默认值

协议本身由 translate 层处理, 这里只放"同一个协议在不同厂商/中转上有出入"的部分。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Literal

from .models import DEEPSEEK_EFFORT, Effort


@dataclass(frozen=True)
class Quirks:
    # 能力: 不支持的能力类参数在发请求前就要拦下, 不能静默降级
    supports_tools: bool = True
    supports_json_schema: bool = True
    supports_images: bool = True

    # 采样类参数: 不支持就丢弃并记日志
    supports_temperature: bool = True
    supports_top_p: bool = True
    supports_stop: bool = True

    # chat completions 的落点差异
    max_tokens_field: str = "max_tokens"
    send_include_usage: bool = True
    # effort=none 时怎么关思考: "thinking_param" 发 thinking.disabled, "omit" 什么都不发
    thinking_off_style: Literal["thinking_param", "omit"] = "omit"
    effort_map: dict[str, str] = field(default_factory=dict)

    # anthropic 的约束
    anthropic_default_max_tokens: int = 4096
    anthropic_min_budget_tokens: int = 1024
    # 新一代 Claude 只认 thinking.type=adaptive 加 output_config.effort,
    # 老模型才用 thinking.type=enabled 加 budget_tokens
    anthropic_thinking_style: Literal["adaptive", "budget"] = "adaptive"

    def fold_effort(self, effort: Effort) -> str:
        return self.effort_map.get(effort, effort)

    def supports_capability(self, name: str) -> bool:
        return {
            "tools": self.supports_tools,
            "json_schema": self.supports_json_schema,
            "images": self.supports_images,
        }[name]


_GENERIC = Quirks()

_PRESETS: dict[str, Quirks] = {
    "generic": _GENERIC,
    # OpenAI 官方: 新模型用 max_completion_tokens, responses 没有 stop
    "openai_chat": Quirks(max_tokens_field="max_completion_tokens"),
    "openai_responses": Quirks(
        max_tokens_field="max_output_tokens", supports_stop=False
    ),
    "anthropic": Quirks(supports_temperature=False, supports_top_p=False),
    # 老一代 Claude 才支持 thinking.type=enabled 加预算
    "anthropic_budgeted": Quirks(
        supports_temperature=False,
        supports_top_p=False,
        anthropic_thinking_style="budget",
    ),
    # DeepSeek: 新模型用 max_tokens, 思考开关走 thinking, effort 只有 low/high/max;
    # chat 侧的 response_format 只认 text / json_object, 不认 json_schema
    "deepseek_chat": Quirks(
        max_tokens_field="max_tokens",
        thinking_off_style="thinking_param",
        effort_map=DEEPSEEK_EFFORT,
        supports_json_schema=False,
    ),
    "deepseek_responses": Quirks(
        max_tokens_field="max_output_tokens",
        supports_stop=False,
        effort_map=DEEPSEEK_EFFORT,
    ),
    "deepseek_anthropic": Quirks(
        supports_temperature=False,
        supports_top_p=False,
        effort_map=DEEPSEEK_EFFORT,
    ),
    # Gemini 原生协议: 没有 stop 的独立字段以外的坑, 采样参数都能用
    "gemini": Quirks(max_tokens_field="max_output_tokens"),
    # 聚合站自己的差异 (额外头、会话头) 属于端点配置, 不在这里;
    # 模型差异用 capabilities 覆盖已有的预设
}


def resolve_quirks(name: str) -> Quirks:
    try:
        return _PRESETS[name]
    except KeyError:
        known = ", ".join(sorted(_PRESETS))
        raise ValueError(f"未知 quirks 预设 {name!r}, 可用: {known}") from None


def preset_names() -> list[str]:
    return sorted(_PRESETS)


_CAPABILITY_FIELDS = {
    "tools": "supports_tools",
    "json_schema": "supports_json_schema",
    "images": "supports_images",
    "temperature": "supports_temperature",
    "top_p": "supports_top_p",
    "stop": "supports_stop",
}


def apply_capabilities(quirks: Quirks, overrides: Mapping[str, bool]) -> Quirks:
    """按端点覆盖能力声明, 用来吸收同一预设下个别模型的差异"""
    unknown = set(overrides) - set(_CAPABILITY_FIELDS)
    if unknown:
        known = ", ".join(sorted(_CAPABILITY_FIELDS))
        raise ValueError(f"未知能力 {', '.join(sorted(unknown))}, 可用: {known}")
    return replace(
        quirks, **{_CAPABILITY_FIELDS[name]: value for name, value in overrides.items()}
    )
