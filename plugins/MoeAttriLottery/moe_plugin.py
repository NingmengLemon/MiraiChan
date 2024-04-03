from lemonyBot import Bot, Plugin, cqcode
from . import extractor

import traceback
import json
import time
import logging
import re
import os
import copy
import atexit
import asyncio

# import yaml

cache = {}
# qq_number: data_pack(from extractor.generator)
config = None
config_file = "./plugin_configs/moeattrdraw.json"
DEFAULT_CONFIG = {
    "enable": {}  # "<group_id>": bool
    #
}
stat = {
    # "<uid>": {"<keyword>": counter} # _total
    "total": 0
}
stat_file = "./data/moedraw_stat.json"


def load_all():
    global config
    global stat
    if os.path.exists(config_file):
        config = json.load(open(config_file, "r", encoding="utf-8"))
    else:
        config = copy.deepcopy(DEFAULT_CONFIG)
        json.dump(config, open(config_file, "w+", encoding="utf-8"), indent=4)
    if os.path.exists(stat_file):
        stat = json.load(open(stat_file, "r", encoding="utf-8"))
    else:
        json.dump(stat, open(stat_file, "w+", encoding="utf-8"), indent=4)


load_all()


def record_stat(uid, data: dict):
    global stat
    uid = str(uid)
    stat["total"] += 1
    if uid not in stat:
        stat[uid] = {}
        stat[uid]["_total"] = 0
    stat[uid]["_total"] += 1
    for cate, keyw in data.items():
        if keyw in stat[uid]:
            stat[uid][keyw] += 1
        else:
            stat[uid][keyw] = 1
    stat[uid].pop("普通", None)
    stat[uid].pop("/", None)
    stat[uid].pop("无", None)


def get_stat(uid):
    uid = str(uid)
    return stat.get(uid, {})


def get_stat_most(uid):
    data: dict = copy.deepcopy(get_stat(uid))
    total = data.pop("_total", 0)
    most = []
    if not data:
        return most, total
    max_value = max(data.values())
    for k, v in data.items():
        if v == max_value:
            most += [k]
    return most, total


@atexit.register
def save_all():
    json.dump(
        stat, open(stat_file, "w+", encoding="utf-8"), indent=4, ensure_ascii=False
    )
    json.dump(
        config, open(config_file, "w+", encoding="utf-8"), indent=4, ensure_ascii=False
    )


