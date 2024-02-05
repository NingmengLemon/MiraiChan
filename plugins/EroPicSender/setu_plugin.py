from lemonyBot import Plugin, cqcode, Bot
from . import setuapi

from typing import Callable
import os
import copy
import atexit
import re
import base64
import time
import logging
import asyncio
import random

import yaml

request: Callable = None

img_save_path = "./data/setu_history/imgs/"
stat_file = "./data/setu_stat.yml"
stat = None
# {
#     "<group_id>": {"<QQ>": <counter>}
# }

DEFAULT_CONFIG = {
    "enable": {},  # "<group_id>": bool
    "cold_time": 8,  # in second
    "shielded_words": [],
}
config = None
config_file = "./plugin_configs/setu_config.yaml"
cold_down = {
    # QQ(int): Last Request Timestamp
}


def add_record(group_id, uid):
    global stat
    group_id = str(group_id)
    uid = str(uid)
    if group_id in stat:
        if uid in stat[group_id]:
            stat[group_id][uid] += 1
        else:
            stat[group_id][uid] = 1
    else:
        stat[group_id] = {}
        stat[group_id][uid] = 1


def load_all():
    global config
    global stat
    if os.path.exists(stat_file):
        stat = yaml.load(open(stat_file, "r", encoding="utf-8"), yaml.SafeLoader)
    else:
        stat = {}
    if os.path.exists(config_file):
        config = yaml.load(open(config_file, "r", encoding="utf-8"), yaml.SafeLoader)
    else:
        config = copy.deepcopy(DEFAULT_CONFIG)
        yaml.dump(
            DEFAULT_CONFIG,
            open(config_file, "w+", encoding="utf-8"),
            yaml.SafeDumper,
            default_flow_style=False,
            allow_unicode=True,
        )


@atexit.register
def save_all():
    yaml.dump(
        stat,
        open(stat_file, "w+", encoding="utf-8"),
        yaml.SafeDumper,
        default_flow_style=False,
        allow_unicode=True,
    )
    yaml.dump(
        config,
        open(config_file, "w+", encoding="utf-8"),
        yaml.SafeDumper,
        default_flow_style=False,
        allow_unicode=True,
    )


load_all()


