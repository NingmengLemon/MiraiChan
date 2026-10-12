"""资源获取: 图片、头像、emoji。

渲染前一次性取齐, 全部有超时、并发上限与大小上限; 取不到的资源不算失败,
由渲染层用占位图或字体字形代替。解码在线程里做, 并先缩到渲染所需的尺寸。
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

from aiohttp import ClientSession, ClientTimeout
from lemony_network.qqntmedia_sslcontext import QQNTMEDIA_SSL_CONTEXT
from lemony_network.request import HTTP_HEADERS
from PIL import Image

from .model import ImageRef

__all__ = ["FetchLimits", "ResourceBundle", "ResourceResolver"]

logger = logging.getLogger(__name__)

# 解码前的像素上限, 防止压缩炸弹
_MAX_DECODE_PIXELS = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class FetchLimits:
    timeout: float = 10.0
    max_bytes: int = 20 * 1024 * 1024
    concurrency: int = 4
    # 解码后长边上限; 聊天样式里图片最宽 512*3, 留足余量
    max_image_side: int = 2048


@dataclass(slots=True)
class ResourceBundle:
    images: dict[str, Image.Image] = field(default_factory=dict)
    avatars: dict[int, Image.Image] = field(default_factory=dict)
    emojis: dict[str, Image.Image] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)


AvatarSource = Callable[[int], Awaitable[bytes]]


def _decode(data: bytes, max_side: int) -> Image.Image:
    with Image.open(BytesIO(data)) as img:
        if img.width * img.height > _MAX_DECODE_PIXELS:
            raise ValueError(f"image too large: {img.width}x{img.height}")
        # 动图只取第一帧
        img.seek(0)
        img.draft("RGB", (max_side, max_side))
        out = img.convert("RGBA")
    out.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    return out


class ResourceResolver:
    def __init__(
        self,
        *,
        data_root: Path,
        avatar_source: AvatarSource,
        emoji_cdn: str | None,
        limits: FetchLimits = FetchLimits(),
    ) -> None:
        self._data_root = data_root
        self._avatar_source = avatar_source
        self._emoji_cdn = emoji_cdn.rstrip("/") + "/" if emoji_cdn else None
        self._limits = limits
        self._session: ClientSession | None = None
        self._sem = asyncio.Semaphore(limits.concurrency)
        self._emoji_cache: dict[str, Image.Image] = {}

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    def _http(self) -> ClientSession:
        if self._session is None or self._session.closed:
            self._session = ClientSession(
                timeout=ClientTimeout(total=self._limits.timeout),
                headers=dict(HTTP_HEADERS),
            )
        return self._session

    async def _download(self, url: str) -> bytes:
        async with self._sem:
            # QQ NT 图床要特定的 TLS 设置; 其余地址用 aiohttp 默认校验 (ssl=True)
            ssl = QQNTMEDIA_SSL_CONTEXT if "multimedia.nt.qq.com.cn" in url else True
            async with self._http().get(url, ssl=ssl) as resp:
                resp.raise_for_status()
                if (resp.content_length or 0) > self._limits.max_bytes:
                    raise ValueError(f"too large: {resp.content_length}")
                buf = bytearray()
                async for chunk in resp.content.iter_chunked(64 * 1024):
                    buf.extend(chunk)
                    if len(buf) > self._limits.max_bytes:
                        raise ValueError("too large")
                return bytes(buf)

    def _local_path(self, rel: str) -> Path | None:
        p = Path(rel)
        if not p.is_absolute():
            p = self._data_root / p
        try:
            p = p.resolve()
            p.relative_to(self._data_root.resolve())
        except (OSError, ValueError):
            return None
        return p if p.is_file() else None

    async def _image_bytes(self, ref: ImageRef) -> bytes | None:
        for rel in ref.local_paths:
            if (p := self._local_path(rel)) is not None:
                try:
                    return await asyncio.to_thread(p.read_bytes)
                except OSError:
                    logger.debug("读取本地图片失败: %s", p, exc_info=True)
        if ref.url:
            return await self._download(ref.url)
        return None

    async def _one_image(self, ref: ImageRef, bundle: ResourceBundle) -> None:
        try:
            data = await self._image_bytes(ref)
            if data is None:
                raise LookupError("no source")
            bundle.images[ref.key] = await asyncio.to_thread(
                _decode, data, self._limits.max_image_side
            )
        except (TimeoutError, Exception) as e:
            bundle.missing.append(f"image {ref.key[:80]}: {type(e).__name__}")

    async def _one_avatar(self, uid: int, bundle: ResourceBundle) -> None:
        try:
            async with asyncio.timeout(self._limits.timeout):
                data = await self._avatar_source(uid)
            bundle.avatars[uid] = await asyncio.to_thread(_decode, data, 640)
        except (TimeoutError, Exception) as e:
            bundle.missing.append(f"avatar {uid}: {type(e).__name__}")

    async def _one_emoji(self, em: str, bundle: ResourceBundle) -> None:
        if (cached := self._emoji_cache.get(em)) is not None:
            bundle.emojis[em] = cached
            return
        if self._emoji_cdn is None:
            return
        try:
            data = await self._download(self._emoji_cdn + quote(em, safe=""))
            img = await asyncio.to_thread(_decode, data, 160)
        except (TimeoutError, Exception) as e:
            bundle.missing.append(f"emoji {em}: {type(e).__name__}")
            return
        if len(self._emoji_cache) < 4096:
            self._emoji_cache[em] = img
        bundle.emojis[em] = img

    async def resolve(
        self,
        *,
        images: Iterable[ImageRef] = (),
        avatars: Iterable[int] = (),
        emojis: Iterable[str] = (),
    ) -> ResourceBundle:
        bundle = ResourceBundle()
        refs = {r.key: r for r in images if r.key}
        async with asyncio.TaskGroup() as tg:
            for ref in refs.values():
                tg.create_task(self._one_image(ref, bundle))
            for uid in set(avatars):
                tg.create_task(self._one_avatar(uid, bundle))
            for em in set(emojis):
                tg.create_task(self._one_emoji(em, bundle))
        if bundle.missing:
            logger.info("引用图有 %d 个资源未取到: %s", len(bundle.missing), bundle.missing)
        return bundle
