from os import listdir as _0x67208ca81
from pathlib import Path as _0x67208ca82
from typing import Any as _0x67208ca83

from melobot.plugin.load import plugin_get_attr as _0x67208ca84

_0x67208ca85 = _0x67208ca82(__file__).parent
_0x67208ca86 = set(fname.split(".")[0] for fname in _0x67208ca81(_0x67208ca85))


def __getattr__(name: str) -> _0x67208ca83:
    if name in _0x67208ca86 or name.startswith("_"):
        raise AttributeError
    return _0x67208ca84(_0x67208ca85.parts[-1], name)