class MoeAttriLottery(Plugin):
    DRAW_REGEX = r"^(\/draw|抽签)\s*$"
    COMMAND_REGEX = r"^\/draw\s+(reload|help|on|off|stati|state)\s*$"

    def __init__(self, bot):
        super().__init__(bot)
        self.bot: Bot
        self.bot.add_task(self.init_moefile())

    async def init_moefile(self):
        logging.info("load moe attr file in 2s")
        await asyncio.sleep(2)
        extractor.load_attrs()

    def message_group_normal(self, event: dict):
        msg: str = event.get("message")
        if re.findall(MoeAttriLottery.DRAW_REGEX, msg, re.I):
            self.draw_lot(event=event)
        elif params := re.findall(MoeAttriLottery.COMMAND_REGEX, msg, re.I):
            command = params[0].lower()
            self.parse_command(event, command)
        elif msg.lower().startswith("/draw "):
            self.send_group_msg_func(
                {
                    "group_id": event["group_id"],
                    "message": "unknown command branch",
                    "auto_escape": False,
                }
            )

    def parse_command(self, event: dict, command: str):
        admins: list = self.bot.config.get("admins", [])
        msg_id: int = event["message_id"]
        sender: dict = event["sender"]
        uid: int = sender["user_id"]
        group_id: int = event["group_id"]
        if str(group_id) not in config["enable"]:
            config["enable"][str(group_id)] = False
        match command:
            case "reload":
                if uid in admins:
                    self.reload_moefile(event=event)
                else:
                    self.send_group_msg_func(
                        {
                            "group_id": group_id,
                            "message": cqcode.reply(msg_id=msg_id) + "permisson denied",
                            "auto_escape": False,
                        }
                    )
            case "help":
                self.send_group_msg_func(
                    {
                        "group_id": group_id,
                        "message": """抽签帮助
直接发送 /draw 或 抽签 以抽取当日的萌属性
/draw reload - 重新加载萌属性文件
/draw help - 显示此条信息
/draw on/off - 在本群开启/关闭此模块
/draw state - 查看模块开关状态
/draw stati - 查看自己的抽签统计""",
                        "auto_escape": False,
                    }
                )
            case "on" | "off":
                new_status = {"on": True, "off": False}[command]
                if uid in admins:
                    if new_status == config["enable"].get(str(group_id), False):
                        self.send_group_msg_func(
                            {
                                "group_id": group_id,
                                "message": cqcode.reply(msg_id=msg_id)
                                + "抽签开关状态已经是 %s 了" % new_status,
                                "auto_escape": False,
                            }
                        )
                    else:
                        config["enable"][str(group_id)] = new_status
                        self.send_group_msg_func(
                            {
                                "group_id": group_id,
                                "message": cqcode.reply(msg_id=msg_id)
                                + "抽签开关已设为 %s" % new_status,
                                "auto_escape": False,
                            }
                        )
                else:
                    self.send_group_msg_func(
                        {
                            "group_id": group_id,
                            "message": cqcode.reply(msg_id=msg_id) + "permisson denied",
                            "auto_escape": False,
                        }
                    )
            case "state":
                self.send_group_msg_func(
                    {
                        "group_id": group_id,
                        "message": "模块开关: %s\n已累计抽取 %d 次"
                        % (
                            config["enable"].get(str(group_id), False),
                            stat.get("total", 0),
                        ),
                        "auto_escape": False,
                    }
                )
            case "stati":
                most, total = get_stat_most(uid)
                self.send_group_msg_func(
                    {
                        "group_id": group_id,
                        "message": cqcode.reply(msg_id=msg_id)
                        + "你抽到最多的词条是: %s\n你已累计抽取 %d 次"
                        % (", ".join(most), total),
                        "auto_escape": False,
                    }
                )
            case _:
                self.send_group_msg_func(
                    {
                        "group_id": group_id,
                        "message": cqcode.reply(msg_id=msg_id) + "unknown sub command",
                        "auto_escape": False,
                    }
                )

    def reload_moefile(self, event: dict):
        msg_id: int = event["message_id"]
        group_id: int = event["group_id"]
        try:
            extractor.load_attrs()
        except Exception as e:
            self.send_group_msg_func(
                {
                    "group_id": group_id,
                    "message": cqcode.reply(msg_id=msg_id)
                    + "数据文件重载失败: "
                    + str(e),
                    "auto_escape": False,
                }
            )
            logging.exception(e)
        else:
            self.send_group_msg_func(
                {
                    "group_id": group_id,
                    "message": cqcode.reply(msg_id=msg_id) + "数据文件已重载",
                    "auto_escape": False,
                }
            )

    def draw_lot(self, event: dict):
        global cache
        msg_id: int = event["message_id"]
        group_id: int = event["group_id"]
        sender: dict = event["sender"]
        uid: int = sender["user_id"]
        admins: list = self.bot.config.get("admins", [])
        if not (uid in admins or config["enable"].get(str(group_id), False)):
            self.send_group_msg_func(
                {
                    "group_id": group_id,
                    "message": cqcode.reply(msg_id=msg_id)
                    + "本群的抽签模块已被管理员关闭 :(",
                    "auto_escape": False,
                }
            )
            return
        if uid in cache:
            last_draw_date = time.strftime(
                "%Y-%m-%d", time.localtime(cache[uid]["time"])
            )
            if (
                last_draw_date == time.strftime("%Y-%m-%d", time.localtime())
                and uid not in admins
            ):
                self.send_group_msg_func(
                    {
                        "group_id": group_id,
                        "message": cqcode.reply(msg_id=msg_id) + "您今天已经抽过签了噢",
                        "auto_escape": False,
                    }
                )
                return
        data = extractor.generate()
        cache[uid] = data.copy()
        draw_time = data.pop("time")
        record_stat(uid, data)
        self.send_group_msg_func(
            {
                "group_id": group_id,
                "message": cqcode.reply(msg_id=msg_id)
                + "您今天的设定如下(๑´ڡ`๑)\n"
                + "\n".join([f"{i}：{o}" for i, o in data.items()])
                + "\n生成时间："
                + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(draw_time)),
                "auto_escape": False,
            }
        )
