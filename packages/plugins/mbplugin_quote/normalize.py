"""OneBot 段 -> 渲染元素 (纯函数)。"""

from collections.abc import Callable, Sequence

from lemony_mface import MFaceBlocklist, is_summary_echo, parse_mface

from .model import (
    Element,
    ImageElement,
    ImageRef,
    QuoteMessage,
    SourceMessage,
    SourceSegment,
    TextElement,
)

__all__ = ["display_name_of", "normalize_message"]

# 不画出来的段: 回复引用本身对引用图没有意义
_DROPPED = frozenset({"reply"})
_LABELS = {
    "face": "[表情]",
    "record": "[语音]",
    "video": "[视频]",
    "file": "[文件]",
    "forward": "[聊天记录]",
    "json": "[卡片消息]",
    "xml": "[卡片消息]",
    "poke": "[戳一戳]",
    "dice": "[骰子]",
    "rps": "[猜拳]",
    "location": "[位置]",
    "music": "[音乐]",
    "share": "[链接]",
    "markdown": "[消息]",
}

NameResolver = Callable[[int], str | None]
"""At 段没带名字时, 按 QQ 号查名字 (例如从同一批消息的发送者里找)"""


def display_name_of(card: str | None, nickname: str | None, uid: int) -> str:
    return (card or "").strip() or (nickname or "").strip() or str(uid)


def _at_text(seg: SourceSegment, resolve: NameResolver | None) -> str:
    qq = str(seg.data.get("qq", "")).strip()
    if qq == "all":
        return "@全体成员"
    name = str(seg.data.get("name") or "").removeprefix("@").strip()
    if not name and resolve is not None and qq.isdigit():
        name = resolve(int(qq)) or ""
    return f"@{name or qq}"


def _append_text(out: list[Element], text: str) -> None:
    if not text:
        return
    if out and isinstance(out[-1], TextElement):
        out[-1] = TextElement(out[-1].text + text)
    else:
        out.append(TextElement(text))


def normalize_segments(
    segments: Sequence[SourceSegment],
    *,
    blocklist: MFaceBlocklist,
    resolve_name: NameResolver | None = None,
) -> tuple[Element, ...]:
    out: list[Element] = []
    pending_echo = None
    for seg in segments:
        if pending_echo is not None:
            echo, pending_echo = pending_echo, None
            if is_summary_echo(echo, seg.type, seg.data):
                continue
        if seg.type in _DROPPED:
            continue
        if seg.type == "text":
            _append_text(out, str(seg.data.get("text", "")))
            continue
        if seg.type == "at":
            _append_text(out, _at_text(seg, resolve_name) + " ")
            continue
        if mface := parse_mface(seg.type, seg.data):
            pending_echo = mface
            if mface in blocklist:
                _append_text(out, mface.summary or "[表情]")
            else:
                out.append(
                    ImageElement(
                        ImageRef(
                            url=mface.url, local_paths=seg.local_paths, is_mface=True
                        )
                    )
                )
            continue
        if seg.type == "image":
            url = seg.data.get("url")
            out.append(
                ImageElement(
                    ImageRef(url=str(url) if url else None, local_paths=seg.local_paths)
                )
            )
            continue
        _append_text(out, _LABELS.get(seg.type, f"[{seg.type}]"))
    # 文本块与图片分开排版, 每个文本块首尾的空白都不画
    result: list[Element] = []
    for e in out:
        if isinstance(e, TextElement):
            if text := e.text.strip():
                result.append(TextElement(text))
        else:
            result.append(e)
    return tuple(result)


def normalize_message(
    msg: SourceMessage,
    *,
    blocklist: MFaceBlocklist,
    resolve_name: NameResolver | None = None,
) -> QuoteMessage:
    return QuoteMessage(
        message_id=msg.message_id,
        sender_id=msg.sender_id,
        display_name=display_name_of(
            msg.sender_card, msg.sender_nickname, msg.sender_id
        ),
        nickname=msg.sender_nickname,
        card=msg.sender_card,
        elements=normalize_segments(
            msg.segments, blocklist=blocklist, resolve_name=resolve_name
        ),
    )


def name_resolver_from(messages: Sequence[SourceMessage]) -> NameResolver:
    """用同一批消息里出现过的发送者名字解析 At"""
    names: dict[int, str] = {}
    for m in messages:
        names.setdefault(
            m.sender_id, display_name_of(m.sender_card, m.sender_nickname, m.sender_id)
        )
    return names.get
