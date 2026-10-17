"""内容核验的响应解析与 HTTP 调用 (不联网)。"""

import json
from typing import Any, cast

import aiohttp
import pytest
from mbplugin_provenance.client import (
    ProvenanceError,
    ProvenanceResult,
    check_image,
    parse_results,
)

RESPONSE = {
    "object": "content_provenance_check",
    "created_at": 1792241358,
    "results": [
        {
            "type": "c2pa",
            "outcome": "detected",
            "validation_state": "trusted",
            "issuer": "OpenAI OpCo, LLC",
            "model": "gpt-image-1",
            "generated_at": "2026-07-27T18:34:12Z",
        },
        {
            "type": "synthid",
            "outcome": "not_detected",
            "model": None,
            "generated_at": None,
        },
    ],
}


class _Response:
    def __init__(self, status: int, body: str, headers: dict[str, str] | None = None):
        self.status = status
        self._body = body
        self.headers = headers or {}

    async def text(self) -> str:
        return self._body

    async def __aenter__(self) -> "_Response":
        return self

    async def __aexit__(self, *_: object) -> bool:
        return False


class _Session:
    """记录调用参数的假 session"""

    def __init__(self, response: _Response) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> _Response:
        self.calls.append({"url": url, **kwargs})
        return self.response


def _as_session(fake: _Session) -> aiohttp.ClientSession:
    return cast(aiohttp.ClientSession, fake)


@pytest.mark.asyncio
async def test_check_image_sends_one_multipart_file() -> None:
    fake = _Session(_Response(200, json.dumps(RESPONSE)))
    result = await check_image(
        _as_session(fake),
        b"\x89PNG\r\n\x1a\nfake",
        mime="image/png",
        api_key="sk-test",
        base_url="https://example.test/v1/",
    )

    call = fake.calls[0]
    assert call["url"] == "https://example.test/v1/content_provenance_checks"
    assert call["headers"]["Authorization"] == "Bearer sk-test"
    form = call["data"]
    assert isinstance(form, aiohttp.FormData)
    field, headers, body = form._fields[0]
    assert field["name"] == "file"
    assert field["filename"] == "image"
    assert body == b"\x89PNG\r\n\x1a\nfake"
    assert headers["Content-Type"] == "image/png"
    # 只解析结果, 不关心 object/created_at
    assert [(r.type, r.outcome) for r in result] == [
        ("c2pa", "detected"),
        ("synthid", "not_detected"),
    ]


@pytest.mark.asyncio
async def test_check_image_maps_failures_to_readable_errors() -> None:
    for status, headers, needle in (
        (429, {"Retry-After": "7"}, "限流"),
        (401, {}, "凭据"),
        (500, {}, "500"),
    ):
        fake = _Session(_Response(status, "{}", headers))
        with pytest.raises(ProvenanceError, match=needle):
            await check_image(_as_session(fake), b"x", mime="image/png", api_key="k")


@pytest.mark.asyncio
async def test_check_image_rejects_empty_or_invalid_bodies() -> None:
    with pytest.raises(ProvenanceError, match="空响应"):
        await check_image(
            _as_session(_Session(_Response(200, "   "))),
            b"x",
            mime="image/png",
            api_key="k",
        )
    with pytest.raises(ProvenanceError, match="JSON"):
        await check_image(
            _as_session(_Session(_Response(200, "not json"))),
            b"x",
            mime="image/png",
            api_key="k",
        )


def test_parse_results_keeps_optional_fields() -> None:
    c2pa, synthid = parse_results(RESPONSE)
    assert c2pa.issuer == "OpenAI OpCo, LLC"
    assert c2pa.model == "gpt-image-1"
    assert c2pa.validation_state == "trusted"
    assert c2pa.generated_at == "2026-07-27T18:34:12Z"
    assert c2pa.detected
    assert synthid.model is None and synthid.issuer is None
    assert not synthid.detected


def test_parse_results_rejects_broken_shapes() -> None:
    with pytest.raises(ProvenanceError, match="results"):
        parse_results({})
    with pytest.raises(ProvenanceError, match="results"):
        parse_results({"results": "nope"})
    with pytest.raises(ProvenanceError, match="type"):
        parse_results({"results": [{"outcome": "detected"}]})


def test_detected_flag() -> None:
    assert ProvenanceResult("c2pa", "detected").detected
    assert not ProvenanceResult("c2pa", "not_detected").detected
