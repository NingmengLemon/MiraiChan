import asyncio
import functools
import os
import time
import traceback

import aiofiles
from melobot.adapter.generic import send_image, send_text
from melobot.ctx import EventOrigin
from melobot.handle import get_event
from melobot.protocols.onebot.v11.adapter import Adapter
from melobot.protocols.onebot.v11.adapter.event import MessageEvent
from melobot.protocols.onebot.v11.adapter.segment import ReplySegment, TextSegment
from melobot.utils import singleton
from melobot.utils.parse.cmd import CmdArgFormatInfo, CmdArgFormatter
from yarl import URL

from .asyncutils import async_retry
from .images import text_to_image
from .templates import async_http, http_headers


@singleton
class _GetReply:
    class GetReplyException(Exception):
        """raise when failed to get reply"""

    class TargetNotSpecifiedError(GetReplyException):
        pass

    class EmptyResponseError(GetReplyException):
        pass

    @classmethod
    async def _get_reply(cls, adapter: Adapter, event: MessageEvent):
        if _ := event.get_segments(ReplySegment):
            msg_id = _[0].data["id"]
        else:
            raise cls.TargetNotSpecifiedError()
        msg = await (await adapter.with_echo(adapter.get_msg)(msg_id))[0]
        if not msg.data:
            raise cls.EmptyResponseError(msg)
        return msg

    def __call__(self, adapter: Adapter, event: MessageEvent):
        return self._get_reply(adapter, event)


get_reply = _GetReply()


def get_mface_package_url(package_id: int):
    return f"https://i.gtimg.cn/club/item/parcel/0/{package_id}_android.json"


def get_mface_url(mface_id: str):
    return f"https://gxh.vip.qq.com/club/item/parcel/item/{mface_id[0:2]}/{mface_id}/raw300.gif"


@singleton
class AvatarCache:
    CACHE_DIR = "data/avatars"
    EXPIRES = 24 * 60 * 60
    FILENAME_TEMPLATE = "{uid}.png"
    URL_TEMPLATE = "https://q1.qlogo.cn/g?b=qq&nk={uid}&s=640"
    HEADERS = http_headers.copy()
    SUPPORTED_URL_HOSTS = ["q.qlogo.cn", "q1.qlogo.cn"]

    def __init__(self):
        os.makedirs(self.CACHE_DIR, exist_ok=True)
        self._update_times: dict[int, float] = {}

    def __getitem__(self, val: int):
        return self.get(val)

    def __call__(self, uid: int):
        return self.get(uid)

    @async_retry()
    async def get_from_remote(self, uid: int):
        url = self.URL_TEMPLATE.format(uid=uid)
        async with async_http(url, "get", headers=self.HEADERS) as resp:
            resp.raise_for_status()
            return await resp.read()

    def get_url(self, uid: int):
        return f"https://q1.qlogo.cn/g?b=qq&nk={uid}&s=640"

    async def get_by_url(self, url: URL | str):
        if not isinstance(url, URL):
            url = URL(url)
        # f"https://q.qlogo.cn/headimg_dl?dst_uin={uid}&spec=640&img_type=jpg"
        # f"https://q1.qlogo.cn/g?b=qq&nk={uid}&s=640"
        if url.host not in self.SUPPORTED_URL_HOSTS:
            return None
        uid = url.query.get("nk") or url.query.get("dst_uin")
        if uid and uid.isdigit():
            return await self.get(int(uid))
        else:
            return None

    async def get(self, uid: int):
        filename = self.FILENAME_TEMPLATE.format(uid=uid)
        path = os.path.join(self.CACHE_DIR, filename)

        if (
            os.path.exists(path)
            and time.time() - self._update_times.get(uid, 0) <= self.EXPIRES
        ):
            async with aiofiles.open(path, "rb") as fp:
                return await fp.read()
        else:
            data = await self.get_from_remote(uid)
            async with aiofiles.open(path, "wb+") as fp:
                await fp.write(data)
            self._update_times[uid] = time.time()
            return data


cached_avatar_source = AvatarCache()


def get_adapter():
    event = get_event()
    return EventOrigin.get_origin(event).adapter


async def _report_by_image(text: str):
    await send_image(
        "Error Report",
        raw=await asyncio.to_thread(text_to_image, text),
        mimetype="image/png",
    )


def auto_report_traceback(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception:
            tbfmt = traceback.format_exc()
            await _report_by_image("///// 出现了错误, 请联系Bot管理员 ///// \n" + tbfmt)
            raise

    return wrapper


def to_ordinal(n: int) -> str:
    if not isinstance(n, int) or n <= 0:
        raise ValueError("positive integer required")

    # 特别处理 11 ~ 13
    if 11 <= (n % 100) <= 13:
        suffix = "th"
    else:
        last_digit = n % 10
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(last_digit, "th")
    return f"{n}{suffix}"


# reference:
# https://github.com/aicorein/meloinf/blob/631f28bc7e75d1b297524d03ed9a69e67c0a4881/src/platform/onebot.py#L72
# 试着用 traceback 的样子写了 (x)
class DefaultCmdFailCallbacks:
    @staticmethod
    async def convert_fail(info: CmdArgFormatInfo) -> None:
        e_class = f"{info.exc.__class__.__module__}.{info.exc.__class__.__qualname__}"
        src = repr(info.src) if isinstance(info.src, str) else info.src

        tip = (
            f"Command <{info.name}>\n"
            + f"    {to_ordinal(info.idx + 1)} argument "
            + (f"({info.src_desc}) " if info.src_desc else "")
            + f"cannot be processed with value {src} given"
            + (f", {info.src_expect} expected." if info.src_expect else ".")
            + f"\n{e_class}: {info.exc}"
        )
        await _report_by_image(tip)

    @staticmethod
    async def validate_fail(info: CmdArgFormatInfo) -> None:
        src = repr(info.src) if isinstance(info.src, str) else info.src

        tip = (
            f"Command <{info.name}>\n"
            + f"    {to_ordinal(info.idx + 1)} argument "
            + (f"({info.src_desc}) " if info.src_desc else "")
            + f"does not meet the requirement with value {src} given"
            + (f", {info.src_expect} expected." if info.src_expect else ".")
        )
        await _report_by_image(tip)

    @staticmethod
    async def arg_lack(info: CmdArgFormatInfo) -> None:
        tip = (
            f"Command <{info.name}>\n"
            + f"    {to_ordinal(info.idx + 1)} argument "
            + (f"({info.src_desc}) " if info.src_desc else "")
            + (f"is missing. {info.src_expect} expected." if info.src_expect else ".")
        )
        await _report_by_image(tip)


PrefilledCmdArgFmtter = functools.partial(
    CmdArgFormatter,
    convert_fail=DefaultCmdFailCallbacks.convert_fail,
    validate_fail=DefaultCmdFailCallbacks.validate_fail,
    arg_lack=DefaultCmdFailCallbacks.arg_lack,
)
