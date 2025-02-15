import asyncio
import functools
from io import BytesIO
from typing import Iterable
import math

from melobot import get_logger
from melobot.protocols.onebot.v11.adapter.echo import _GetMsgEchoDataInterface
from melobot.protocols.onebot.v11.adapter.segment import (
    TextSegment,
    Segment,
    ImageRecvSegment,
    AtSegment,
)

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

_SupportedImgInput = str | BytesIO | Image.Image
_FontSource = str | BytesIO


class QuoteMaker:
    def __init__(
        self,
        font: _FontSource,
        bg_mask: _SupportedImgInput,
        emoji_cdn: str | None = None,
    ):
        self._font_cache = FontCache(font)
        self._emoji_source = (
            SelfHostSource(emoji_cdn) if emoji_cdn else GoogleEmojiSource()
        )
        self._mask = self._standardize(bg_mask)

    async def make(self, msg: _GetMsgEchoDataInterface, use_imgs=False):
        sender = msg["sender"]
        # avatar_url = f"https://q.qlogo.cn/headimg_dl?dst_uin={sender.user_id}&spec=640&img_type=jpg"
        avatar_url = f"https://q1.qlogo.cn/g?b=qq&nk={sender.user_id}&s=640"
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
    def _standardize(image: _SupportedImgInput | None):
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
        urls = [
            str(seg.data["url"]) for seg in segs if isinstance(seg, ImageRecvSegment)
        ]
        get_logger().debug(f"{urls=}")
        return {
            k: v
            for k, v in zip(
                urls,
                map(
                    cls._standardize,
                    await asyncio.gather(
                        *(cls.fetch_image(url, maxsize=maxsize) for url in urls)
                    ),
                ),
            )
            if v
        }

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
        except Exception as e:
            get_logger().warning(e)

    @classmethod
    def _make(
        cls,
        msg: _GetMsgEchoDataInterface,
        mask: Image.Image,
        avatar: Image.Image | None,
        emsource: BaseSource,
        font: FontCache,
        image_dict: dict[str, Image.Image] | None = None,
    ):
        if image_dict is None:
            image_dict = {}
        fg_color = (255, 255, 255, 255)
        bg_color = (19, 19, 19, 255)
        get_logger().debug(f"{image_dict=}")

        sender = msg["sender"]
        msgsegs = msg["message"]
        msgtexts: list[str] = []
        for seg in msgsegs:
            if isinstance(seg, TextSegment):
                msgtexts.append(seg.data["text"])
            elif isinstance(seg, AtSegment):
                msgtexts.append(
                    "@"
                    + str(seg.raw["data"].get("name") or seg.data["qq"])
                    .removeprefix("@")
                    .strip()
                    + " "
                )
        msgtext = " ".join(msgtexts).strip()
        authortext = (
            f"—— {sender.card}\n({sender.nickname})"
            if sender.card
            else f"—— {sender.nickname}"
        )
        # 预先检查防止浪费时间
        if not image_dict and not msgtext:
            # 现在只支持纯文本和纯图片
            return None

        bg = Image.new("RGBA", size=(1920, 1080), color=fg_color)
        # 头像
        if avatar:
            bg.paste(ImageOps.contain(avatar, size=(1080, 1080)), box=(0, 0))
        canvas = Image.alpha_composite(bg, mask)
        draw = ImageDraw.Draw(canvas)
        draw_text = functools.partial(
            draw_multiline_text_auto,
            emoji_source=emsource,
            font=font,
            draw=draw,
        )
        draw_text(
            bbox=(1140, 945, 1850, 1055),
            text=authortext,
            max_font_size=36,
            fill=(128, 128, 128, 255),
        )
        if msgtext:
            get_logger().debug("drawing msg, plaintext")
            draw_text(
                bbox=(1000, 325, 1850, 675),
                text=msgtext,
                max_font_size=72,
                # fill=(255, 255, 255, 255),
                fill=(get_main_color(avatar) if avatar else (255, 255, 255, 255)),
            )
        elif image_dict:
            get_logger().debug("drawing msg, plainimgs")
            imgs = list(image_dict.values())
            pastebox = cls._calc_paste_box((800, 700), [img.size for img in imgs])
            w, h, cw, ch = pastebox
            x, y = 1050, 200
            for i in range(h):
                for j in range(w):
                    index = j + i * h
                    if index > len(imgs) - 1:
                        break
                    resized = ImageOps.contain(imgs[index], size=(cw, ch))
                    canvas.paste(
                        Image.alpha_composite(
                            Image.new("RGBA", size=resized.size, color=bg_color),
                            resized,
                        ),
                        box=(
                            x + j * cw + int((cw - resized.size[0]) / 2),
                            y + i * ch + int((ch - resized.size[1]) / 2),
                        ),
                    )
        fp = BytesIO()
        canvas.save(fp, format="PNG")
        return fp

    @staticmethod
    def _calc_paste_box(box: tuple[int, int], sizes: Iterable[tuple[int, int]]):
        box_w, box_h = box
        n = len(sizes)

        best_w, best_h, min_diff = None, None, float("inf")

        for w in range(1, n + 1):
            h = math.ceil(n / w)
            if w * h >= n:
                aspect_ratio_diff = abs((box_w / box_h) - (w / h))
                if aspect_ratio_diff < min_diff:
                    best_w, best_h, min_diff = w, h, aspect_ratio_diff

        p = box_w // best_w
        q = box_h // best_h

        return best_w, best_h, p, q
