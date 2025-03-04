import asyncio
from collections.abc import Callable, Iterable
from dataclasses import dataclass
import functools
from io import BytesIO
import re
import os
import time
import traceback
from typing import Annotated, Concatenate

import aiofiles
from melobot import send_text, get_logger
from melobot.adapter.generic import _get_ctx_adapter
from melobot.plugin import PluginPlanner
from melobot.protocols.onebot.v11.adapter.event import GroupMessageEvent, MessageEvent
from melobot.protocols.onebot.v11.adapter.segment import (
    ImageSegment,
    TextSegment,
    ReplySegment,
)
from melobot.protocols.onebot.v11.adapter import Adapter
from melobot.handle import on_command
from melobot.di import Reflect
from melobot.utils import singleton, unfold_ctx, get_id
from melobot.session import Rule, enter_session, suspend

from sqlmodel import select, col
from sqlmodel import Session as SqlmSession
from pydantic import BaseModel
from yarl import URL

from configloader import ConfigLoader, ConfigLoaderMetadata
import checker_factory
from recorder_models import Message
from lemony_utils.botutils import get_reply
from lemony_utils.images import (
    SelfHostSource,
    text_to_imgseg,
    bytes_to_b64_url,
    FontCache,
)
import little_helper

from .core import (
    QuoteFactory,
    prepare_quote,
    gather_resources,
)
from .. import Recorder


logger = get_logger()

little_helper.register(
    "MomoQuote",
    {
        "cmd": r".mq [[\d, \d]] [sender_?only] [\dx] [a\dx]",
        "text": "回复一条消息, 以其为基准进行范围引用. "
        "\n使用闭区间表示相对引用范围. "
        "\n添加 'sender_only' flag 将引用消息限制为仅基准消息发送者发送. "
        "\n添加 \\dx 调整输出尺寸, 添加 a\\dx 调整用于抗锯齿的尺寸",
    },
)


class QuoteConfig(BaseModel):
    emoji_cdn: str | None = None
    font: str = "data/fonts/NotoSansSC-Medium.ttf"
    placeholder_img: str = "data/no_data.png"
    saveto: str | None = "data/record/quotes"
    allow_image: bool = True
    banned_stickersets: list[int] = [
        231182,
        231412,
        231764,
        239439,
        239546,
        239871,
    ]
    same_msg_min_dist: int = 60 * 10
    region_limit: tuple[int, int] = (-25, 25)
    scale_limit: float = 5.0


cfgloader = ConfigLoader(
    ConfigLoaderMetadata(model=QuoteConfig, filename="momoquote_conf.json")
)
cfgloader.load_config()
quote_factory = QuoteFactory(
    font=FontCache(cfgloader.config.font),
    emoji_source=(
        SelfHostSource(cfgloader.config.emoji_cdn)
        if cfgloader.config.emoji_cdn
        else None
    ),
    placeholder_img=cfgloader.config.placeholder_img,
)


def to_thread_deco[**P, T](func: Callable[P, T]):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        return await asyncio.to_thread(func, *args, **kwargs)

    return wrapper


