"""引用图管线: 取消息 -> 归一化 -> 取资源 -> 渲染 -> 编码。

不依赖 bot 上下文; ``__plugin__`` 负责把事件与适配器翻译成这里的调用。
"""

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from concurrent.futures import Executor
from dataclasses import dataclass, field
from io import BytesIO

from lemony_mface import MFaceBlocklist
from PIL import Image

from .model import QuoteMessage, SourceMessage
from .normalize import name_resolver_from, normalize_message, unresolved_at_targets
from .render.card import card_signature, render_card
from .render.chat import render_chat
from .render.text import FontProvider, extract_emojis
from .resources import ResourceResolver

__all__ = [
    "Assets",
    "MemberNames",
    "NothingToQuote",
    "Rendered",
    "encode",
    "render_card_quote",
    "render_chat_quote",
]


class NothingToQuote(ValueError):
    """消息里没有能画的内容, message 直接面向用户"""


@dataclass(frozen=True, slots=True)
class Assets:
    fonts: FontProvider
    mask: Image.Image
    placeholder: Image.Image


@dataclass(slots=True)
class Rendered:
    image: Image.Image
    messages: tuple[QuoteMessage, ...]
    timings: dict[str, float] = field(default_factory=dict)


MemberNames = Callable[[set[int]], Awaitable[Mapping[int, str]]]
"""按 QQ 号批量查群内显示名 (群名片优先), 用于补全不带名字的 At 段; 查不到的不出现在结果里"""


async def _normalize(
    sources: Sequence[SourceMessage],
    blocklist: MFaceBlocklist,
    member_names: MemberNames | None = None,
) -> tuple[QuoteMessage, ...]:
    extra: Mapping[int, str] = {}
    if member_names is not None and (missing := unresolved_at_targets(sources)):
        extra = await member_names(missing)
    resolve = name_resolver_from(sources, extra)
    return tuple(
        normalize_message(m, blocklist=blocklist, resolve_name=resolve) for m in sources
    )


async def render_card_quote(
    source: SourceMessage,
    *,
    resolver: ResourceResolver,
    assets: Assets,
    executor: Executor,
    member_names: MemberNames | None = None,
) -> Rendered:
    t0 = time.perf_counter()
    (msg,) = await _normalize([source], MFaceBlocklist(), member_names)
    text = msg.text
    if not text:
        raise NothingToQuote("这条消息没有文字, 试试 .mq")
    signature = card_signature(msg.card, msg.nickname, str(msg.sender_id))
    bundle = await resolver.resolve(
        avatars=[msg.sender_id], emojis=extract_emojis([text, signature])
    )
    t1 = time.perf_counter()
    image = await asyncio.get_running_loop().run_in_executor(
        executor,
        lambda: render_card(
            text,
            signature,
            avatar=bundle.avatars.get(msg.sender_id),
            mask=assets.mask,
            emojis=bundle.emojis,
            fonts=assets.fonts,
        ),
    )
    t2 = time.perf_counter()
    return Rendered(image, (msg,), {"fetch": t1 - t0, "draw": t2 - t1})


async def render_chat_quote(
    sources: Sequence[SourceMessage],
    *,
    blocklist: MFaceBlocklist,
    scale: float,
    max_pixels: int,
    resolver: ResourceResolver,
    assets: Assets,
    executor: Executor,
    member_names: MemberNames | None = None,
) -> Rendered:
    t0 = time.perf_counter()
    messages = await _normalize(sources, blocklist, member_names)
    if not messages:
        raise NothingToQuote("区间内没有消息")
    texts = [m.text for m in messages] + [m.display_name for m in messages]
    bundle = await resolver.resolve(
        images=[ref for m in messages for ref in m.images],
        avatars=[m.sender_id for m in messages],
        emojis=extract_emojis(texts),
    )
    t1 = time.perf_counter()
    image = await asyncio.get_running_loop().run_in_executor(
        executor,
        lambda: render_chat(
            messages,
            images=bundle.images,
            avatars=bundle.avatars,
            emojis=bundle.emojis,
            fonts=assets.fonts,
            placeholder=assets.placeholder,
            scale=scale,
            max_pixels=max_pixels,
        ),
    )
    t2 = time.perf_counter()
    return Rendered(image, messages, {"fetch": t1 - t0, "draw": t2 - t1})


_PIL_FORMATS = {
    "jpeg": ("JPEG", "jpg"),
    "png": ("PNG", "png"),
    "webp": ("WEBP", "webp"),
}


def encode(image: Image.Image, fmt: str, quality: int) -> tuple[bytes, str]:
    """编码为 (字节, 扩展名); jpeg 不支持透明, 先铺白底"""
    pil_fmt, ext = _PIL_FORMATS[fmt]
    buf = BytesIO()
    if pil_fmt == "JPEG":
        flat = Image.new("RGB", image.size, (255, 255, 255))
        flat.paste(image, mask=image.getchannel("A") if image.mode == "RGBA" else None)
        flat.save(buf, "JPEG", quality=quality, optimize=True)
    elif pil_fmt == "WEBP":
        image.save(buf, "WEBP", quality=quality)
    else:
        image.save(buf, "PNG")
    return buf.getvalue(), ext
