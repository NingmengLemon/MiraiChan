from aiohttp import ClientSession


def get_csrf(session: ClientSession):
    """从 session 获得很多 api 需要的 csrf"""
    for ck in session.cookie_jar:
        if ck.key == "bili_jct":
            return ck.value
