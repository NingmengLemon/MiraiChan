from lemonyBot import Bot, Plugin, cqcode
from . import bilicodes, bilidynamic, wbi

from typing import Callable, Union, Any
import os
import json
import copy
import atexit
import logging
import time
import asyncio
import re

import yaml

# 等待注入
request = None
download_multi = None

config: dict = None
config_file = "./plugin_configs/bilidynforw.json"
ConfigDict = dict[str, dict[str, list[str]]]
DEFAULT_CONFIG = {
    # "<group_id>": {       // Notice: keys are all strings
    #     "targets": [
    #         "<bili_uid>"
    #     ],
    #     "whitewords":[],
    #     "blackwords":[]
    # }
}
CONFIG_TEMPLATE = {"targets": [], "whitewords": [], "blackwords": []}
listen_sleep = 5 * 60

nickname_map: dict = {
    # "<bili_uid>": "<nickname>"
}
nickname_map_file = "./data/biliuser_nickname_map.json"

dynamic_cache: dict[str, list] = {}

timestamp_to_time = lambda ts: time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


def _check_uid(bili_uid):
    if isinstance(bili_uid, (int, str)):
        bili_uid = [str(int(bili_uid))]
    elif isinstance(bili_uid, (list, tuple, set)):
        bili_uid = [str(int(i)) for i in bili_uid]
    else:
        raise ValueError("unsupported uid type: %s" % type(bili_uid))
    return bili_uid


def _check_words(words):
    if not words:
        return []
    if isinstance(words, (list, tuple, set)):
        words = [str(word).lower() for word in words]
    else:
        words = [str(words).lower()]
    return words


def add_target(bili_uid, group_id):
    global config
    bili_uid = _check_uid(bili_uid)
    group_id = str(int(group_id))
    if group_id not in config:
        config[group_id] = copy.deepcopy(CONFIG_TEMPLATE)
    config[group_id]["targets"] += bili_uid
    dump_config()


def remove_target(bili_uid, group_id):
    """
    returns:
    (list) - contains not-found uids
    """
    global config
    bili_uid: list = _check_uid(bili_uid)
    group_id: str = str(int(group_id))
    if group_id not in config:
        return 1
    not_found = []
    for uid in bili_uid:
        if uid in config[group_id]["targets"]:
            config[group_id]["targets"].remove(uid)
        else:
            not_found += [uid]
    dump_config()
    return not_found


def add_words(group_id, black=None, white=None):
    global config
    group_id: str = str(int(group_id))
    black: list = _check_words(black)
    white: list = _check_words(white)
    if group_id not in config:
        config[group_id] = copy.deepcopy(CONFIG_TEMPLATE)
    config[group_id]["whitewords"] += [
        w for w in white if w not in config[group_id]["whitewords"]
    ]
    config[group_id]["blackwords"] += [
        w for w in black if w not in config[group_id]["blackwords"]
    ]
    dump_config()


def remove_words(group_id, black=None, white=None):
    global config
    group_id: str = str(int(group_id))
    black: list = _check_words(black)
    white: list = _check_words(white)
    if group_id not in config:
        return
    for word in [w for w in black if w in config[group_id]["blackwords"]]:
        config[group_id]["blackwords"].remove(word)
    for word in [w for w in white if w in config[group_id]["whitewords"]]:
        config[group_id]["whitewords"].remove(word)
    dump_config()


def dump_config(override_with_default: bool = False):
    with open(config_file, "w+", encoding="utf-8") as f:
        if override_with_default:
            json.dump(DEFAULT_CONFIG, f, indent=4)
        elif config:
            json.dump(config, f, indent=4)
        else:
            json.dump({}, f, indent=4)


def load_config():
    global config
    if os.path.exists(config_file):
        config = json.load(open(config_file, "r", encoding="utf-8"))
    else:
        config = copy.deepcopy(DEFAULT_CONFIG)
        dump_config(True)


load_config()


def load_nickname_map():
    global nickname_map
    if os.path.exists(nickname_map_file):
        nickname_map = json.load(open(nickname_map_file, "r", encoding="utf-8"))


@atexit.register
def save_nickname_map():
    json.dump(nickname_map, open(nickname_map_file, "w+", encoding="utf-8"))


load_nickname_map()


async def query_nickname(uid):
    global nickname_map
    uid = str(uid)
    if uid in nickname_map:
        nickname = nickname_map[uid]
    else:
        nickname = (await bilidynamic.get_user_info(uid))["name"]
        nickname_map[uid] = nickname
        logging.debug(f"Uid{uid} not in cache, queried")
    return nickname


def query_nickname_nowait(uid):
    global nickname_map
    uid = str(uid)
    if uid in nickname_map:
        return nickname_map[uid]
    else:
        return None


