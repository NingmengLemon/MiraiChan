import asyncio
import functools
from io import BytesIO
from typing import Iterable

from melobot.protocols.onebot.v11.adapter.echo import _GetMsgEchoDataInterface
from melobot.protocols.onebot.v11.adapter.segment import TextSegment, Segment

from PIL import Image, ImageOps, ImageDraw
from pilmoji.source import GoogleEmojiSource, BaseSource

from lemony_utils.images import (
    FontCache,
    SelfHostSource,
    draw_multiline_text_auto,
    get_main_color,
)
from lemony_utils.consts import http_headers
from lemony_utils.templates import async_http

_ApplyGraSupports = str | BytesIO | Image.Image
_FontSource = str | BytesIO


class QuoteMaker:
    def __init__(
        self,
        font: _FontSource,
        bg_mask: _ApplyGraSupports,
        emoji_cdn: str | None = None,
    ):
        self._font_cache = FontCache(font)
        self._emoji_source = (
            SelfHostSource(emoji_cdn) if emoji_cdn else GoogleEmojiSource()
        )
        self._mask = self._standardize(bg_mask)

    async def make(self, msg: _GetMsgEchoDataInterface, use_imgs=False):
        sender = msg["sender"]

        avatar_url = f"https://q.qlogo.cn/headimg_dl?dst_uin={sender.user_id}&spec=640&img_type=jpg"
        avatar = await self.fetch_image(avatar_url)
        image_dict = (await self._fetch_all_imgs(msg["message"])) if use_imgs else None
        return await asyncio.to_thread(
            self._make,
            msg=msg,
            mask=self._mask,
            avatar=self._standardize(avatar),
            emsource=self._emoji_source,
            font=self._font_cache,
            image_dict=image_dict,
        )

    @staticmethod
    def _standardize(image: _ApplyGraSupports | None):
        if image is None:
            return None
        if isinstance(image, (str, BytesIO)):
            img = Image.open(image).convert("RGBA")
        elif isinstance(image, Image.Image):
            img = image.convert("RGBA")
        else:
            raise ValueError(
                "Invalid image input. Provide a file path or a PIL image object."
            )
        return img

    @classmethod
    async def _fetch_all_imgs(cls, segs: Iterable[Segment], maxsize=-1):
        pass

    @staticmethod
    async def fetch_image(url: str, maxsize=-1):
        try:
            async with async_http(url, "get", headers=http_headers) as resp:
                resp.raise_for_status()
                if (
                    maxsize != -1
                    and int(resp.headers.get("Content-Length", "0")) > maxsize
                ):
                    return None
                return BytesIO(await resp.content.read())
        except Exception:
            pass

    @staticmethod
    def _make(
        msg: _GetMsgEchoDataInterface,
        mask: Image.Image,
        avatar: Image.Image | None,
        emsource: BaseSource,
        font: FontCache,
        image_dict: dict[str, bytes] | None = None,
    ):
        if image_dict is None:
            image_dict = {}
        bg_color = (255, 255, 255, 255)
        canvas = Image.new("RGBA", size=(1920, 1080), color=bg_color)
        if avatar:
            canvas.paste(ImageOps.contain(avatar, size=(1080, 1080)), box=(0, 0))
        result = Image.alpha_composite(canvas, mask)
        # draw = ImageDraw.Draw(result)

        sender = msg["sender"]
        msgsegs = msg["message"]
        msgtexts = [seg.data["text"] for seg in msgsegs if isinstance(seg, TextSegment)]
        msgtext = "\n".join(msgtexts)
        authortext = (
            f"—— {sender.card}\n({sender.nickname})"
            if sender.card
            else f"—— {sender.nickname}"
        )
        draw = ImageDraw.Draw(result)
        draw_text = functools.partial(
            draw_multiline_text_auto,
            emoji_source=emsource,
            font=font,
            draw=draw,
        )
        draw_text(
            bbox=(1000, 325, 1850, 675),
            text=msgtext,
            max_font_size=72,
            # fill=(255, 255, 255, 255),
            fill=(get_main_color(avatar) if avatar else (255, 255, 255, 255)),
        )
        draw_text(
            bbox=(1140, 945, 1850, 1055),
            text=authortext,
            max_font_size=36,
            fill=(128, 128, 128, 255),
        )
        fp = BytesIO()
        result.save(fp, format="PNG")
        return fp
