from lemonyBot import Plugin, cqcode, Bot, utils
from . import login

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
import json
import io

import yaml
import qrcode
from PIL import Image

request: Callable = None


class BiliLogin(Plugin):
    def __init__(self, bot):
        super().__init__(bot)
        self.bot: Bot
        self.__inject()
        self.bot.add_task(request("https://www.bilibili.com/", mod="get"))

    def __inject(self):
        global request
        request = login.request = self.bot.request
        login.session = self.bot.aiosession

    def message_private_friend(self, event: dict):
        uid = event["sender"]["user_id"]
        admins: list = self.bot.config.get("admins", [])
        if uid not in admins:
            return
        self.bot.add_task(self.major_function(event))

    async def major_function(self, event):
        uid = event["sender"]["user_id"]
        msg = event["message"].lower().strip()
        match msg:
            case "check login":
                echo = ""
                try:
                    echo = json.dumps(
                        await login.get_login_info(), indent=4, ensure_ascii=False
                    )
                except Exception as e:
                    echo = str(e)
                self.send_private_msg_func(
                    {
                        "user_id": uid,
                        "message": echo,
                        "auto_escape": False,
                    }
                )
            case "start login":
                try:
                    echo = await login.get_login_info()
                except AssertionError as e:
                    logging.debug(str(e))
                    await self.login_action(uid)
                else:
                    self.send_private_msg_func(
                        {
                            "user_id": uid,
                            "message": "already logged in:\n"
                            + json.dumps(echo, indent=4, ensure_ascii=False),
                            "auto_escape": False,
                        }
                    )
            case "exit login":
                try:
                    await login.exit_login()
                except AssertionError as e:
                    echo = str(e)
                else:
                    echo = "ok"
                self.send_private_msg_func(
                    {
                        "user_id": uid,
                        "message": echo,
                        "auto_escape": False,
                    }
                )

    async def login_action(self, echo_uid: int):
        try:
            url, key = await login.start_login()
        except Exception as e:
            self.send_private_msg_func(
                {
                    "user_id": echo_uid,
                    "message": str(e),
                    "auto_escape": False,
                }
            )
            return
        img = utils.make_qrcode(url)
        imgb64 = base64.b64encode(img).decode()
        await self.send_private_msg_async(
            {
                "user_id": echo_uid,
                "message": cqcode.image(file="base64://" + imgb64)
                + "scan this to login",
                "auto_escape": False,
            }
        )
        while True:
            await asyncio.sleep(2)
            succ, _, code = await login.check_login(key)
            if succ or code in [-1, -2]:
                break
        if succ:
            self.send_private_msg_func(
                {
                    "user_id": echo_uid,
                    "message": "success",
                    "auto_escape": False,
                }
            )
            self.send_private_msg_func(
                {
                    "user_id": echo_uid,
                    "message": json.dumps(
                        await login.get_login_info(), indent=4, ensure_ascii=False
                    ),
                    "auto_escape": False,
                }
            )
            await self.bot.request("https://www.bilibili.com/", mod="get")
        elif code == -1:
            self.send_private_msg_func(
                {
                    "user_id": echo_uid,
                    "message": "oauthkey error",
                    "auto_escape": False,
                }
            )
        elif code == -2:
            self.send_private_msg_func(
                {
                    "user_id": echo_uid,
                    "message": "oauthkey timeout",
                    "auto_escape": False,
                }
            )
