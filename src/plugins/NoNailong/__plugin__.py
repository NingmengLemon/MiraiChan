import asyncio
import atexit
from io import BytesIO
import json
import base64
import time
from typing import TypedDict
import hashlib

from pydantic import BaseModel

from melobot.utils import lock
from melobot.plugin import Plugin
from melobot.log import GenericLogger
from melobot.protocols.onebot.v11.handle import on_command, on_message
from melobot.protocols.onebot.v11.adapter import Adapter
from melobot.protocols.onebot.v11.adapter.segment import ReplySegment, ImageSegment
from melobot.protocols.onebot.v11.adapter.event import GroupMessageEvent, MessageEvent
import aiohttp
from PIL import Image, ImageOps

from configloader import ConfigLoader, ConfigLoaderMetadata
import checker_factory
from lemony_utils.consts import http_headers
from lemony_utils.templates import async_http
from lemony_utils.images import text_to_imgseg


class NLConfig(BaseModel):
    api: str | None = "http://127.0.0.1:9656/predict"
    api_key: str | None = None
    focus_list: list[int] = []
    score_threshold: float = 0.7
    banned_emoji_package_ids: list[int] = [
        231182,
        231412,
        231764,
        239439,
        239546,
        239871,
    ]
    ban_votethreshold: int = 4
    ban_time: int = 5 * 60
    max_ban_time: int = 60 * 60 * 24 * 30 - 1
    ban_time_mult: float = 2.0
    ban_time_record: dict[int, int] = {}
    vote_expires: float = 10 * 60
    not_nlimg_hashes: list[str] = []  # sha256
    nlimg_hashes: list[str] = []  # sha256


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


@lock()
async def get_ban_time(user_id: int):
    ban_time = cfgloader.config.ban_time_record.get(
        user_id,
        cfgloader.config.ban_time,
    )
    cfgloader.config.ban_time_record[user_id] = int(
        ban_time * cfgloader.config.ban_time_mult
    )
    return min(ban_time, cfgloader.config.max_ban_time)


class ConfirmationData(TypedDict):
    nlsender: int
    time: float
    vote: int
    voted: set[int]
    nlmsg: int
    imghash: str
    imgdata: BytesIO


