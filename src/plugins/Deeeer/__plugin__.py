import asyncio
import os
import re
import sys
import time
from io import BytesIO

from melobot import get_bot
from melobot.plugin import PluginPlanner
from melobot.protocols.onebot.v11.adapter import Adapter
from melobot.protocols.onebot.v11.adapter.event import GroupMessageEvent
from melobot.protocols.onebot.v11.adapter.segment import ImageSegment, TextSegment
from melobot.protocols.onebot.v11.handle import on_message

from lemony_utils.botutils import cached_avatar_source
from lemony_utils.database import AsyncDbCore
from lemony_utils.images import bytes_to_b64_url

from .core import TABLES, Drawer, query, record

dburl = "sqlite+aiosqlite:///data/record/deers.db"
os.makedirs("data/record/", exist_ok=True)

deerdbcore = AsyncDbCore(dburl, TABLES, echo="--debug" in sys.argv)
drawer = Drawer("data/deer.jpg", "data/correct.png")

plugin = PluginPlanner("0.1.0")
bot = get_bot()


@bot.on_started
async def _():
    await deerdbcore.startup()


DEER_CHARS = "鹿撸🦌"
DEER_JUDGE_REGEX = re.compile(rf"^(?:\s*[{re.escape(DEER_CHARS)}]\s*)+$", re.IGNORECASE)
DEER_COUNT_REGEX = re.compile(rf"[{re.escape(DEER_CHARS)}]", re.IGNORECASE)


@plugin.use
@on_message()
async def deer(event: GroupMessageEvent, adapter: Adapter):
    if not re.match(DEER_JUDGE_REGEX, (msg := event.text)):
        return
    combo = len(re.findall(DEER_COUNT_REGEX, msg))
    await deerdbcore.started.wait()
    await deerdbcore.run_sync(
        record, uid=event.user_id, gid=event.group_id, combo=combo, ts=time.time()
    )

    records = await deerdbcore.run_sync(query, uid=event.user_id, gid=event.group_id)
    nt = time.localtime()
    avatar = BytesIO(await cached_avatar_source.get(event.user_id))
    pic = drawer.draw(
        records,
        year=nt.tm_year,
        month=nt.tm_mon,
        user_name=event.sender.nickname,
        user_avatar=avatar,
    )
    await adapter.send_reply(
        [
            TextSegment(f"成功🦌了 {combo} 次!"),
            ImageSegment(
                file=await asyncio.to_thread(bytes_to_b64_url, pic.getvalue())
            ),
        ],
    )
