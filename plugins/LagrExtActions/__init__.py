from os import listdir as _0x67209e791
from pathlib import Path as _0x67209e792
from typing import Any as _0x67209e793

from melobot.plugin.load import plugin_get_attr as _0x67209e794

_0x67209e795 = _0x67209e792(__file__).parent
_0x67209e796 = set(fname.split(".")[0] for fname in _0x67209e791(_0x67209e795))


def __getattr__(name: str) -> _0x67209e793:
    if name in _0x67209e796 or name.startswith("_"):
        raise AttributeError
    return _0x67209e794(_0x67209e795.parts[-1], name)
