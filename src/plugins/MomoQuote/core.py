from collections.abc import Iterable
from io import BytesIO
import time
from typing import TypedDict

from PIL import Image, ImageOps, UnidentifiedImageError
from yarl import URL
from pilmoji.source import BaseSource
from melobot.protocols.onebot.v11.adapter.segment import (
    Segment,
    ImageSegment,
    TextSegment,
    AtSegment,
)

from lemony_utils.asyncutils import gather_with_concurrency
from lemony_utils.images import (
    FontCache,
    _ColorT,
    bytes_to_b64_url,
)
from lemony_utils.consts import http_headers
from lemony_utils.templates import async_http
from recorder_models import Message

from .widgets import Avatar, Bubble, _ensure_int
from .params import (
    DrawingParams,
    default_drawing_params,
    QuoteParams,
    default_quote_params,
)


class SupportDot:
    def __init__(self, o: dict):
        self._o = o

    def __getitem__(self, values: str | tuple[str]):
        o = self._o
        for v in [values] if isinstance(values, str) else values:
            o = o[v]
        return o


_FontSource = str | BytesIO


async def retrieve_into_bytesio(url: URL | str):
    async with async_http(url, "get", headers=http_headers) as resp:
        return BytesIO(await resp.read())


def get_avatar_url(uid: int):
    return f"https://q1.qlogo.cn/g?b=qq&nk={uid}&s=640"
    # return f"https://q.qlogo.cn/headimg_dl?dst_uin={uid}&spec=640&img_type=jpg"


class _QuoteMsg(TypedDict):
    sender_id: int
    sender_name: str | None = None
    segments: list[Segment]


class QuoteData(TypedDict):
    group_id: int
    group_name: str | None = None
    quote_time: float
    messages: list[_QuoteMsg]


def prepare_quote(msgs: list[Message]):
    """调用时请保持 msgs 所属的 session 打开"""
    data: QuoteData = {
        "group_id": 0,
        "group_name": None,
        "quote_time": time.time(),
        "messages": [],
    }
    resources = set[URL | str]()
    if not msgs:
        return data, resources
    data["group_id"] = msgs[0].group_id
    data["group_name"] = msgs[0].group.name
    for msg in msgs:
        qmsg: _QuoteMsg = {
            "sender_id": msg.sender_id,
            "sender_name": msg.sender.name,
            "segments": [],
        }
        resources.add(get_avatar_url(msg.sender_id))
        for seg in msg.segments:
            qseg = Segment.resolve(seg.type, seg.data)
            qmsg["segments"].append(qseg)
            if isinstance(qseg, ImageSegment):
                resources.add(qseg.data["url"])
        data["messages"].append(qmsg)
    return data, resources


async def gather_resources(urls: Iterable[URL | str], concurrency=4):
    return {
        k: v
        for k, v in zip(
            urls,
            await gather_with_concurrency(
                *[retrieve_into_bytesio(u) for u in urls],
                concurrency=concurrency,
                return_exceptions=True,
            ),
        )
        if not isinstance(v, Exception)
    }


