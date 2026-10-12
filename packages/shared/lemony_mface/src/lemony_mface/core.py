import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

MFACE_HOST = "gxh.vip.qq.com"
_ITEM_PATH_RE = re.compile(
    r"^/club/item/parcel/item/(?P<dir>[0-9a-fA-F]{2})/(?P<id>[0-9a-fA-F]{32})/"
)
_EMOJI_ID_RE = re.compile(r"^[0-9a-fA-F]{32}$")


@dataclass(frozen=True, slots=True)
class MFace:
    emoji_id: str
    """32 位 hex, 小写"""
    package_id: int | None
    """表情包 id, 未知时为 None (例如只从 url 认出来的)"""
    summary: str | None
    """替代文本, 形如 ``[喵喵消息]``"""
    key: str | None
    url: str
    """原图地址; 上报里有就用上报的, 否则按 emoji_id 拼"""


def mface_image_url(emoji_id: str, *, size: int = 300) -> str:
    emoji_id = emoji_id.lower()
    return (
        f"https://{MFACE_HOST}/club/item/parcel/item/"
        f"{emoji_id[:2]}/{emoji_id}/raw{size}.gif"
    )


def mface_package_url(package_id: int) -> str:
    """表情包元数据 (json)"""
    return f"https://i.gtimg.cn/club/item/parcel/0/{package_id}_android.json"


def _emoji_id_from_url(url: str) -> str | None:
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.hostname != MFACE_HOST:
        return None
    m = _ITEM_PATH_RE.match(parts.path)
    if m is None or m["dir"].lower() != m["id"][:2].lower():
        return None
    return m["id"].lower()


def _opt_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("+-").isdigit():
        return int(value)
    return None


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def parse_mface(seg_type: str, data: Mapping[str, Any]) -> MFace | None:
    """从 OneBot 段 (类型 + data) 识别商城表情, 不是则返回 None"""
    if seg_type not in ("mface", "image"):
        return None
    raw_url = _opt_str(data.get("url"))
    emoji_id = _opt_str(data.get("emoji_id"))
    if emoji_id is not None:
        emoji_id = emoji_id.strip().lower()
        if not _EMOJI_ID_RE.match(emoji_id):
            emoji_id = None
    if emoji_id is None and raw_url is not None:
        emoji_id = _emoji_id_from_url(raw_url)
    if emoji_id is None:
        return None
    package_id = _opt_int(data.get("emoji_package_id", data.get("tab_id")))
    if package_id == 0:
        package_id = None
    return MFace(
        emoji_id=emoji_id,
        package_id=package_id,
        summary=_opt_str(data.get("summary")),
        key=_opt_str(data.get("key")),
        url=raw_url or mface_image_url(emoji_id),
    )


def is_summary_echo(mface: MFace, seg_type: str, data: Mapping[str, Any]) -> bool:
    """QQ 客户端发送商城表情时会附带一条与 summary 相同的文本段, 渲染时应当去掉"""
    if seg_type != "text" or not mface.summary:
        return False
    return str(data.get("text", "")).strip() == mface.summary.strip()


class MFaceBlocklist:
    """按表情包 id 屏蔽。包 id 未知的表情不会被屏蔽"""

    __slots__ = ("_packages",)

    def __init__(self, package_ids: Iterable[int] = ()) -> None:
        self._packages = frozenset(int(p) for p in package_ids)

    def __contains__(self, mface: object) -> bool:
        return (
            isinstance(mface, MFace)
            and mface.package_id is not None
            and mface.package_id in self._packages
        )

    def __len__(self) -> int:
        return len(self._packages)

    @property
    def package_ids(self) -> frozenset[int]:
        return self._packages
