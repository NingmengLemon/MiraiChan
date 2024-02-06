from .setu_plugin import EroPicSender
import os

__all__ = ["EroPicSender"]

ESSENTIAL_DIRS = [
    "./data/setu_history/datapacks/",
    "./data/setu_history/imgs/",
]

for d in ESSENTIAL_DIRS:
    if not os.path.exists(d):
        os.makedirs(d, exist_ok=True)