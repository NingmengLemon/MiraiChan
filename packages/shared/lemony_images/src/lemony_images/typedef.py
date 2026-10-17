import os
from typing import BinaryIO

type _FontFileT = str | bytes | os.PathLike[str] | os.PathLike[bytes] | BinaryIO
type _4IntTupleT = tuple[int, int, int, int]
type _3IntTupleT = tuple[int, int, int]
type _ColorTupleT = _3IntTupleT | _4IntTupleT
type _ColorT = int | _ColorTupleT | str
type _BboxT = _4IntTupleT
