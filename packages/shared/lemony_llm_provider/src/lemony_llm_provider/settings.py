"""端点配置 (兼容 lemony_settings 的配置模型)"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from lemony_settings.models import BaseSettings
from pydantic import Field

from .errors import LLMConfigError
from .quirks import Quirks, apply_capabilities, resolve_quirks

Protocol = Literal["chat", "responses", "anthropic"]


class EndpointSettings(BaseSettings):
    protocol: Protocol = "chat"
    base_url: str = ""
    model: str = ""
    # 凭据键名而不是密钥本身, 由 key_resolver 解析
    api_key_ref: str | None = None
    quirks: str = "generic"
    # 覆盖预设里的能力声明, 例如 {"json_schema": false}
    capabilities: dict[str, bool] = Field(default_factory=dict)
    # 采样参数被丢弃时是记日志还是直接报错
    strict_params: bool = False
    max_concurrency: int = 4
    timeout: float = 120.0
    # 连接超时单独一个值, 免得黑洞端点把整个 timeout 耗在握手上
    connect_timeout: float = 10.0
    proxy: str | None = None
    extra_headers: dict[str, str] = Field(default_factory=dict)
    session_header: str | None = None
    extra_body: dict[str, Any] = Field(default_factory=dict)


class LLMSettings(BaseSettings):
    default_alias: str = "chat"
    aliases: dict[str, list[str]] = Field(default_factory=dict)
    endpoints: dict[str, EndpointSettings] = Field(default_factory=dict)
    # 每个别名共用的尝试次数, 含第一次
    max_attempts: int = 2


@dataclass(frozen=True)
class EndpointSpec:
    """构建客户端用的不可变端点描述"""

    id: str
    protocol: Protocol
    base_url: str
    model: str
    # 不参与 repr: 异常 traceback 与 debug 日志都不该带出密钥
    api_key: str | None = field(default=None, repr=False)
    quirks: Quirks = field(default_factory=Quirks)
    strict_params: bool = False
    max_concurrency: int = 4
    timeout: float = 120.0
    connect_timeout: float = 10.0
    proxy: str | None = None
    extra_headers: Mapping[str, str] = field(default_factory=dict)
    session_header: str | None = None
    extra_body: Mapping[str, Any] = field(default_factory=dict)


def _lemony_secret(key: str) -> str | None:
    from lemony_settings.credentials import get_secret

    return get_secret(key)


def build_specs(
    settings: LLMSettings,
    *,
    key_resolver: Callable[[str], str | None] | None = None,
) -> dict[str, EndpointSpec]:
    """把配置模型折成端点描述; 取不到凭据或必填项为空都直接报错"""
    resolver = key_resolver or _lemony_secret
    specs: dict[str, EndpointSpec] = {}
    for name, endpoint in settings.endpoints.items():
        if not endpoint.base_url:
            raise LLMConfigError(f"端点 {name!r} 缺少 base_url")
        if not endpoint.model:
            raise LLMConfigError(f"端点 {name!r} 缺少 model")
        key = None
        if endpoint.api_key_ref:
            key = resolver(endpoint.api_key_ref)
            if not key:
                raise LLMConfigError(
                    f"端点 {name!r} 的凭据 {endpoint.api_key_ref!r} 取不到; "
                    "请写进凭据文件或设置对应的环境变量"
                )
        specs[name] = EndpointSpec(
            id=name,
            protocol=endpoint.protocol,
            base_url=endpoint.base_url,
            model=endpoint.model,
            api_key=key,
            quirks=apply_capabilities(
                resolve_quirks(endpoint.quirks), endpoint.capabilities
            ),
            strict_params=endpoint.strict_params,
            max_concurrency=endpoint.max_concurrency,
            timeout=endpoint.timeout,
            connect_timeout=endpoint.connect_timeout,
            proxy=endpoint.proxy,
            extra_headers=dict(endpoint.extra_headers),
            session_header=endpoint.session_header,
            extra_body=dict(endpoint.extra_body),
        )
    return specs
