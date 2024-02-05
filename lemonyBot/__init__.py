from .bot import Bot
from .objects import Plugin
from . import cqcode

import os

__all__ = ["Bot", "Plugin", "cqcode"]

ESSENTIAL_DIRS = [
    "./data/setu_history/datapacks/",
    "./data/setu_history/imgs/",
]

for d in ESSENTIAL_DIRS:
    if not os.path.exists(d):
        os.makedirs(d, exist_ok=True)
