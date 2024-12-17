from typing import cast
from melobot import PluginPlanner, get_bot
from melobot.protocols.onebot.v11.handle import on_command, GetParseArgs
from melobot.protocols.onebot.v11.utils import ParseArgs
from melobot.protocols.onebot.v11 import Adapter

import little_helper

HelpMeErinnnnnn = PluginPlanner("0.1.0")

little_helper.set_bot_name(get_bot().name)
little_helper.register(
    "Helper",
    {
        "cmd": ".show_help [plugin|page]",
        "text": "显示帮助消息",
    },
)


def split_page_by_height(s: str, page_height: int):
    result: list[str] = []
    lines = s.splitlines()
    for i in range(0, len(lines), page_height):
        result.append("\n".join(lines[i : i + page_height]))
    return result


@HelpMeErinnnnnn.use
@on_command(".", " ", "show_help")
async def show_help(
    adapter: Adapter,
    args: ParseArgs = GetParseArgs(),
):
    plugin = cast(str, args.vals[0]) if args.vals else None
    if plugin and plugin[0].isdigit():
        if not plugin.isdigit():
            await adapter.send_reply("无效的页码")
            return
        page = int(plugin)
        pages = split_page_by_height(little_helper.export_markdown(None), 20)
        if page not in range(1, len(pages) + 1):
            await adapter.send_reply("超出范围的页码")
            return
        await adapter.send(pages[page - 1] + f"\nPage {page}/{len(pages)}")
    else:
        await adapter.send(little_helper.export_markdown(plugin))
