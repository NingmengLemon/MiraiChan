from os import listdir as _0x672135661
from pathlib import Path as _0x672135662
from typing import Any as _0x672135663

from melobot.plugin.load import plugin_get_attr as _0x672135664

_0x672135665 = _0x672135662(__file__).parent
_0x672135666 = set(fname.split(".")[0] for fname in _0x672135661(_0x672135665))


def __getattr__(name: str) -> _0x672135663:
    if name in _0x672135666 or name.startswith("_"):
        raise AttributeError
    return _0x672135664(_0x672135665.parts[-1], name)
