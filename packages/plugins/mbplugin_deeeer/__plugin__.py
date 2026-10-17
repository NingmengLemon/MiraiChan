import asyncio
import random
import re
import time
from datetime import datetime
from io import BytesIO
from logging import getLogger
from pathlib import Path
from typing import TypedDict

from lemony_checkers import get_checker_factory_wrapper
from lemony_images import bytes_to_b64_url
from lemony_onebot_utils.botutils import cached_avatar_source
from lemony_settings import BaseSettings, require
from lemony_storage_helper.files import resource_path
from lemony_utils.help import Command, register_help
from melobot.bot import get_bot
from melobot.plugin.base import PluginInfo, PluginPlanner
from melobot.protocols.onebot.v11.adapter.base import Adapter
from melobot.protocols.onebot.v11.adapter.event import GroupMessageEvent
from melobot.protocols.onebot.v11.adapter.segment import ImageSegment, TextSegment
from melobot.protocols.onebot.v11.handle import on_message
from PIL import Image

from .core import (
    Painter,
    deerdbcore,
    query,
    query_one_day_total,
    record,
)
from .migration import migrate

logger = getLogger(__name__)

PLUGIN_IDENTIFIER = "deeeer"


class DeerImgCfg(TypedDict):
    filename: str
    random_weight: float


class DeerImg(DeerImgCfg):
    data: Image.Image


class CfgModel(BaseSettings):
    trigger_chars: str = "鹿撸🦌"
    group_isolation: bool = False
    daily_limit: int = 100  # < 1 的值记为无限制
    # pydantic 会为每个实例复制默认值, 可变默认值在这里是安全的
    enabled_deer_imgs: list[DeerImgCfg] = [  # noqa: RUF012
        {"filename": "deer.jpg", "random_weight": 1.0},
    ]
    correct_sign_img: str = "correct.png"


cfgloader = require(model=CfgModel, identifier=PLUGIN_IDENTIFIER)

_limit = cfgloader.value.daily_limit
register_help(
    PLUGIN_IDENTIFIER,
    title="签到",
    summary="群签到, 生成本月签到日历, 仅群聊",
    commands=[
        Command(
            "、".join(cfgloader.value.trigger_chars),
            "发送只由这些字组成的消息即可签到, 一条消息里有几个字算几次"
            + (f"\n每天最多 {_limit} 次" if _limit >= 1 else ""),
        )
    ],
)

RESOURCE_PATH = Path(__file__).parent / "resources"

plugin = PluginPlanner(
    "0.1.4",
    info=PluginInfo(
        desc="只是一个群签到插件",
    ),
)
bot = get_bot()

# Global variables initialized after config loading
PAINTER: Painter
DEER_CHARS: str
DEER_JUDGE_REGEX: re.Pattern[str]
DEER_COUNT_REGEX: re.Pattern[str]
DAILY_LIMIT: int
GROUP_ISOLATION: bool
DEERS: list[DeerImg]
CORRECT_SIGN_IMG: Image.Image


def post_init():
    global \
        DEER_CHARS, \
        DEER_JUDGE_REGEX, \
        DEER_COUNT_REGEX, \
        DAILY_LIMIT, \
        GROUP_ISOLATION, \
        PAINTER, \
        DEERS, \
        CORRECT_SIGN_IMG

    DEER_CHARS = cfgloader.value.trigger_chars
    DEER_JUDGE_REGEX = re.compile(
        rf"^(?:\s*[{re.escape(DEER_CHARS)}]\s*)+$", re.IGNORECASE
    )
    DEER_COUNT_REGEX = re.compile(rf"[{re.escape(DEER_CHARS)}]", re.IGNORECASE)
    DAILY_LIMIT = cfgloader.value.daily_limit
    GROUP_ISOLATION = cfgloader.value.group_isolation
    DEERS = []
    for d in cfgloader.value.enabled_deer_imgs:
        deer_path = resource_path(RESOURCE_PATH, d["filename"], identifier="deeeer")
        DEERS.append(
            {
                "data": Image.open(deer_path).convert("RGBA"),
                "filename": d["filename"],
                "random_weight": d["random_weight"],
            }
        )
        logger.info(f"loaded deer img: {d['filename']}")
    logger.info(f"loaded all deer imgs, {len(DEERS)} in total")
    CORRECT_SIGN_IMG = Image.open(
        resource_path(
            RESOURCE_PATH, cfgloader.value.correct_sign_img, identifier="deeeer"
        )
    ).convert("RGBA")
    PAINTER = Painter()


