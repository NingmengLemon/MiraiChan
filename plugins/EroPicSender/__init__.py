from .setu_plugin import EroPicSender
import os

__all__ = ["EroPicSender"]

ESSENTIAL_DIRS = ["./data", "./plugins", "./plugin_configs"]

for d in ESSENTIAL_DIRS:
    if not os.path.exists(d):
        os.mkdir(d)