async def generate_msg(data):
    card = data["card"]
    dtype = card["type"]
    # 正文
    msg = (
        "由Mirai酱带来的新的动态消息！\n发布者："
        + data["user"]["uname"]
        + """
时间：{pt}
地址：https://t.bilibili.com/{did}
{cnt}
""".format(
            pt=timestamp_to_time(data["timestamp"]),
            did=data["dynamic_id"],
            cnt=card["content"],
        )
    )
    # 图片
    if card["images"]:
        images: dict = await download_multi(*card["images"], return_type="base64")
        for url, b64 in images.items():
            # msg += cqcode.image(url.split("/")[-1], url="base64://"+b64)
            msg += cqcode.image("base64://" + b64)
    # 附加内容
    match dtype:
        case "forward":
            if not card["origin"]["user"]:
                msg += """
此动态为转发动态 原动态已被删除"""
            else:
                msg += """
此动态为转发动态
原动态：https://t.bilibili.com/{dynamic_id}
发布者：{user[uname]}
{card[content]}""".format(
                    **card["origin"]
                )
        case "video":
            msg += """
包含视频：https://www.bilibili.com/video/av{avid}
《{title}》（{length}秒）""".format(
                **card["video"]
            )
        case "article":
            msg += """
包含专栏：https://www.bilibili.com/read/cv{cvid}
《{title}》（{words}字）""".format(
                **card["article"]
            )
        case "audio":
            msg += """
包含音频：https://www.bilibili.com/audio/au{auid}
{author} - 《{title}》""".format(
                **card["audio"]
            )
        case _:
            pass
    return msg