_ready = asyncio.Event()
_init_failed = False


@plugin.on_ready
async def _() -> None:
    # melobot 会吞掉 hook 里的异常, 这里自己记下失败, 让 handler 放弃而不是挂起或 NameError
    global _init_failed
    try:
        cfgloader.load()
        await asyncio.to_thread(post_init)
        await deerdbcore.startup(prepare=migrate)
    except Exception:
        _init_failed = True
        logger.exception("deeeer 初始化失败, 插件将不响应")
    finally:
        _ready.set()


deer_lock = asyncio.Lock()
checker_factory = get_checker_factory_wrapper(
    plugin_name=PLUGIN_IDENTIFIER,
)


#: 当日次数用尽时的回复
_LIMIT_REPLY = "今天🦌太多了qwq\n奖励自己太多会变成小迷糊啦(๑>ᴗ<๑)"


def _truncate_combo(combo: int, today_total: int) -> int:
    """按当日剩余额度截断本次次数 (DAILY_LIMIT < 1 表示不限次)"""
    if DAILY_LIMIT < 1:
        return combo
    return min(combo, max(0, DAILY_LIMIT - today_total))


@plugin.use
@on_message()
async def deer(event: GroupMessageEvent, adapter: Adapter):
    await _ready.wait()
    if _init_failed:
        return
    if not re.match(DEER_JUDGE_REGEX, (msg := event.text)):
        return
    if not await checker_factory(command_name="do_deer").check(event):
        return
    combo = len(re.findall(DEER_COUNT_REGEX, msg))
    ts = time.time()
    group_id = event.group_id
    # GROUP_ISOLATION 关闭时按用户跨群统计, 但记录本身始终带真实群号
    scope_gid = group_id if GROUP_ISOLATION else None

    # 锁外先做一次便宜的额度检查: 满了就直接拒绝, 既不拉头像也不画图
    if DAILY_LIMIT >= 1:
        today_total = await query_one_day_total(
            date=datetime.now().astimezone(), uid=event.user_id, gid=scope_gid
        )
        if today_total >= DAILY_LIMIT:
            await adapter.send_reply(_LIMIT_REPLY)
            return
        combo = _truncate_combo(combo, today_total)

    # 头像拉取与绘图都放到锁外, 而且排在记账之前: 它们失败时还没有扣次数, 不会白扣
    avatar = BytesIO(await cached_avatar_source.get(event.user_id))
    records = await query(uid=event.user_id, gid=scope_gid)
    random_deer = random.choices(
        DEERS,
        [deer["random_weight"] for deer in DEERS],
    )[0]
    logger.info(f"selected deer img: {random_deer['filename']}")
    nt = time.localtime(ts)
    pic = await asyncio.to_thread(
        PAINTER.draw,
        random_deer["data"],
        CORRECT_SIGN_IMG,
        # 画的是记账之后的日历, 这里先算上本次 (combo 在锁内可能被再次截断, 极端并发下
        # 图上的 xN 会略大, 不影响账目)
        records=[*records, (ts, combo)],
        year=nt.tm_year,
        month=nt.tm_mon,
        user_name=str(event.sender.nickname),
        user_avatar=avatar,
    )

    # 临界区只包含"查当日总数 + 记账": 锁外那次检查可能已经过期, 以锁内读数为准重算
    async with deer_lock:
        if DAILY_LIMIT >= 1:
            today_total = await query_one_day_total(
                date=datetime.now().astimezone(), uid=event.user_id, gid=scope_gid
            )
            if today_total >= DAILY_LIMIT:
                # 图已经画好, 但既不记账也不发送, 避免超发
                await adapter.send_reply(_LIMIT_REPLY)
                return
            combo = _truncate_combo(combo, today_total)

        await record(
            uid=event.user_id,
            gid=group_id,
            combo=combo,
            ts=ts,
        )

    await adapter.send_reply(
        [
            TextSegment("成功🦌了" + (f" {combo} 次!" if combo > 1 else "!")),
            ImageSegment(
                file=await asyncio.to_thread(bytes_to_b64_url, pic.getvalue())
            ),
        ],
    )
