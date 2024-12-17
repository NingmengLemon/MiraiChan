import asyncio
import atexit
from io import BytesIO
import random
import time
import traceback
from typing import Literal

import imagehash
from melobot import get_bot
from melobot.utils import lock, async_interval
from melobot.plugin import PluginPlanner
from melobot.log import GenericLogger, get_logger
from melobot.protocols.onebot.v11.utils import ParseArgs
from melobot.protocols.onebot.v11.handle import on_command, on_message, GetParseArgs
from melobot.protocols.onebot.v11.adapter import Adapter
from melobot.protocols.onebot.v11.adapter.segment import ImageRecvSegment, ImageSegment
from melobot.protocols.onebot.v11.adapter.event import GroupMessageEvent
import aiohttp
from yarl import URL
from PIL import Image

from configloader import ConfigLoader, ConfigLoaderMetadata
import checker_factory
from lemony_utils.templates import async_http
from lemony_utils.images import text_to_imgseg, bytes_to_b64_url
import little_helper

from .models import NLConfig, ImgRec, PredictResult
from .utils import preprocess, get_reply, to_hash, draw_boxs, fetch_image

NoNailong = PluginPlanner("1.0.0")
little_helper.register(
    "AntiNailong",
    {
        "cmd": ".recognize [--image|-i]",
        "text": "尝试识别回复的消息中的图片\n*Owner Only*",
    },
    {
        "cmd": ".{notnl|并非乃龙}",
        "text": "将回复的消息或被判定为乃龙的消息中的图片标注为非乃龙\n*Owner Only*",
    },
    {
        "cmd": ".{reportnl|这是乃龙}",
        "text": "同上，但标注为乃龙\n*Owner Only*",
    },
)


cfgloader = ConfigLoader(
    ConfigLoaderMetadata(
        model=NLConfig,
        filename="antinailong_conf.json",
    )
)
cfgloader.load_config()
API = cfgloader.config.api
API_KEY = cfgloader.config.api_key
THRESHOLD = cfgloader.config.score_threshold
BANNED_STICKERSETS = cfgloader.config.banned_emoji_package_ids
atexit.register(cfgloader.save_config)


imgrecord: dict[int, ImgRec] = {}  # key=原始图片消息的id
banned_imgrec: dict[int, int] = {}  # 通知消息的id: 原始消息的id
# 群号: 自我角色, 时间戳
self_role_cache: dict[int, tuple[Literal["owner", "admin", "member"], float]] = {}
bot = get_bot()
logger = get_logger()

clear_task: asyncio.Task = None


async def clear_imgrecord():
    msgids = [
        k
        for k, v in imgrecord.items()
        if time.time() - v["ts"] >= cfgloader.config.imgrec_expires
    ]
    for msgid in msgids:
        del imgrecord[msgid]
    for msgid in [k for k, v in banned_imgrec.items() if v in msgids]:
        del banned_imgrec[msgid]


def query_nl_anno(img: BytesIO | Image.Image | str | imagehash.ImageHash):
    img = to_hash(img)
    hexhash = str(img)
    max_dist = cfgloader.config.max_hash_distance
    if hexhash in cfgloader.config.nlimg_hashes:
        logger.debug("hit yes_list, phash dist = 0")
        return True
    if hexhash in cfgloader.config.not_nlimg_hashes:
        logger.debug("hit not_list, phash dist = 0")
        return False
    if max_dist <= 0:
        return None
    for i in cfgloader.config.nlimg_hashes.copy():
        if len(i) == len(img) and (dist := imagehash.hex_to_hash(i) - img) <= max_dist:
            logger.debug(f"hit yes_list, phash dist = {dist}")
            return True
    for i in cfgloader.config.not_nlimg_hashes.copy():
        if len(i) == len(img) and (dist := imagehash.hex_to_hash(i) - img) <= max_dist:
            logger.debug(f"hit not_list, phash dist = {dist}")
            return False
    return None


@bot.on_loaded
async def _():
    global clear_task
    clear_task = async_interval(clear_imgrecord, cfgloader.config.imgrec_expires)


@bot.on_stopped
async def _():
    if clear_task:
        clear_task.cancel()


@lock()
async def predict(img: BytesIO):
    form = aiohttp.FormData()
    form.add_field("image", img.getvalue(), content_type="image/png")
    async with async_http(
        URL(API) % ({"key": API_KEY} if API_KEY else {}), "post", data=form
    ) as resp:
        resp.raise_for_status()
        return PredictResult.model_validate(await resp.json())


def record_img(
    event: GroupMessageEvent,
    imghash: str,
):
    imgrecord[event.message_id] = ImgRec(
        hash=imghash,
        sender=event.user_id,
        msgid=event.message_id,
        ts=time.time(),
    )


@NoNailong.use
@on_command(
    ".",
    " ",
    "recognize",
    checker=checker_factory.get_owner_checker(),
)
async def test_recognize(
    adapter: Adapter, event: GroupMessageEvent, args: ParseArgs = GetParseArgs()
):
    msg = await get_reply(adapter, event)
    if msg is None:
        await adapter.send_reply("获取消息失败")
        return
    imgs = [s for s in msg.data["message"] if isinstance(s, ImageRecvSegment)]
    if not imgs:
        await adapter.send_reply("消息中没有图片")
        return
    try:
        img = await asyncio.to_thread(
            preprocess, await fetch_image(str(imgs[0].data["url"]))
        )
        result = await predict(img)
    except Exception:
        await adapter.send_reply(f"出错了:\n{traceback.format_exc()}")
        return
    if not result.data:
        await adapter.send_reply("识别结果为空")
        return
    if args.vals and args.vals[0] in ("--image", "-i"):
        drawn_img = await asyncio.to_thread(draw_boxs, img, result.data)
        await adapter.send_reply(
            ImageSegment(file=bytes_to_b64_url(drawn_img.getvalue()))
        )
    else:
        await adapter.send_reply(await text_to_imgseg(result.model_dump_json(indent=2)))