class BiliDynamicForwarder(Plugin):
    REGEX_KWLIST = (
        r"^\/bilidynamicforwarder\s+kwlist\s+(white|black)\s+(add|remove)\s+(.+?)\s*$"
    )
    REGEX_TARGET = r"^\/bilidynamicforwarder\s+target\s+(add|remove)\s+(\d+)\s*$"
    REGEX_SHOW = r"^\/bilidynamicforwarder\s+show\s*$"
    REGEX_HELP = r"^\/bilidynamicforwarder\s+help\s*$"

    def __init__(self, bot: Bot):
        super().__init__(bot)
        self.bot: Bot
        self.__inject()
        self.bot.add_task(self.process())

    def __inject(self):
        # 依 赖 注 入
        global request
        global download_multi
        request = bilidynamic.request = wbi.request = self.bot.request
        download_multi = self.bot.download_multi

    async def process(self):
        logging.info("initialize dynamic list in 2s")
        await asyncio.sleep(2)
        await self.check_dynamic_update()
        await asyncio.sleep(listen_sleep)
        while True:
            send_list = await self.check_dynamic_update()
            self.send_msgs(send_list)
            await asyncio.sleep(listen_sleep)

    async def scan_dynamics(self) -> dict[str, list]:
        dynamic_cache_new = {}
        config_copy: ConfigDict = copy.deepcopy(config)
        for group_id, rules in config_copy.items():
            for target in rules.get("targets"):
                try:
                    data = (
                        dynamic_cache_new.get(target)
                        if target in dynamic_cache_new
                        else await bilidynamic.get_recent(int(target))
                    )
                except Exception as e:
                    logging.exception(e)
                else:
                    nickname_map[target] = data[0]["user"]["uname"]
                    logging.info("uid <%s> pulled, <%d> items" % (target, len(data)))
                    dynamic_cache_new[target] = data
        return dynamic_cache_new

    async def check_dynamic_update(self) -> dict[str, list[dict[str, Any]]]:
        global dynamic_cache
        logging.info("start to pull dynamic lists")
        try:
            cache_new = await self.scan_dynamics()
            cache = dynamic_cache
            need_to_be_sent = {}
            logging.info("dynamic lists pulled")
            for uid, new in cache_new.items():
                if uid not in cache:
                    continue
                old = cache[uid]
                if not new:
                    continue
                # 比对最新一条动态
                if new[0]["timestamp"] == old[0]["timestamp"]:
                    continue
                elif new[0]["timestamp"] < old[0]["timestamp"]:
                    # 可能有动态删除
                    if new[0]["card"]["type"] == "video":
                        # 可能存在的视频修改行为
                        if new[0]["dynamic_id"] == old[0]["dynamic_id"]:
                            # 进一步比对动态id
                            continue
                    logging.debug(f"dynamic deletion of uid{uid} detected")
                    continue
                else:
                    old_newest_time = old[0]["timestamp"]
                    # 向后寻找可能漏掉的动态
                    for offset in range(1, len(new)):  # 从1开始是因为0已经检查过了
                        if (
                            new[offset]["timestamp"] <= old_newest_time
                            or new[offset]["timestamp"] <= time.time() - 60 * 60 * 1
                        ):  # 备用, 阻止过于久远的动态被发出
                            break
                    need_to_be_sent[uid] = new[:offset]
        except Exception as e:
            logging.exception(e)
            return None
        else:
            dynamic_cache = cache_new
            return need_to_be_sent

    def send_msgs(self, msg_list: dict[str, list[dict[str, Any]]]):
        config_copy = copy.deepcopy(config)
        for group_id, rules in config_copy.items():
            targets = rules["targets"]
            for uid in targets:
                if uid not in msg_list:
                    continue
                for msg in msg_list[uid]:
                    self.bot.add_task(self.send_msg(group_id=group_id, msg=msg))
                    logging.info(
                        "start to forward dynamic of %s(%s) to %s"
                        % (uid, query_nickname_nowait(uid), group_id)
                    )

    async def send_msg(self, group_id, msg: dict):
        # 过滤消息
        content_ck = (
            msg["card"].get("content", "")
            + msg.get("origin", {}).get("card", {}).get("content", "")
        ).lower()
        flag = True
        if sum(
            [
                b.lower() in content_ck
                for b in config.get(group_id, {}).get("blackwords", [])
            ]
        ):
            flag = False
        if sum(
            [
                w.lower() in content_ck
                for w in config.get(group_id, {}).get("whitewords", [])
            ]
        ):
            flag = True
        if not flag:
            logging.info("filtered a dynamic of uid{uid}({name})".format(**msg["user"]))
            return
        # 正式发送
        msg = await generate_msg(msg)
        data = {"group_id": group_id, "message": msg, "auto_escape": False}
        rv = await self.send_group_msg_async(data)
        # 检查被 tx 拦截的情况
        if rv["retcode"] != 0:
            logging.error("failed to send, server msg: " + str(rv))
            # 移除图片
            msg = re.sub(r"\[CQ\:image.+?\]", "", msg)
            # 重新发送
            data["message"] = msg
            self.send_group_msg_func(data)

    # 重写的事件监听方法
    def message_group_normal(self, event: dict):
        msg: str = event["message"]
        msg_id: int = event["message_id"]
        group_id: int = event["group_id"]
        sender: dict = event["sender"]

        # 判定指令
        if not msg.lower().startswith("/bilidynamicforwarder"):
            return
        # 鉴权
        if sender.get("user_id") in self.bot.config.get("admins", []) or sender.get(
            "role"
        ) in ["admin", "owner"]:
            self.parse_command(event)
        else:
            self.send_group_msg_func(
                {
                    "group_id": group_id,
                    "message": cqcode.reply(msg_id=msg_id) + "permission denied",
                    "auto_escape": False,
                }
            )

    def parse_command(self, event: dict):
        command: str = event["message"]
        group_id: int = event["group_id"]
        # 确定指令分支
        if params := re.findall(BiliDynamicForwarder.REGEX_KWLIST, command, re.I):
            wb_type, oper, word = params[0]
            ({"add": add_words, "remove": remove_words}[oper])(
                group_id, **{wb_type: word}
            )
            self.send_group_msg_func(
                {
                    "group_id": group_id,
                    "message": cqcode.reply(msg_id=event["message_id"]) + "success",
                    "auto_escape": False,
                }
            )

        elif params := re.findall(BiliDynamicForwarder.REGEX_TARGET, command, re.I):
            oper, uid = params[0]
            {"add": add_target, "remove": remove_target}[oper](uid, group_id)
            self.send_group_msg_func(
                {
                    "group_id": group_id,
                    "message": cqcode.reply(msg_id=event["message_id"]) + "success",
                    "auto_escape": False,
                }
            )
        elif re.findall(BiliDynamicForwarder.REGEX_SHOW, command, re.I):
            self.send_group_msg_func(
                {
                    "group_id": group_id,
                    "message": cqcode.reply(msg_id=event["message_id"])
                    + "本群当前的配置如下: \n%s\nUID 对照表: \n%s"
                    % (
                        yaml.dump(
                            config.get(str(group_id)),
                            default_flow_style=False,
                            allow_unicode=True,
                        ),
                        yaml.dump(
                            {
                                k: v
                                for k, v in nickname_map.items()
                                if k in config.get(str(group_id), {}).get("targets", [])
                            },
                            default_flow_style=False,
                            allow_unicode=True,
                        ),
                    ),
                    "auto_escape": False,
                }
            )
        elif re.findall(BiliDynamicForwarder.REGEX_HELP, command, re.I):
            self.send_group_msg_func(
                {
                    "group_id": group_id,
                    "message": cqcode.reply(msg_id=event["message_id"])
                    + """帮助信息:
/bilidynamicforwarder target add/remove (B站用户uid) - 增/减监听的用户
/bilidynamicforwarder kwlist white/black add/remove (关键词) - 增/减 黑/白关键词
/bilidynamicforwarder show - 展示本群当前的配置
(包含白关键词的消息会被保留, 优先级>黑关键词)""",
                    "auto_escape": False,
                }
            )
        else:
            self.send_group_msg_func(
                {
                    "group_id": group_id,
                    "message": cqcode.reply(msg_id=event["message_id"])
                    + "no matched command branch",
                    "auto_escape": False,
                }
            )