class QuoteDrawer:
    def __init__(
        self,
        data: QuoteData,
        resources: dict[URL | str, BytesIO],
        font: FontCache,
        quote_params: QuoteParams | None = None,
        drawing_params: DrawingParams | None = None,
        scale: float = 1.0,
    ):
        self._data = data
        self._font = font
        self._resources = resources
        self._qparams = default_quote_params if quote_params is None else quote_params
        self._dparams = (
            default_drawing_params if drawing_params is None else drawing_params
        )
        self._scale = scale
        self._img_missing_img = Image.open("data/no_data.png").convert("RGBA")

        self._widgets: list[list[tuple[tuple[int, int], Avatar | Bubble]]] = []
        # 一个 widget 列表对应一个 msg
        s = self._scale
        x_avatar = self._dparams["margin"]["to_edge"] * s
        y = 0
        x_bubble = (
            x_avatar
            + (self._dparams["avatar_size"] + self._dparams["margin"]["to_edge"]) * s
        )
        max_bubble_width = 0
        last_sender = -1
        for msg in data["messages"]:
            sender = msg["sender_id"]
            if sender == last_sender:
                y += self._dparams["margin"]["between_msgs"] * s
            elif last_sender == -1:
                y += (
                    self._dparams["margin"]["to_edge"] * s
                    + self._dparams["avatar_size"] / 2 * s
                )
            else:
                y += self._dparams["margin"]["between_senders"] * s
            widgets = []
            avatar, bubble = self._msg_to_widgets(msg)
            w, _ = bubble.size
            if w > max_bubble_width:
                max_bubble_width = w
            if sender != last_sender:
                widgets.append(
                    ((x_avatar, y - self._dparams["avatar_size"] / 2 * s), avatar)
                )
            widgets.append(((x_bubble, y), bubble))
            self._widgets.append(widgets)
            y += bubble.size[1]
            last_sender = sender
        self._height = y + self._dparams["margin"]["to_edge"] * s
        self._width = (
            x_bubble
            + (self._dparams["padding"] * 2 + self._dparams["margin"]["to_edge"]) * s
            + max_bubble_width
        )

    def _msg_to_widgets(self, msg: _QuoteMsg):
        avatar_img = self._resources.get(get_avatar_url(msg["sender_id"]))
        avatar = Avatar(
            (
                Image.open(avatar_img).convert("RGBA")
                if avatar_img
                else self._img_missing_img
            ),
            width=self._dparams["avatar_size"],
            scale=self._scale,
        )
        bubble = Bubble(
            self._segs_to_bublems(msg["segments"]),
            font=self._font,
            wrap_width=self._dparams["wrap_width"],
            radius=self._dparams["bubble_corner_radius"],
            font_size=self._dparams["font_size"]["text"],
            padding=self._dparams["padding"],
            spacing=self._dparams["spacing"],
            bg_color=self._dparams["color"]["bubble_bg"],
            text_color=self._dparams["color"]["bubble_text"],
            scale=self._scale,
        )
        return avatar, bubble

    def _segs_to_bublems(self, segs: Iterable[Segment]):
        elements: list[str | Image.Image] = []
        for seg in segs:
            text: str | None = None
            if isinstance(seg, ImageSegment):
                bio = self._resources.get(seg.data["url"])
                try:
                    img = (
                        Image.open(bio).convert("RGBA")
                        if bio
                        else self._img_missing_img
                    )
                except UnidentifiedImageError:
                    img = self._img_missing_img
                elements.append(img)
            elif isinstance(seg, TextSegment):
                text = seg.data["text"]
            elif isinstance(seg, AtSegment):
                text = (
                    "@"
                    + str(seg.raw["data"].get("name") or seg.data["qq"])
                    .removeprefix("@")
                    .strip()
                    + " "
                )
            # TODO: 处理商城表情
            # TODO: 写完处理商城表情之后, 把商城表情过滤列表加上
            if text is not None:
                if elements and isinstance(elements[-1], str):
                    elements[-1] = " ".join([elements[-1], text])
                else:
                    elements.append(text)
        return elements

    @property
    def size(self):
        return (self._width, self._height)

    def draw(
        self,
        canvas: Image.Image,
        emoji_source: BaseSource | type[BaseSource] | None = None,
        bg_color: _ColorT = "#ffffffff",
        show_border=False,
    ):
        last_sender = -1
        for msg, widgets in zip(self._data["messages"], self._widgets):
            sender = msg["sender_id"]
            for coor, widget in widgets:
                # TODO: 增加用户的元数据
                if isinstance(widget, Bubble):
                    widget.draw(
                        canvas,
                        coor,
                        emoji_source=emoji_source,
                        add_triangle=last_sender != sender,
                        show_border=show_border,
                    )
                elif isinstance(widget, Avatar):
                    widget.draw(
                        canvas, coor, bg_color=bg_color, show_border=show_border
                    )
            last_sender = sender
        # TODO: 增加本次Quote的元数据


class QuoteFactory:
    def __init__(
        self,
        font: _FontSource,
        emoji_source: BaseSource | None = None,
    ):
        self._font_cache = font
        self._emoji_source = emoji_source

    def draw(
        self,
        data: QuoteData,
        resources: dict[URL | str, BytesIO],
        drawing_params: DrawingParams | None = None,
        quote_params: QuoteParams | None = None,
        scale: float = 1.0,
        scale_for_antialias: float = 1.0,
        resampling_method: Image.Resampling = Image.Resampling.LANCZOS,
        # TODO: 测试绘图缩放
    ):
        drawer = QuoteDrawer(
            data,
            resources,
            font=self._font_cache,
            quote_params=quote_params,
            drawing_params=drawing_params,
            scale=scale * scale_for_antialias,
        )
        w, h = drawer.size
        canvas = Image.new("RGBA", _ensure_int((w, h)), color="#ffffffff")
        drawer.draw(canvas)
        result = ImageOps.fit(
            canvas,
            _ensure_int((w / scale_for_antialias, h / scale_for_antialias)),
            method=resampling_method,
        )
        return result

    def quote_sync(
        self,
        data: QuoteData,
        resources: dict[URL | str, BytesIO],
    ):
        result = self.draw(data, resources)
        bio = BytesIO()
        result.save(bio, "png")
        return bytes_to_b64_url(bio.getvalue())
