"""帮助: ``.help [名称]``. 内容来自各插件在 lemony_utils.help 里注册的说明, 以合并转发发送."""

import logging

from lemony_onebot_utils.forward import ForwardBuilder, Sender
from lemony_utils.help import Command, all_helps, find_help, register_help
from melobot import PluginInfo, PluginPlanner, get_bot
from melobot.handle import on_command
from melobot.protocols.onebot.v11 import Adapter, MessageEvent
from melobot.utils.parse import CmdArgs

from .render import overview_nodes, plugin_nodes

PLUGIN_IDENTIFIER = "helper"

logger = logging.getLogger(__name__)
bot = get_bot()
plugin = PluginPlanner("1.0.0", info=PluginInfo(desc="帮助信息"))

register_help(
    PLUGIN_IDENTIFIER,
    title="帮助",
    aliases=["help"],
    commands=[
        Command(".help", "列出所有功能"),
        Command(".help <名称>", "只看某一项, 名称可以是标题或标识, 如 .help 引用图"),
    ],
)


async def _bot_sender(adapter: Adapter) -> Sender:
    try:
        return await Sender.of_bot(adapter)
    except Exception:
        # 拿不到登录信息时仍然要能发帮助
        logger.warning("get_login_info 失败, 转发节点用默认名片", exc_info=True)
        return Sender(0, bot.name)


async def _send_nodes(adapter: Adapter, texts: list[str]) -> None:
    fwd = ForwardBuilder(await _bot_sender(adapter)).texts(texts)
    try:
        echo = await fwd.send(adapter)
    except Exception:
        logger.exception("帮助的合并转发发送失败, 改为普通消息")
        echo = None
    if echo is not None and echo.is_ok():
        return
    # 协议端不支持合并转发或发送失败时退回普通消息, 保证总能看到帮助
    await adapter.send_reply("\n\n".join(texts))


@plugin.use
@on_command(".", " ", ["help", "帮助"])
async def show_help(event: MessageEvent, adapter: Adapter, args: CmdArgs) -> None:
    name = " ".join(str(v) for v in args.vals).strip()
    if not name:
        await _send_nodes(adapter, overview_nodes(all_helps(), bot.name))
        return
    entry = find_help(name)
    if entry is None:
        await adapter.send_reply(f"没有找到 {name!r}, 发送 .help 查看全部")
        return
    await _send_nodes(adapter, plugin_nodes(entry))
