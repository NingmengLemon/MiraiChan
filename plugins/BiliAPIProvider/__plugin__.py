from melobot.bot import get_bot
from melobot.plugin import Plugin, SyncShare, AsyncShare
from .wbi import CachedWbiManager
from .utils import get_csrf
from .login import get_qrlogin_url, poll_qrlogin_status

import aiohttp

bot = get_bot()


class BiliApiProvider(Plugin):
    version = "0.1.0"
    author = "LemonyNingmeng"
    funcs = (CachedWbiManager, get_qrlogin_url, get_csrf, poll_qrlogin_status)
