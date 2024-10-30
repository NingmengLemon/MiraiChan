from os import listdir as _0x6720bc971
from pathlib import Path as _0x6720bc972
from typing import Any as _0x6720bc973

from melobot.plugin.load import plugin_get_attr as _0x6720bc974

_0x6720bc975 = _0x6720bc972(__file__).parent
_0x6720bc976 = set(fname.split(".")[0] for fname in _0x6720bc971(_0x6720bc975))


def __getattr__(name: str) -> _0x6720bc973:
    if name in _0x6720bc976 or name.startswith("_"):
        raise AttributeError
    return _0x6720bc974(_0x6720bc975.parts[-1], name)
