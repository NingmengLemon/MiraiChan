import json

from melobot import get_bot
from melobot.plugin import PluginPlanner
from melobot.handle import on_command
from melobot.protocols.onebot.v11.adapter import Adapter
from melobot.utils.parse import CmdArgs

from arknights_datasource import ArknSource
from lemony_utils.images import text_to_imgseg
import little_helper

ArknightsUtils = PluginPlanner("0.1.0")
little_helper.register(
    "ArknightsUtils",
    {
        "cmd": ".{arkquery|aq} {operator|o} <name>",
        "text": "查询干员信息",
    },
    {
        "cmd": ".{arkquery|aq} update",
        "text": "更新游戏数据",
    },
)

aksource = ArknSource()
bot = get_bot()


@bot.on_started
async def _():
    await aksource.update()


@ArknightsUtils.use
@on_command(".", " ", ["arkquery", "aq"])
async def query(
    adapter: Adapter,
    args: CmdArgs,
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
