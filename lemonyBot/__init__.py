from .bot import Bot
from .objects import Plugin
from . import cqcode

import os

__all__ = ["Bot", "Plugin", "cqcode"]

ESSENTIAL_DIRS = ["./data", "./plugins", "./plugin_configs"]

for d in ESSENTIAL_DIRS:
    if not os.path.exists(d):
        os.mkdir(d)
