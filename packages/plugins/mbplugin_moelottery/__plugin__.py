import time

from lemony_checkers import get_checker_factory, require_permission
from lemony_checkers.adapters.register import registry
from lemony_settings import BaseSettings, require
from melobot import get_logger
from melobot.handle import on_command
from melobot.log import GenericLogger
from melobot.plugin import PluginPlanner
from melobot.protocols.onebot.v11.adapter import Adapter
from melobot.protocols.onebot.v11.adapter.event import GroupMessageEvent

from .lottery import LotteryBox

MoeLottery = PluginPlanner("1.0.0")

PLUGIN_IDENTIFIER = "moelottery"


class MoeLotConfig(BaseSettings):
    moedata_file: str | None = None
    group_isolation: bool = False  # 是否启用群隔离, 启用后每个群的抽取结果互不影响


cfgloader = require(
    model=MoeLotConfig,
    identifier=PLUGIN_IDENTIFIER,
)
logger = get_logger()
moelot = LotteryBox(cfgloader.value.moedata_file)
cd_table: dict[
    tuple[int, int], str
] = {}  # (user_id, group_id) -> date_str (精度为天), 用于冷却


@MoeLottery.use
@on_command(
    ".",
    " ",
    ["今日人设"],
)
@require_permission(PLUGIN_IDENTIFIER, "draw_attrs")
async def draw_attrs(event: GroupMessageEvent, adapter: Adapter, logger: GenericLogger):
    if not event.sender.user_id:
        # sender_id 为 None 是旧 QQ 的匿名用户, 现代 QQ 已经没有了
        # 但是我们亲爱的 OneBot11 协议仍然保留了这个特性, 以至于我们不得不在这里处理一下
        return  # 直接静默拒绝
    gid = event.group_id if cfgloader.value.group_isolation else 0
    uid = event.sender.user_id
    user = registry.extract_uniid_any(event)
    is_owner = user is not None and get_checker_factory().is_owner(user)
    if (
        cd_table.get((uid, gid))
        == (now_date := time.strftime("%Y-%m-%d", time.localtime()))
        and not is_owner
    ):
        await adapter.send_reply("今天已经抽过了噢")
        return
    cd_table[(uid, gid)] = now_date
    moeattr = moelot.lot()
    logger.debug(f"{moeattr=}")
    await adapter.send_reply(f"你今天的人设是{moelot.build_response_text(moeattr)}！")
