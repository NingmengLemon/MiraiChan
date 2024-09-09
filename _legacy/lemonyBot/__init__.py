from .bot import Bot
from .objects import Plugin
from . import cqcode
from .base import HttpBase, SocketBase

import os

__all__ = ["Bot", "Plugin", "cqcode", "HttpBase", "SocketBase"]

ESSENTIAL_DIRS = ["./data", "./plugins", "./plugin_configs"]

for d in ESSENTIAL_DIRS:
    if not os.path.exists(d):
        os.mkdir(d)