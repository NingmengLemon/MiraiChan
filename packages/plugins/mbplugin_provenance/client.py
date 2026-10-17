"""内容来源核验插件的 HTTP 客户端与响应解析。

接口是 OpenAI 的 ``POST /v1/content_provenance_checks``: multipart 里放一个 ``file``
字段, 设置它的 media type; 图片返回 ``c2pa`` 与 ``synthid`` 两项结果, 音频只有
``synthid``。这里只做请求与解析, 不知道消息、权限和回复格式。
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import aiohttp

__all__ = [
    "ProvenanceError",
    "ProvenanceResult",
    "check_image",
    "parse_results",
]


@dataclass(frozen=True, slots=True)
class ProvenanceResult:
    """一条检测结果; 不同 type 的字段不完全一样, 没有的字段是 None"""

    type: str
    outcome: str
    model: str | None = None
    issuer: str | None = None
    validation_state: str | None = None
    generated_at: str | None = None

    @property
    def detected(self) -> bool:
        return self.outcome == "detected"


class ProvenanceError(RuntimeError):
    """调用失败; 消息可以直接回给用户"""


def parse_results(payload: Mapping[str, Any]) -> tuple[ProvenanceResult, ...]:
    """把接口响应里的 results 转成 tuple; 结构不对时抛 :class:`ProvenanceError`"""
    raw_results = payload.get("results")
    if not isinstance(raw_results, list):
        raise ProvenanceError("接口返回里没有 results")
    results: list[ProvenanceResult] = []
    for item in raw_results:
        if not isinstance(item, Mapping):
            raise ProvenanceError("接口返回的 results 结构不对")
        result_type = str(item.get("type") or "")
        outcome = str(item.get("outcome") or "")
        if not result_type or not outcome:
            raise ProvenanceError("接口返回的 results 缺少 type 或 outcome")
        results.append(
            ProvenanceResult(
                type=result_type,
                outcome=outcome,
                model=_optional_str(item.get("model")),
                issuer=_optional_str(item.get("issuer")),
                validation_state=_optional_str(item.get("validation_state")),
                generated_at=_optional_str(item.get("generated_at")),
            )
        )
    return tuple(results)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


async def check_image(
    session: aiohttp.ClientSession,
    data: bytes,
    *,
    mime: str,
    api_key: str,
    base_url: str = "https://api.openai.com/v1",
    total_timeout: float = 30.0,
    proxy: str | None = None,
) -> tuple[ProvenanceResult, ...]:
    """发送一张图片并返回检测结果; 失败时抛 :class:`ProvenanceError`"""
    url = base_url.rstrip("/") + "/content_provenance_checks"
    form = aiohttp.FormData()
    form.add_field("file", data, filename="image", content_type=mime)
    try:
        async with session.post(
            url,
            data=form,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=aiohttp.ClientTimeout(total=total_timeout),
            proxy=proxy,
        ) as response:
            body = await response.text()
            if response.status == 429:
                retry_after = response.headers.get("Retry-After")
                hint = f", {retry_after} 秒后重试" if retry_after else ""
                raise ProvenanceError(f"接口限流了{hint}")
            if response.status in (401, 403):
                raise ProvenanceError(
                    "凭据被拒绝了, 请联系管理员检查 provenance.api_key"
                )
            if response.status != 200:
                raise ProvenanceError(f"接口返回了 {response.status}")
            if not body.strip():
                raise ProvenanceError("接口返回了空响应")
            try:
                payload = json.loads(body)
            except ValueError as exc:
                raise ProvenanceError("接口返回的不是合法 JSON") from exc
            if not isinstance(payload, Mapping):
                raise ProvenanceError("接口返回的结构不对")
            return parse_results(payload)
    except aiohttp.ClientError as exc:
        raise ProvenanceError(f"调用接口失败: {type(exc).__name__}") from exc
    except TimeoutError as exc:
        raise ProvenanceError("调用接口超时了") from exc
