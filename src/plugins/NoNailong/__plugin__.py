import asyncio
import atexit
from io import BytesIO
import json
import random
import time
from typing import Any, TypedDict, Literal, cast
import hashlib

from melobot import get_bot
from melobot.utils import lock, async_interval
from melobot.plugin import Plugin
from melobot.log import GenericLogger
from melobot.protocols.onebot.v11.utils import ParseArgs
from melobot.protocols.onebot.v11.handle import on_command, on_message, GetParseArgs
from melobot.protocols.onebot.v11.adapter import Adapter
from melobot.protocols.onebot.v11.adapter.segment import ReplySegment, ImageSegment
from melobot.protocols.onebot.v11.adapter.event import GroupMessageEvent, MessageEvent
import aiohttp
from PIL import Image, ImageOps, ImageDraw
from pydantic import BaseModel
from yarl import URL

from configloader import ConfigLoader, ConfigLoaderMetadata
import checker_factory
from lemony_utils.consts import http_headers
from lemony_utils.templates import async_http
from lemony_utils.images import text_to_imgseg, default_font_cache, bytes_to_b64_url


class NLConfig(BaseModel):
    api: str | None = "http://127.0.0.1:9656/predict"
    api_key: str | None = None
    score_threshold: float = 0.8
    banned_emoji_package_ids: list[int] = [
        231182,
        231412,
        231764,
        239439,
        239546,
        239871,
    ]
    not_nlimg_hashes: list[str] = []  # sha256
    nlimg_hashes: list[str] = []  # sha256
    imgrec_expires: float = 60 * 60 * 12
    role_cache_expires: float = 60 * 5


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


class ImgRec(TypedDict):
    hash: str
    sender: int
    msgid: int
    ts: float


imgrecord: dict[int, ImgRec] = {}  # key=原始图片消息的id
banned_imgrec: dict[int, int] = {}  # 通知消息的id: 原始消息的id
# 群号: 自我角色, 时间戳
self_role_cache: dict[int, tuple[Literal["owner", "admin", "member"], float]] = {}
bot = get_bot()

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


@bot.on_loaded
async def _():
    global clear_task
    clear_task = async_interval(clear_imgrecord, cfgloader.config.imgrec_expires)


@bot.on_stopped
async def _():
    if clear_task:
        clear_task.cancel()


def preproc(img: BytesIO):
    pimg = Image.open(img).convert("RGBA")
    w, h = pimg.size
    if w > 512 or h > 512:
        pimg = ImageOps.contain(pimg, (512, 512))
    result = BytesIO()
    pimg.save(result, "png")
    return result


@lock()
async def predict(img: BytesIO):
    form = aiohttp.FormData()
    form.add_field("image", img.getvalue(), content_type="image/png")
    async with async_http(
        URL(API) % ({"key": API_KEY} if API_KEY else {}), "post", data=form
    ) as resp:
        resp.raise_for_status()
        return await resp.json()


async def fetch_image(url: str):
    url = url.replace(
        "https://multimedia.nt.qq.com.cn/", "http://multimedia.nt.qq.com.cn/"
    )
    async with async_http(url, "get", headers=http_headers) as resp:
        resp.raise_for_status()
        return BytesIO(await resp.content.read())


async def get_reply(adapter: Adapter, event: MessageEvent):
    if _ := event.get_segments(ReplySegment):
        msg_id = _[0].data["id"]
    else:
        return
    msg = await (await adapter.with_echo(adapter.get_msg)(msg_id))[0]
    if not msg.data:
        return
    return msg


def _calc_hash(b: bytes):
    return hashlib.sha256(b).hexdigest()


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


def draw_boxs(image: BytesIO, data: dict[str, Any], font_size=20, width=2):
    pimg = Image.open(image).convert("RGBA")
    draw = ImageDraw.Draw(pimg)
    for entity in data["data"]:
        draw.rectangle(entity["box"], width=width, outline=(255, 0, 0, 255))
        draw.text(
            (entity["box"][0] + width, entity["box"][1]),
            entity["class_name"] + f" {entity['score']:.4f}",
            font=default_font_cache.use(font_size),
            fill=(255, 0, 0, 255),
        )
    result = BytesIO()
    pimg.save(result, "png")
    return result