def auto_report_traceback(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception:
            adapter = _get_ctx_adapter()
            if isinstance(adapter, Adapter):
                await adapter.send(
                    [
                        TextSegment("出现了错误: \n"),
                        await text_to_imgseg(traceback.format_exc()),
                    ]
                )
            else:
                await send_text("出现了错误: \n" + traceback.format_exc())
            raise

    return wrapper


@singleton
class _GetReplyIdWithCache:
    reply_relation_cache: dict[int, int] = {}

    @classmethod
    def _get_reply_id(cls, event: MessageEvent) -> int:
        if event.message_id in cls.reply_relation_cache:
            return cls.reply_relation_cache[event.message_id]
        if _ := event.get_segments(ReplySegment):
            msg_id = _[0].data["id"]
        else:
            raise get_reply.TargetNotSpecifiedError()
        cls.reply_relation_cache[event.message_id] = msg_id
        return msg_id

    def __call__(self, event: MessageEvent):
        return self._get_reply_id(event)


get_reply_msg_id = _GetReplyIdWithCache()


@dataclass(frozen=True)
class MsgFromDB:
    msg_id: int
    sender_id: int
    sender_name: str


async def get_reply_from_db(event: GroupMessageEvent):
    msg_id = get_reply_msg_id(event)
    async with Recorder.get_session() as sess:
        msg = (
            await sess.exec(
                select(Message)
                .where(Message.message_id == msg_id, Message.group_id == event.group_id)
                .order_by(col(Message.timestamp).desc())
            )
        ).first()
        if msg:
            result = MsgFromDB(
                msg_id=msg_id,
                sender_id=msg.sender_id,
                sender_name=(await msg.awaitable_attrs.sender).name,
            )
            logger.debug(f"Got reply record form db: {result!r}")
            return result


plugin = PluginPlanner("0.1.0")


def extract_params(event: GroupMessageEvent):
    params = event.text
    if _ := re.search(r"\[\s*(\-?\d+)\s*\,\s*(\-?\d+)\s*\]", params, re.IGNORECASE):
        left, right = map(int, _.group(1, 2))
        params = params.replace(_.group(), "")
    else:
        left = right = 0
    sender_only = bool(re.search(r"sender[\s_\-]only", params, re.IGNORECASE))
    if _ := re.search(r"\s+(\d+(?:\.\d+)?)x\b", params):
        scale = _.group(1)
    else:
        scale = 1.0
    if _ := re.search(r"\s*a(\d+(?:\.\d+)?)x\b", params):
        ascale = _.group(1)
    else:
        ascale = 1.0
    return (min(left, right), max(left, right)), (
        sender_only,
        float(scale),
        float(ascale),
    )


class SameReplyRule(Rule[GroupMessageEvent]):
    async def compare(self, e1, e2):
        try:
            r1, r2 = get_reply_msg_id(e1), get_reply_msg_id(e2)
        except get_reply.GetReplyException:
            return False
        (re1, p1), (re2, p2) = extract_params(e1), extract_params(e2)
        return (r1, *re1, *p1) == (r2, *re2, *p2)


rule = SameReplyRule()


def just_prepare_quote_data_decorator(banned_sticker_sets: Iterable[int]):
    def decorator[**P](func: Callable[Concatenate[SqlmSession, P], list[Message]]):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return prepare_quote(func(*args, **kwargs), banned_sticker_sets)

        return wrapper

    return decorator


just_prepare = just_prepare_quote_data_decorator(cfgloader.config.banned_stickersets)(
    Recorder.get_context_messages
)

do_quote = to_thread_deco(quote_factory.quote_sync)
b2b64url_async = to_thread_deco(bytes_to_b64_url)


async def gather_resources_from_recorder(resources: set[str | URL]):
    paths = {
        r: await Recorder.get_filepath(Recorder.url_to_fileid(URL(r)))
        for r in resources
    }
    result: dict[str | URL, BytesIO] = {}
    for url, path in paths.items():
        if path and os.path.isfile(path):
            async with aiofiles.open(path, "rb") as fp:
                result[url] = BytesIO(await fp.read())
    notfounds = resources - set(result.keys())
    return result, notfounds


def reset_to_zero_left(left: int, right: int, base_msg: int, msgseq: list[int]):
    if base_msg not in msgseq:
        return left, right, base_msg
    base_i = msgseq.index(base_msg)
    return left + base_i, right + base_i, msgseq[0]


@plugin.use
@on_command(
    ".",
    " ",
    ["mq", "momoquote"],
    decos=[
        auto_report_traceback,
        unfold_ctx(
            lambda: enter_session(
                rule, wait=False, nowait_cb=lambda: send_text("MomoQuote 正忙, 请稍等")
            )
        ),
    ],
    # checker=checker_factory.get_owner_checker(),
)
async def quote(
    adapter: Annotated[Adapter, Reflect()],
    event: Annotated[GroupMessageEvent, Reflect()],
):
    # 拿到消息id
    if not Recorder.ready_event.is_set():
        await adapter.send_reply("数据库还未就绪")
        return
    try:
        target = await get_reply_from_db(event)
        if not target:
            echo = await get_reply(adapter, event)
            target = MsgFromDB(
                msg_id=echo.data["message_id"],
                sender_id=echo.data["sender"].user_id,
                sender_name=echo.data["sender"].nickname,
            )
    except get_reply.GetReplyException:
        await adapter.send_reply("获取目标消息失败")
        return
    except get_reply.TargetNotSpecifiedError:
        await adapter.send_reply("需要指定基准消息")
        return
    else:
        logger.debug(f"Got reply message from remote: {target!r}")
    (left, right), (sender_only, scale, ascale) = extract_params(event)
    # 参数范围约束
    llimit, rlimit = cfgloader.config.region_limit
    if (
        not (llimit <= left <= rlimit and llimit <= right <= rlimit)
    ) and event.sender.user_id != checker_factory.OWNER:
        await adapter.send_reply(
            f"请求的消息区间 `[{left}, {right}]` 超出规定范围 `[{rlimit}, {llimit}]`"
        )
        return
    slimit = cfgloader.config.scale_limit
    if (
        not (0 < scale <= cfgloader.config.scale_limit)
    ) and event.sender.user_id != checker_factory.OWNER:
        await adapter.send_reply(
            f"请求的缩放比例 `{scale}` 超出规定范围 `(0, {slimit}]`"
        )
        return
    if (
        not (0 < ascale <= cfgloader.config.scale_limit)
    ) and event.sender.user_id != checker_factory.OWNER:
        await adapter.send_reply(
            f"请求的抗锯齿缩放比例 `{ascale}` 超出规定范围 `(0, {slimit}]`"
        )
        return
    # 开始尝试 quote
    start_query_time = time.perf_counter()
    logger.debug(
        f"Preparing quote of {target}, [{left}, {right}], sender_only={sender_only}, {scale}x, a{ascale}x"
    )
    data, required_resources = await Recorder.run_sync(
        just_prepare,
        base_msgid=target.msg_id,
        group_id=event.group_id,
        sender_id=target.sender_id,
        edge_e=left,
        edge_l=right,
        sender_only=sender_only,
    )
    query_time = time.perf_counter() - start_query_time
    if data is None:
        await adapter.send_reply("数据库中没有可用的消息")
    else:
        # await adapter.send("已开始生成图像, 请稍等")
        # TODO: 增加更多参数选项
        start_draw_time = time.perf_counter()
        logger.debug(f"Got QuoteData: {data!r}")
        resources, notfounds = await gather_resources_from_recorder(required_resources)
        logger.debug(f"Got {len(resources)} resources from local")
        resources.update(await gather_resources(notfounds))
        logger.debug(
            f"Got {len(resources)}/{len(required_resources)} resources in total"
        )
        result = await do_quote(
            data,
            resources,
            scale=scale,
            scale_for_antialias=ascale,
        )

        imagebytes = result.getvalue()
        now_time = time.perf_counter()
        await adapter.send(
            [
                ImageSegment(file=await b2b64url_async(imagebytes)),
                TextSegment(
                    f"db: {query_time:.3f}s; draw: {now_time-start_draw_time:.3f}s"
                ),
            ]
        )
        if path := cfgloader.config.saveto:
            file = os.path.join(
                path,
                f"{time.strftime("%Y%m%d%H%M%S", time.localtime())}_{event.group_id}_{target.msg_id}[{left}-{right}]_{get_id()}.png",
            )
            async with aiofiles.open(file, "wb+") as fp:
                await fp.write(imagebytes)
            logger.info(f"Quote saved as {file}")

    completime = time.perf_counter()
    gap = 0
    while True:
        if (wait_time := (cfgloader.config.same_msg_min_dist - gap)) <= 0:
            return
        if not await suspend(wait_time):
            return
        gap = time.perf_counter() - completime
        await adapter.send_reply("引用此消息过于频繁, 请稍候再试")
