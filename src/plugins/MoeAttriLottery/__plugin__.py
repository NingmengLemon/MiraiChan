import os
import time

from pydantic import BaseModel

from melobot import get_logger
from melobot.plugin import PluginPlanner
from melobot.log import GenericLogger
from melobot.protocols.onebot.v11.handle import on_command
from melobot.protocols.onebot.v11.adapter import Adapter
from melobot.protocols.onebot.v11.adapter.event import GroupMessageEvent

from configloader import ConfigLoader, ConfigLoaderMetadata
import checker_factory
import little_helper

from .lottery import MoeLot

MoeLottery = PluginPlanner("0.1.0")
little_helper.register(
    "MoeLottery",
    {
        "cmd": ".今日人设",
        "text": "抽取今日人设\n标签来源：萌娘百科",
    },
)


class QuoteConfig(BaseModel):
    moedata_file: str = "data/moe_attrs.json"


os.makedirs("data/fonts", exist_ok=True)
cfgloader = ConfigLoader(
    ConfigLoaderMetadata(model=QuoteConfig, filename="moelottery_conf.json")
)
cfgloader.load_config()
logger = get_logger()
moelot = MoeLot(cfgloader.config.moedata_file)
cd_table: dict[int, str] = {}


@MoeLottery.use
@on_command(".", " ", ["今日人设", "萌抽签"])
async def draw_attrs(event: GroupMessageEvent, adapter: Adapter, logger: GenericLogger):
    if (
        cd_table.get(event.sender.user_id, "")
        == (now_date := time.strftime("%Y-%m-%d", time.localtime()))
        and event.sender.user_id != checker_factory.OWNER
    ):
        await adapter.send_reply("今天已经抽过了噢")
        return
    cd_table[event.sender.user_id] = now_date
    moeattr = moelot.draw()
    logger.debug(f"{moeattr=}")
    await adapter.send_reply(f"你今天的人设是{moelot.to_text(moeattr)}！")