confirm_sessions: dict[int, ConfirmationData] = {}
# bot发送的确认消息的 message_id: 数据
confirm_lock = asyncio.Lock()


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
    img = await asyncio.to_thread(preproc, img)
    form = aiohttp.FormData()
    form.add_field("image", img.getvalue(), content_type="image/png")
    async with async_http(
        API + (f"?key={API_KEY}" if API_KEY else ""), "post", data=form
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


@on_command(
    ".",
    " ",
    "recognize",
    checker=lambda e: e.user_id == checker_factory.owner,
)
async def test_recognize(adapter: Adapter, event: GroupMessageEvent):
    if _ := event.get_segments(ReplySegment):
        msg_id = _[0].data["id"]
    else:
        await adapter.send_reply("需要指定目标消息")
        return
    msg = await (await adapter.with_echo(adapter.get_msg)(msg_id))[0]
    if not msg.data:
        await adapter.send_reply("目标消息数据获取失败")
        return
    imgs = [s for s in msg.data["message"] if isinstance(s, ImageSegment)]
    if not imgs:
        await adapter.send_reply("消息中没有图片")
        return
    try:
        img = await fetch_image(str(imgs[0].data["url"]))
        result = await predict(img)
    except Exception as e:
        await adapter.send_reply(f"出错了: {e}")
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


async def is_admin(adapter: Adapter, group_id: int, user_id: int):
    echo = await (
        await adapter.with_echo(adapter.get_group_member_info)(
            group_id=group_id,
            user_id=user_id,
        )
    )[0]
    if echo.data is None:
        return None
    return echo.data["role"] in ("admin", "owner")


async def ban_combo(adapter: Adapter, event: GroupMessageEvent):
    await adapter.delete_msg(event.message_id)
    await adapter.set_group_ban(
        event.group_id, event.user_id, duration=await get_ban_time(event.user_id)
    )
    await adapter.send("切莫相信乃龙，我将为你指明道路")


@on_message()
async def daemon(adapter: Adapter, event: GroupMessageEvent, logger: GenericLogger):
    if not await is_admin(adapter, event.group_id, event.self_id):
        logger.debug("Im not admin in this group, skip check")
        return
    if sum(
        [
            s.data["emoji_package_id"] in BANNED_STICKERSETS
            for s in event.message
            if s.type == "mface"
        ]
    ):
        logger.info(f"banned emoji found in msg: {event}")
        await ban_combo(adapter, event)
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
            imghash = hashlib.sha256(imgdata.getvalue()).hexdigest()
            if imghash in cfgloader.config.not_nlimg_hashes:
                continue
            if imghash in cfgloader.config.nlimg_hashes:
                await ban_combo(adapter, event)
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
                logger.info("nailong detected! enter voting confirmation")
                await start_vote(
                    adapter, event, imghash=imghash, imgdata=imgdata, imgindex=i
                )
                return
    logger.debug("no nailong found")


async def start_vote(
    adapter: Adapter,
    event: GroupMessageEvent,
    imghash: str,
    imgdata: BytesIO,
    imgindex: int,
):
    echo = await (
        await adapter.with_echo(adapter.send_reply)(
            f"""这条消息的第 {imgindex+1} 张图片看上去像是乃龙，它确实是吗？
其余成员回复此条消息 '是' / '否' 以投票
( 0 / {cfgloader.config.ban_votethreshold} )"""
        )
    )[0]
    if not echo.data:
        return
    async with confirm_lock:
        confirm_sessions[echo.data["message_id"]] = ConfirmationData(
            nlsender=event.user_id,
            time=time.time(),
            vote=0,
            voted=set(),
            nlmsg=event.message_id,
            imghash=imghash,
            imgdata=imgdata,
        )


@on_message()
async def confirm_ban(
    adapter: Adapter, event: GroupMessageEvent, logger: GenericLogger
):
    if _ := event.get_segments(ReplySegment):
        msg_id = _[0].data["id"]
    else:
        return
    match event.text.strip():
        case "是的" | "是" | "对的" | "对":
            vote = True
        case "不是" | "不" | "不对" | "否":
            vote = False
        case _:
            return
    msg = await (await adapter.with_echo(adapter.get_msg)(msg_id))[0]
    if not msg.data:
        return
    async with confirm_lock:
        if msg.data["message_id"] not in confirm_sessions:
            return
        confirmation = confirm_sessions.get(msg.data["message_id"])

        if (
            confirmation["nlsender"] == event.user_id
            and confirmation["nlsender"] != checker_factory.owner
        ):
            await adapter.send_reply("不能给自己投票")
            return
        if event.user_id in confirmation["voted"]:
            await adapter.send_reply("你已经投过票了")
            return
        if event.user_id == checker_factory.owner:
            confirmation["vote"] += (
                cfgloader.config.ban_votethreshold
                if vote
                else -cfgloader.config.ban_votethreshold
            )
        else:
            confirmation["vote"] += 1 if vote else -1

        confirmation["voted"].add(event.user_id)
        if confirmation["vote"] >= cfgloader.config.ban_votethreshold:
            await adapter.send_reply("投票通过")
            await adapter.delete_msg(confirmation["nlmsg"])
            await adapter.set_group_ban(
                event.group_id,
                confirmation["nlsender"],
                duration=await get_ban_time(confirmation["nlsender"]),
            )
            cfgloader.config.nlimg_hashes.append(confirmation["imghash"])
            del confirm_sessions[msg.data["message_id"]]
            return
        if confirmation["vote"] <= -cfgloader.config.ban_votethreshold:
            await adapter.send_reply("已添加到图片白名单")
            cfgloader.config.not_nlimg_hashes.append(confirmation["imghash"])
            del confirm_sessions[msg.data["message_id"]]
            return


@on_command(".", " ", "reportnl")
async def report():
    pass


class AntiNailong(Plugin):
    version = "0.1.0"
    author = "LemonyNingmeng"
    flows = (test_recognize,)  # daemon, confirm_ban)