async def get_self_role(adapter: Adapter, group_id: int, self_id: int):
    cache = self_role_cache.get(group_id)
    if cache is None or time.time() - cache[1] >= cfgloader.config.role_cache_expires:
        echo = await (
            await adapter.with_echo(adapter.get_group_member_info)(
                group_id=group_id,
                user_id=self_id,
            )
        )[0]
        if echo.data is None:
            return cache[0] if cache else None
        self_role_cache[group_id] = (echo.data["role"], time.time())
    cache = self_role_cache.get(group_id)
    return cache[0] if cache else None


async def ban_combo(
    adapter: Adapter,
    event: GroupMessageEvent,
    score: float | None = None,
    index: int = 0,
    record: bool = True,
):
    if not cfgloader.config.del_fail_msgs and not cfgloader.config.del_succ_msgs:
        return
    echo = await (
        await adapter.with_echo(adapter.send)(
            (
                random.choice(cfgloader.config.del_succ_msgs)
                if (
                    await (
                        await adapter.with_echo(adapter.delete_msg)(event.message_id)
                    )[0]
                ).is_ok()
                else random.choice(cfgloader.config.del_fail_msgs)
            )
            + (
                f"\n({index+1}, {score:.4f})"
                if score and cfgloader.config.show_score
                else ""
            )
        )
    )[0]
    if echo.data:
        if record:
            banned_imgrec[echo.data["message_id"]] = event.message_id
        return echo.data["message_id"]


@NoNailong.use
@on_message()
async def daemon(adapter: Adapter, event: GroupMessageEvent, logger: GenericLogger):
    bot_role = await get_self_role(adapter, event.group_id, event.self_id)
    if bot_role not in ("owner", "admin"):
        logger.debug(f"Im not admin in group {event.group_id}, skip check")
        return
    if sum(
        [
            s.data["emoji_package_id"] in BANNED_STICKERSETS
            for s in event.message
            if s.type == "mface"
        ]
    ):
        logger.info(f"banned emoji found in msg: {event}")
        await ban_combo(adapter, event, record=False)
        return
    # predict by model
    imgs = [s for s in event.message if isinstance(s, ImageRecvSegment)]
    if not imgs:
        logger.debug("no img found, skip predict")
        return
    if not API:
        logger.debug("API not set, skip predict")
        return
    logger.debug(
        f"checking {event.message_id} by {event.sender.user_id}({event.sender.nickname})"
    )
    for i, img in enumerate(imgs):
        try:
            imgdata = await fetch_image(str(img.data["url"]))
            imghash = await asyncio.to_thread(to_hash, imgdata.getvalue())
            record_img(event, str(imghash))
            if (anno := query_nl_anno(imghash)) is not None:
                if anno:
                    await ban_combo(adapter, event, index=i)
                    return
                else:
                    continue
            result = await predict(await asyncio.to_thread(preprocess, imgdata))
        except Exception as e:
            logger.error(f"error when recognize: {e}")
            continue
        for entity in result.data:
            logger.debug(
                f"found {entity['class_name']} (score={entity['score']}) in img {i}"
            )
            if entity["class_name"] == "nailong" and entity["score"] >= THRESHOLD:
                logger.info("nailong detected!")
                await ban_combo(adapter, event, score=entity["score"], index=i)
                return
    logger.debug("no nailong found")


@NoNailong.use
@on_command(
    ".",
    " ",
    ["reportnl", "这是乃龙"],
    checker=checker_factory.get_owner_checker(),
)
async def report(adapter: Adapter, event: GroupMessageEvent, logger: GenericLogger):
    msg = await get_reply(adapter, event)
    if not msg or not msg.data:
        await adapter.send_reply("获取消息失败")
        return
    orig_msgid = msg.data["message_id"]
    orig_record = imgrecord.get(orig_msgid)
    if orig_record is None:
        await adapter.send_reply("没有找到图片记录w")
        return
    imghash = orig_record["hash"]
    if imghash in cfgloader.config.not_nlimg_hashes:
        cfgloader.config.not_nlimg_hashes.remove(imghash)
    if imghash not in cfgloader.config.nlimg_hashes:
        cfgloader.config.nlimg_hashes.append(imghash)
    logger.info(f"put {imghash=} into nl list")
    await adapter.delete_msg(orig_msgid)
    await adapter.send_reply("已应用更改")


@NoNailong.use
@on_command(
    ".",
    " ",
    ["notnl", "并非乃龙"],
    checker=checker_factory.get_owner_checker(),
)
async def report_not(adapter: Adapter, event: GroupMessageEvent, logger: GenericLogger):
    msg = await get_reply(adapter, event)
    if not msg or not msg.data:
        await adapter.send_reply("获取消息失败")
        return
    orig_msgid = banned_imgrec.get(msg.data["message_id"]) or msg.data["message_id"]
    orig_record = imgrecord.get(orig_msgid)
    if orig_record is None:
        await adapter.send_reply("没有找到图片记录w")
        return
    imghash = orig_record["hash"]
    if imghash in cfgloader.config.nlimg_hashes:
        cfgloader.config.nlimg_hashes.remove(imghash)
    if imghash not in cfgloader.config.not_nlimg_hashes:
        cfgloader.config.not_nlimg_hashes.append(imghash)
    logger.info(f"put {imghash=} into not_nl list")
    await adapter.send_reply("已应用更改")
