from os import listdir as _0x671fd5741
from pathlib import Path as _0x671fd5742
from typing import Any as _0x671fd5743

from melobot.plugin.load import plugin_get_attr as _0x671fd5744

_0x671fd5745 = _0x671fd5742(__file__).parent
_0x671fd5746 = set(fname.split(".")[0] for fname in _0x671fd5741(_0x671fd5745))


def __getattr__(name: str) -> _0x671fd5743:
    if name in _0x671fd5746 or name.startswith("_"):
        raise AttributeError
    return _0x671fd5744(_0x671fd5745.parts[-1], name)
