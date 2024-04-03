import json
import qrcode
import logging

import aiohttp

from typing import Callable

request: Callable = None
session: aiohttp.ClientSession = None


async def start_login():
    api = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
    data = await request(api, mod="get", return_type="dict")
    assert data["code"] == 0, data.get("message")
    data = data["data"]
    loginurl = data["url"]
    oauthkey = data["qrcode_key"]
    return loginurl, oauthkey


async def check_login(oauthkey):
    api = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
    api += "?qrcode_key=%s" % oauthkey
    # 无所谓, aiohttp 的自动 cookie 处理会出手
    logging.debug("Checking scanning status...")
    data = await request(api, mod="get", return_type="dict")
    assert data["code"] == 0, data.get("message")
    data = data["data"]
    # -1：密钥错误 -2：密钥超时 -4：未扫描 -5：未确认
    status = data["code"]
    if status == 0:
        logging.info("QR login succeeded")
        return True, data["url"], 0  # 成功与否, 跨域URL, 状态码
    else:
        # 将返回的状态码转换为以前的
        logging.debug("Login server msg: " + data["message"])
        return False, None, {0: 0, 86038: -2, 86090: -5, 86101: -4}[status]


def get_csrf(aiosession: aiohttp.ClientSession):
    for cookie in aiosession.cookie_jar:
        if cookie.key == "bili_jct":
            return cookie.value
    return None


async def exit_login():
    csrf = get_csrf(session)
    if csrf:
        data = await request(
            "https://passport.bilibili.com/login/exit/v2",
            mod="post",
            data={"biliCSRF": csrf},
            return_type="str",
        )
        assert "请先登录" not in data, "Haven't Logined Yet."
        data = json.loads(data)
        assert data["code"] == 0, data.get("message")
        logging.info("Logout succeeded")
    else:
        raise AssertionError("Haven't Logined Yet.")


async def get_login_info():
    """
    需要登录

    获取当前登录的用户的信息
    """
    api = "https://api.bilibili.com/x/web-interface/nav"
    data = await request(api, mod="get", return_type="dict")
    assert data["code"] == 0, data["message"]
    data = data["data"]
    res = {
        "uid": data["mid"],
        "name": data["uname"],
        "vip_type": {0: "非大会员", 1: "月度大会员", 2: "年度及以上大会员"}[
            data["vipType"]
        ],
        "coin": data["money"],
        "level": data["level_info"]["current_level"],
        "exp": data["level_info"]["current_exp"],
        "moral": data["moral"],  # max=70
        "face": data["face"],
    }
    return res
