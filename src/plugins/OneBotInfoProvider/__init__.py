# This file is @generated by melobot cli.
# It is not intended for manual editing.
from os import listdir as _0x676011da1
from pathlib import Path as _0x676011da2
from typing import Any as _0x676011da3

from melobot import get_bot as _0x676011da4

_0x676011da5 = _0x676011da2(__file__).parent
_0x676011da6 = set(fname.split(".")[0] for fname in _0x676011da1(_0x676011da5))
_0x676011da7 = _0x676011da5.parts[-1]


def __getattr__(name: str) -> _0x676011da3:
    if name in _0x676011da6 or name.startswith("_"):
        raise AttributeError
    obj = _0x676011da4().get_share(_0x676011da7, name)
    if obj.static:
        return obj.get()
    return obj
