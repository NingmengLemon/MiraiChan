import asyncio
import os
import re
import sys
import time
from datetime import datetime
from io import BytesIO

from melobot.bot import get_bot
from melobot.plugin.base import PluginPlanner
from melobot.protocols.onebot.v11.adapter.base import Adapter
from melobot.protocols.onebot.v11.adapter.event import GroupMessageEvent
from melobot.protocols.onebot.v11.adapter.segment import ImageSegment, TextSegment
from melobot.protocols.onebot.v11.handle import on_message
from melobot.utils.base import to_async
from melobot.utils.deco import lock

from lemony_utils.botutils import cached_avatar_source
from lemony_utils.database import AsyncDbCore
from lemony_utils.images import bytes_to_b64_url

from .core import TABLES, Drawer, query, query_one_day_total, record

dburl = "sqlite+aiosqlite:///data/record/deers.db"
os.makedirs("data/record/", exist_ok=True)

deerdbcore = AsyncDbCore(dburl, TABLES, echo="--debug" in sys.argv)
drawer = Drawer("data/deer.jpg", "data/correct.png")

record_a = deerdbcore.to_async(record)
query_a = deerdbcore.to_async(query)
query_one_day_total_a = deerdbcore.to_async(query_one_day_total)

plugin = PluginPlanner("0.1.1")
bot = get_bot()


@bot.on_started
async def _():
    await deerdbcore.startup()


DEER_CHARS = "鹿撸🦌"
DEER_JUDGE_REGEX = re.compile(rf"^(?:\s*[{re.escape(DEER_CHARS)}]\s*)+$", re.IGNORECASE)
DEER_COUNT_REGEX = re.compile(rf"[{re.escape(DEER_CHARS)}]", re.IGNORECASE)
DAILY_LIMIT = 100
GROUP_ISOLATION = True
# TODO: 写成配置文件
draw = to_async(drawer.draw)


@plugin.use
@on_message(decos=[lock()])
async def deer(event: GroupMessageEvent, adapter: Adapter):
    if not re.match(DEER_JUDGE_REGEX, (msg := event.text)):
        return
    combo = len(re.findall(DEER_COUNT_REGEX, msg))
    await deerdbcore.started.wait()

    today_total = await query_one_day_total_a(
        datetime.now(),
        uid=event.user_id,
        gid=event.group_id if GROUP_ISOLATION else None,
    )
    if today_total >= DAILY_LIMIT:
        await adapter.send_reply("今天🦌太多了qwq\n奖励自己太多会变成小迷糊啦(๑>ᴗ<๑)")
        return
    elif today_total + combo > DAILY_LIMIT:
        combo = DAILY_LIMIT - today_total

    await record_a(uid=event.user_id, gid=event.group_id, combo=combo, ts=time.time())

    records = await query_a(
        uid=event.user_id, gid=event.group_id if GROUP_ISOLATION else None
    )
    nt = time.localtime()
    avatar = BytesIO(await cached_avatar_source.get(event.user_id))
    pic = await draw(
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
