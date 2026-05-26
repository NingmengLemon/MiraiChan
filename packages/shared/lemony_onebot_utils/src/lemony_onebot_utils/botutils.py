import asyncio
import functools
import os
import time
import traceback
from collections.abc import Awaitable

import aiofiles
from aiohttp import ClientSession
from lemony_images import bytes_to_b64_url, text_to_image
from lemony_network.request import async_http, http_headers
from lemony_utils.misc import to_ordinal
from melobot import get_bot
from melobot.adapter.base import Adapter as BaseAdapter
from melobot.adapter.generic import send_image
from melobot.bot.base import Bot
from melobot.ctx import EventOrigin
from melobot.handle import get_event
from melobot.protocols.onebot.v11 import GetMsgEcho
from melobot.protocols.onebot.v11.adapter import Adapter
from melobot.protocols.onebot.v11.adapter.event import MessageEvent
from melobot.protocols.onebot.v11.adapter.segment import ImageSegment, ReplySegment
from melobot.utils import singleton
from melobot.utils.parse.cmd import CmdArgFormatInfo, CmdArgFormatter
from tenacity import retry, stop_after_attempt, wait_exponential
from yarl import URL


async def text_to_imgseg(text: str, /, **kwargs):
    return ImageSegment(
        file=await asyncio.to_thread(
            lambda: bytes_to_b64_url(text_to_image(text, **kwargs)),
        )
    )


async def get_reply(adapter: Adapter, event: MessageEvent) -> None | GetMsgEcho:
    if _ := event.get_segments(ReplySegment):
        msg_id = _[0].data["id"]
    else:
        return None
    msg = (await (await adapter.get_msg(msg_id)))[0]
    if msg is None:
        return None
    return msg


def get_mface_package_url(package_id: int):
    return f"https://i.gtimg.cn/club/item/parcel/0/{package_id}_android.json"


def get_mface_url(mface_id: str):
    return f"https://gxh.vip.qq.com/club/item/parcel/item/{mface_id[0:2]}/{mface_id}/raw300.gif"


def uid_to_avatar_url(uid: int) -> str:
    # return f"https://q1.qlogo.cn/g?b=qq&nk={uid}&s=640"
    return f"https://q.qlogo.cn/headimg_dl?dst_uin={uid}&spec=640&img_type=png"


def avatar_url_to_uid(url: str | URL) -> int | None:
    if isinstance(url, str):
        url = URL(url)
    if url.host not in ["q.qlogo.cn", "q1.qlogo.cn"]:
        return None
    uid = url.query.get("nk") or url.query.get("dst_uin")
    if uid and uid.isdigit():
        return int(uid)
    else:
        return None


@singleton
class AvatarCache:
    CACHE_DIR = "data/avatars"  # TODO: 从统一的资源管理器里拿, 别直接读相对路径, cwd 不一定是项目根
    EXPIRES = 24 * 60 * 60
    FILENAME_TEMPLATE = "{uid}.png"
    HEADERS = http_headers.copy()

    def __init__(self, *, auto_close: bool = True):
        # auto_close 依赖 bot 的 stopped 事件关闭 session
        # TODO: 那我问你这个单例怎么传参数
        os.makedirs(self.CACHE_DIR, exist_ok=True)
        # TODO: use mtime instead of a separate dict to track update times
        self._update_times: dict[int, float] = {}
        self._session: ClientSession | None = None
        self._auto_close = auto_close
        self._bot: Bot | None = None

    def __getitem__(self, val: int) -> Awaitable[bytes]:
        return self.get(val)

    def __call__(self, uid: int) -> Awaitable[bytes]:
        return self.get(uid)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
    )
    async def get_from_remote(self, uid: int):
        if self._session is None:
            self._session = ClientSession()
        url = uid_to_avatar_url(uid)
        async with async_http(self._session, "get", url, headers=self.HEADERS) as resp:
            resp.raise_for_status()
            return await resp.read()

    def get_url(self, uid: int):
        return uid_to_avatar_url(uid)

    async def get_by_url(self, url: URL | str):
        uid = avatar_url_to_uid(url)
        if uid is not None:
            return await self.get(int(uid))
        return None

    async def get(self, uid: int):
        if not self._bot and self._auto_close:
            self._bot = get_bot()
            self._bot.on_stopped(self.close)
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

    async def close(self):
        if self._session:
            await self._session.close()
            self._session = None


cached_avatar_source = AvatarCache()


def get_adapter() -> BaseAdapter:
    event = get_event()
    return EventOrigin.get_origin(event).adapter


async def _report_by_image(text: str) -> None:
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
