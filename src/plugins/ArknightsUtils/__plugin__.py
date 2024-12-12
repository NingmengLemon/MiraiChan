import json
import asyncio
from melobot import get_bot
from melobot.plugin import Plugin
from melobot.log import GenericLogger
from melobot.protocols.onebot.v11.handle import on_command, on_message
from melobot.protocols.onebot.v11.adapter import Adapter
from melobot.protocols.onebot.v11.handle import GetParseArgs
from melobot.protocols.onebot.v11.utils import CmdParser, ParseArgs
from melobot.protocols.onebot.v11.adapter.segment import ReplySegment, ImageSegment
from melobot.protocols.onebot.v11.adapter.event import MessageEvent

from arknights_datasource import ArknSource
from lemony_utils.images import text_to_imgseg


aksource = ArknSource()
bot = get_bot()


@bot.on_started
async def _():
    await aksource.update()


@on_command(".", " ", ["arkquery", "aq"])
async def query(
    adapter: Adapter,
    event: MessageEvent,
    logger: GenericLogger,
    args: ParseArgs = GetParseArgs(),
):
    if len(args.vals) < 1:
        await adapter.send_reply("不正确的指令格式")
        return
    match args.vals[0]:
        case "operator" | "o":
            if len(args.vals) != 2:
                await adapter.send_reply("不正确的指令格式")
                return
            async with aksource.use(await aksource.operators()) as oprts:
                result = list(
                    filter(
                        lambda x: args.vals[1].lower()
                        in (x["zh"].lower(), x["en"].lower(), x["ja"].lower()),
                        oprts,
                    )
                )
                if result:
                    await adapter.send_reply(
                        await text_to_imgseg(
                            json.dumps(result[0], indent=2, ensure_ascii=False)
                        )
                    )
                else:
                    await adapter.send_reply("没有找到数据")
        case "update" | "u":
            if len(args.vals) != 1:
                await adapter.send_reply("不正确的指令格式")
                return
            try:
                await aksource.update()
            except Exception as e:
                await adapter.send_reply(f"数据更新失败：{e}")
            else:
                await adapter.send_reply("数据更新完成")
        case _:
            await adapter.send_reply("不正确的指令格式")


class AkUtils(Plugin):
    version = "0.1.0"
    author = "LemonyNingmeng"
    flows = (query,)
