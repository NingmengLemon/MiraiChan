# This file is @generated by melobot cli.
# It is not intended for manual editing.
from os import listdir as _0x676011e41
from pathlib import Path as _0x676011e42
from typing import Any as _0x676011e43

from melobot import get_bot as _0x676011e44

_0x676011e45 = _0x676011e42(__file__).parent
_0x676011e46 = set(fname.split(".")[0] for fname in _0x676011e41(_0x676011e45))
_0x676011e47 = _0x676011e45.parts[-1]


def __getattr__(name: str) -> _0x676011e43:
    if name in _0x676011e46 or name.startswith("_"):
        raise AttributeError
    obj = _0x676011e44().get_share(_0x676011e47, name)
    if obj.static:
        return obj.get()
    return obj
