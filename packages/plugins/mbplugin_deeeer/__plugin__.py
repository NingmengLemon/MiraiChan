import asyncio
import os
import re
import time
from datetime import datetime
from io import BytesIO
from pathlib import Path

from lemony_checkers import get_checker_factory
from lemony_images.core import (
    bytes_to_b64_url,
)
from lemony_settings import BaseSettings, require
from lemony_utils.botutils import cached_avatar_source
from melobot.bot import get_bot
from melobot.plugin.base import PluginInfo, PluginPlanner
from melobot.protocols.onebot.v11.adapter.base import Adapter
from melobot.protocols.onebot.v11.adapter.event import GroupMessageEvent
from melobot.protocols.onebot.v11.adapter.segment import ImageSegment, TextSegment
from melobot.protocols.onebot.v11.handle import on_message

from .core import (
    DBPPATH,
    Painter,
    deerdbcore,
    query,
    query_one_day_total,
    record,
)

PLUGIN_IDENTIFIER = "deeeer"


class CfgModel(BaseSettings):
    trigger_chars: str = "鹿撸🦌"
    group_isolation: bool = False
    daily_limit: int = 100  # < 1 的值记为无限制


os.makedirs(os.path.dirname(DBPPATH), exist_ok=True)
cfgloader = require(model=CfgModel, identifier=PLUGIN_IDENTIFIER)

RESOURCE_PATH = Path(__file__).parent / "resources"

plugin = PluginPlanner(
    "0.1.3",
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


def post_init():
    global \
        DEER_CHARS, \
        DEER_JUDGE_REGEX, \
        DEER_COUNT_REGEX, \
        DAILY_LIMIT, \
        GROUP_ISOLATION, \
        PAINTER

    DEER_CHARS = cfgloader.value.trigger_chars
    DEER_JUDGE_REGEX = re.compile(
        rf"^(?:\s*[{re.escape(DEER_CHARS)}]\s*)+$", re.IGNORECASE
    )
    DEER_COUNT_REGEX = re.compile(rf"[{re.escape(DEER_CHARS)}]", re.IGNORECASE)
    DAILY_LIMIT = cfgloader.value.daily_limit
    GROUP_ISOLATION = cfgloader.value.group_isolation
    PAINTER = Painter(
        RESOURCE_PATH / "deer.jpg",
        RESOURCE_PATH / "correct.png",
    )


@bot.on_started
async def _():
    cfgloader.load()
    await asyncio.to_thread(post_init)
    await deerdbcore.startup(echo=True)


deer_lock = asyncio.Lock()


@plugin.use
@on_message(
    checker=get_checker_factory().new_checker(
        plugin_name=PLUGIN_IDENTIFIER, command_name="do_deer"
    )
)
async def deer(event: GroupMessageEvent, adapter: Adapter):
    if not re.match(DEER_JUDGE_REGEX, (msg := event.text)):
        return
    combo = len(re.findall(DEER_COUNT_REGEX, msg))
    await deerdbcore.wait_until_initialized()

    async with deer_lock:
        today_total = await query_one_day_total(
            date=datetime.now(),
            uid=event.user_id,
            gid=event.group_id if GROUP_ISOLATION else None,
        )
        if DAILY_LIMIT >= 1:
            if today_total >= DAILY_LIMIT:
                await adapter.send_reply(
                    "今天🦌太多了qwq\n奖励自己太多会变成小迷糊啦(๑>ᴗ<๑)"
                )
                return
            elif today_total + combo > DAILY_LIMIT:  # 隐式截断
                combo = DAILY_LIMIT - today_total

        await record(
            uid=event.user_id,
            gid=event.group_id,
            combo=combo,
            ts=time.time(),
        )

        records = await query(
            uid=event.user_id,
            gid=event.group_id if GROUP_ISOLATION else None,
        )

        nt = time.localtime()
        avatar = BytesIO(await cached_avatar_source.get(event.user_id))
        pic = await asyncio.to_thread(
            PAINTER.draw,
            records,
            year=nt.tm_year,
            month=nt.tm_mon,
            user_name=str(event.sender.nickname),
            user_avatar=avatar,
        )

    await adapter.send_reply(
        [
            TextSegment("成功🦌了" + (f" {combo} 次!" if combo > 1 else "!")),
            ImageSegment(
                file=await asyncio.to_thread(bytes_to_b64_url, pic.getvalue())
            ),
        ],
    )