class EroPicSender(Plugin):
    CALLER_REGEX = r"^(/?[搞发来整][点张份][涩色瑟]图|[涩色瑟]图[\s\,，]*来[\!！])\s*$"
    COMMAND_REGEX = r"^\/setu(\s+(on|off|help|status))?\s*$"

    def __init__(self, bot):
        super().__init__(bot)
        self.bot: Bot
        self.__inject()
        self.bot.add_task(self.init_cache())

    def __inject(self):
        global request
        request = setuapi.request = self.bot.request

    async def init_cache(self):
        logging.debug("check setu cache in 5s")
        await asyncio.sleep(5)
        logging.debug("checking setu cache...")
        await self.check_setuassets()
        logging.debug("checked setu cache ok")

    async def check_setuassets(self):
        try:
            if (count := len(setuapi.cache)) < 20:
                logging.debug("setu assets < 20 packs (%d packs), fetching..." % count)
                await setuapi.fetch()
            else:
                logging.debug("enough assets (%s packs)" % len(setuapi.cache))
        except Exception as e:
            logging.exception(e)

    def message_group_normal(self, event: dict):
        group_id: int = event["group_id"]
        if str(group_id) not in config["enable"]:
            config["enable"][str(group_id)] = False
        if re.findall(EroPicSender.CALLER_REGEX, event.get("message", "")):
            self.setu_trigger(event)
        elif params := re.findall(EroPicSender.COMMAND_REGEX, event.get("message", "")):
            command: str = params[0][1].lower().strip()
            if command:
                self.setu_configger(event, command)
            else:
                self.setu_trigger(event)

    def setu_trigger(self, event: dict):
        msg_id: int = event["message_id"]
        group_id: int = event["group_id"]
        sender: dict = event["sender"]
        uid: int = sender["user_id"]
        admins: list = self.bot.config.get("admins", [])
        # 统计
        add_record(group_id, uid)
        # 检查开关
        if not (config.get("enable", {}).get(str(group_id), False) or uid in admins):
            self.send_group_msg_func(
                {
                    "group_id": group_id,
                    "message": cqcode.reply(msg_id=msg_id)
                    + "本群的涩图模块已被管理员关闭 :(",
                    "auto_escape": False,
                }
            )
            return
        if uid in cold_down and uid not in admins:
            if (time_pass := (time.time() - cold_down.get(uid))) < config["cold_time"]:
                self.send_group_msg_func(
                    {
                        "group_id": group_id,
                        "message": cqcode.reply(msg_id=msg_id)
                        + "我知道你很急，但是你先别急。\n冷却时间还剩 %.2f 秒"
                        % (config["cold_time"] - time_pass),
                        "auto_escape": False,
                    }
                )
                return
        cold_down[uid] = time.time()
        self.bot.add_task(self.setu_sender(event))

    def setu_configger(self, event: dict, command: str):
        global config
        msg_id: int = event["message_id"]
        group_id: int = event["group_id"]
        sender: dict = event["sender"]
        if command in ["on", "off"]:
            # 鉴权
            if not (
                sender.get("user_id") in self.bot.config.get("admins", [])
                or sender.get("role") in ["admin", "owner"]
            ):
                self.send_group_msg_func(
                    {
                        "group_id": group_id,
                        "message": cqcode.reply(msg_id=msg_id) + "permission denied",
                        "auto_escape": False,
                    }
                )
                return
        status = config["enable"].get(str(group_id), False)
        success_reply = lambda s: self.send_group_msg_func(
            {
                "group_id": group_id,
                "message": cqcode.reply(msg_id=event["message_id"])
                + "涩图开关已设为 %s" % s,
                "auto_escape": False,
            }
        )
        skipp_reply = lambda s: self.send_group_msg_func(
            {
                "group_id": group_id,
                "message": cqcode.reply(msg_id=event["message_id"])
                + "涩图开关状态已经是 %s 了" % s,
                "auto_escape": False,
            }
        )
        send = lambda t: self.send_group_msg_func(
            {
                "group_id": group_id,
                "message": t,  # cqcode.reply(msg_id=event["message_id"]) + t,
                "auto_escape": False,
            }
        )
        match command:
            case "on" | "off":
                new_status = not status
                if status == {"on": True, "off": False}[command]:
                    skipp_reply(status)
                else:
                    config["enable"][str(group_id)] = new_status
                    success_reply(new_status)
            case "help":
                send(
                    """涩图模块帮助
直接发送 /setu 或 来点涩图 以获取涩图 (%d 秒冷却时间)
/setu on/off - 在本群开启/关闭涩图模块
/setu status - 查看统计与开关情况"""
                    % config["cold_time"]
                )
            case "status":
                self.bot.add_task(self.status_sender(event, status))
            case _:
                send(
                    cqcode.reply(msg_id=msg_id)
                    + "你可能不小心进入了一个不存在的页面..."
                )

    async def status_sender(self, event, status):
        msg_id: int = event["message_id"]
        group_id: int = event["group_id"]
        sender: dict = event["sender"]
        if str(group_id) in stat:
            stat_text = ["统计:"]
            for id, counter in stat[str(group_id)].items():
                stat_text += [
                    "%s(%s): %s 次"
                    % (
                        (
                            await self.get_group_member_info_async(
                                {"group_id": group_id, "user_id": id}
                            )
                        )
                        .get("data", {})
                        .get("user_displayname", "unknown"),
                        id,
                        counter,
                    )
                ]
            stat_text = "\n".join(stat_text)
        else:
            stat_text = "本群还没有统计信息"
        await self.send_group_msg_async(
            {
                "group_id": group_id,
                "message": "统计与开关\n本群开关状态: %s\n%s" % (status, stat_text),
                "auto_escape": False,
            }
        )

    async def setu_sender(self, event: dict):
        group_id: int = event["group_id"]
        reply = lambda t: self.send_group_msg_async(
            {
                "group_id": group_id,
                "message": cqcode.reply(msg_id=event["message_id"]) + t,
                "auto_escape": False,
            }
        )
        self.send_group_msg_func(
            {
                "group_id": group_id,
                "message": cqcode.reply(msg_id=event["message_id"])
                + random.choice(
                    [
                        "咱找找，稍等一下噢...",
                        "让咱找找...",
                        "少女翻找中...",
                        "在找了在找了...",
                    ]
                ),
                "auto_escape": False,
            }
        )
        url, text = setuapi.get_msg()
        text_lower = text.lower()
        if url:
            try:
                img_data = await self.bot.request(url, return_type="bytes")
                with open(os.path.join(img_save_path, url.split("/")[-1]), "wb+") as f:
                    f.write(img_data)
                # 主动过滤
                if sum(
                    [w.lower() in text_lower for w in config.get("shielded_words", [])]
                ):
                    await reply("涩图被咱吃掉叻!\n元数据如下: \n" + text)
                    return
                img_b64 = base64.b64encode(img_data).decode()
                result = await reply(
                    "%s\n%s" % (cqcode.image(file="base64://" + img_b64), text)
                )
                if result["retcode"] != 0:
                    await reply(
                        "涩图发送失败! \n服务器消息: "
                        + result.get("wording", "")
                        + result.get("data", {}).get("error", "")
                        + "\n元数据如下: \n"
                        + text
                    )
            except Exception as e:
                logging.exception(e)
                await reply("涩图在路上出了点状况: %s\n元数据如下: \n%s" % (e, text))
            finally:
                await self.check_setuassets()
        else:
            await reply(text)
            await self.check_setuassets()
