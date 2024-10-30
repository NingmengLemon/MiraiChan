from aiohttp import ClientSession
from http import cookiejar
import time

from lemony_utils.templates import async_reqtemplate


@async_reqtemplate()
async def get_qrlogin_url():
    return {
        "url": "https://passport.bilibili.com/x/passport-login/web/qrcode/generate",
        "method": "get",
    }


@async_reqtemplate()
async def poll_qrlogin_status(qrcode_key: str):
    return {
        "url": "https://passport.bilibili.com/x/passport-login/web/qrcode/poll",
        "method": "get",
        "params": {"qrcode_key": qrcode_key},
    }


def cookiejar_from_crossdomain_url(url: str):
    """URL 来自轮询登录成功后返回的数据"""
    tmpjar = cookiejar.MozillaCookieJar()
    data = url.split("?")[-1].split("&")[:-1]
    for domain in (".bilibili.com", ".bigfun.cn", ".bigfunapp.cn", ".biligame.com"):
        for item in data:
            i = item.split("=", 1)
            # fmt: off
            tmpjar.set_cookie(
                cookiejar.Cookie(
                    0, i[0], i[1], None, False,
                    domain, True, domain.startswith('.'),
                    '/', False, False,
                    int(time.time()) + (6 * 30 * 24 * 60 * 60),
                    False, None, None, {}
                    )
                )
            # fmt: on
    return tmpjar
