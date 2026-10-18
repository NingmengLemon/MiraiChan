"""配置层: 能力覆盖、凭据解析与严格模式"""

from __future__ import annotations

import pytest
from lemony_llm_provider import (
    CompletionRequest,
    EndpointSpec,
    LLMConfigError,
    LLMSettings,
    Message,
    Pool,
    build_specs,
)
from lemony_llm_provider import (
    CompletionRequest as _Request,
)


def _settings(**endpoint_overrides: object) -> LLMSettings:
    endpoint = {
        "protocol": "chat",
        "base_url": "http://127.0.0.1:1/v1",
        "model": "m",
        "api_key_ref": "llm.test.api_key",
    }
    endpoint.update(endpoint_overrides)
    return LLMSettings(
        default_alias="chat",
        aliases={"chat": ["e1"]},
        endpoints={"e1": endpoint},  # type: ignore[arg-type]
    )


def test_capabilities_override_the_preset() -> None:
    settings = _settings(quirks="deepseek_chat", capabilities={"json_schema": True})
    spec = build_specs(settings, key_resolver=lambda _key: "sk-x")["e1"]
    assert spec.quirks.supports_json_schema is True
    # 没被覆盖的项还是预设里的值
    assert spec.quirks.max_tokens_field == "max_tokens"


def test_unknown_capability_is_rejected() -> None:
    settings = _settings(capabilities={"nope": True})
    with pytest.raises(ValueError, match="未知能力"):
        build_specs(settings, key_resolver=lambda _key: "sk-x")


def test_missing_credential_fails_loudly() -> None:
    settings = _settings()
    with pytest.raises(LLMConfigError, match="凭据"):
        build_specs(settings, key_resolver=lambda _key: None)


@pytest.mark.asyncio
async def test_strict_params_refuses_to_drop_sampling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 端点的 quirks 声明不支持 temperature, 严格模式下应当报错而不是静默丢弃
    spec = EndpointSpec(
        id="e1",
        protocol="chat",
        base_url="http://127.0.0.1:1/v1",
        model="m",
        api_key="sk-x",
        quirks=build_specs(
            _settings(quirks="generic", capabilities={"temperature": False}),
            key_resolver=lambda _key: "sk-x",
        )["e1"].quirks,
        strict_params=True,
    )
    pool = Pool([spec], {})
    request: _Request = CompletionRequest(
        messages=(Message.user("hi"),), temperature=0.3
    )
    try:
        with pytest.raises(LLMConfigError, match="temperature"):
            await pool.complete(request)
    finally:
        await pool.aclose()
