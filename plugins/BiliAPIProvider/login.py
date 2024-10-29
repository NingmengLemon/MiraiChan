from aiohttp import ClientSession

from ..LemonyUtils import async_reqtemplate


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