@on_command(
    ".",
    " ",
    "recognize",
    checker=lambda e: e.user_id == checker_factory.owner,
)
async def test_recognize(
    adapter: Adapter, event: GroupMessageEvent, args: ParseArgs = GetParseArgs()
):
    msg = await get_reply(adapter, event)
    if msg is None:
        await adapter.send_reply("获取消息失败")
        return
    imgs = [s for s in msg.data["message"] if isinstance(s, ImageSegment)]
    if not imgs:
        await adapter.send_reply("消息中没有图片")
        return
    try:
        img = await fetch_image(str(imgs[0].data["url"]))
        img = await asyncio.to_thread(preproc, img)
        result = await predict(img)
    except Exception as e:
        await adapter.send_reply(f"出错了: {e}")
        return
    if not result["data"]:
        await adapter.send_reply("识别结果为空")
        return
    if args.vals and args.vals[0] == "image":
        drawn_img = await asyncio.to_thread(draw_boxs, img, result)
        await adapter.send_reply(
            ImageSegment(file=bytes_to_b64_url(drawn_img.getvalue()))
        )
    else:
        await adapter.send_reply(
            await text_to_imgseg(
                json.dumps(
                    result,
                    indent=2,
                    ensure_ascii=False,
                )
            )
        )


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
            return None
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
    await adapter.delete_msg(event.message_id)
    echo = await (
        await adapter.with_echo(adapter.send)(
            # random.choice(["你不许发乃龙", "切莫相信乃龙，我将为你指明道路"])
            "你不许发乃龙"
            + (f"\n（图 {index+1}，{score=:.4f}）" if score else "")
        )
    )[0]
    if echo.data:
        if record:
            banned_imgrec[echo.data["message_id"]] = event.message_id
        return echo.data["message_id"]


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
    imgs = [s for s in event.message if isinstance(s, ImageSegment)]
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
            imghash = await asyncio.to_thread(_calc_hash, imgdata.getvalue())
            record_img(event, imghash)
            if imghash in cfgloader.config.not_nlimg_hashes:
                continue
            if imghash in cfgloader.config.nlimg_hashes:
                await ban_combo(adapter, event, index=i)
                return
            result = await predict(imgdata)
        except Exception as e:
            logger.error(f"error when recognize: {e}")
            continue
        for entity in result["data"]:
            logger.debug(
                f"found {entity['class_name']} (score={entity['score']}) in img {i}"
            )
            if entity["class_name"] == "nailong" and entity["score"] >= THRESHOLD:
                logger.info("nailong detected!")
                await ban_combo(adapter, event, score=entity["score"], index=i)
                return
    logger.debug("no nailong found")


@on_command(
    ".",
    " ",
    ["reportnl", "这是乃龙"],
    checker=lambda e: e.user_id == checker_factory.owner,
)
async def report(adapter: Adapter, event: GroupMessageEvent, logger: GenericLogger):
    msg = await get_reply(adapter, event)
    if not msg:
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
    logger.info(f"put {imghash=} into included list")
    await adapter.delete_msg(orig_msgid)
    await adapter.send_reply("已应用更改")


@on_command(
    ".",
    " ",
    ["notnl", "并非乃龙"],
    checker=lambda e: e.user_id == checker_factory.owner,
)
async def report_not(adapter: Adapter, event: GroupMessageEvent, logger: GenericLogger):
    msg = await get_reply(adapter, event)
    if not msg:
        # await adapter.send_reply("获取消息失败")
        return
    orig_msgid = banned_imgrec.get(msg.data["message_id"])
    if orig_msgid is None:
        await adapter.send_reply("这条消息没有被识别成乃龙啊（？）")
        return
    orig_record = imgrecord.get(orig_msgid)
    if orig_record is None:
        await adapter.send_reply("没有找到图片记录w")
        return
    imghash = orig_record["hash"]
    if imghash in cfgloader.config.nlimg_hashes:
        cfgloader.config.nlimg_hashes.remove(imghash)
    if imghash not in cfgloader.config.not_nlimg_hashes:
        cfgloader.config.not_nlimg_hashes.append(imghash)
    logger.info(f"put {imghash=} into excluded list")
    await adapter.send_reply("已应用更改")


class AntiNailong(Plugin):
    version = "0.1.0"
    author = "LemonyNingmeng"
    flows = (test_recognize, daemon, report, report_not)
