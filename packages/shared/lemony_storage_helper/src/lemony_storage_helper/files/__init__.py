"""运行期数据文件的统一根目录 (data root)。

上层 (miraichan 主程序) 启动时用 ``set_data_root`` 设定一次, 之后插件和共享库都用
``data_path`` 拿数据文件的绝对路径, 不再依赖当前工作目录。

数据库的相对路径也以它为根: ``SqliteDatabaseHelper`` 在没有单独设置
``set_relative_path_base`` 时会退回到 data root。

写入走 ``atomic_write_bytes`` / ``atomic_write_text``: 先写同目录临时文件再替换,
并发读不会读到写了一半的文件, 失败时原文件不动。

这两个函数不提供互斥: 两个人同时写同一个路径仍然是"最后写完的赢"。需要
"读出来、改、再写回去"的地方, 得由调用方自己跨住整段读写 (例如借 ``filelock``),
只靠原子写入会把别人这段时间的改动覆盖掉。
"""

import contextlib
import os
import tempfile
import time
from pathlib import Path, PurePath

__all__ = [
    "DataRootNotSetError",
    "atomic_write_bytes",
    "atomic_write_text",
    "configured_data_path",
    "data_path",
    "get_data_root",
    "is_data_root_set",
    "set_data_root",
]

_data_root: Path | None = None

# Windows 上并发替换同一个目标会撞共享冲突 (WinError 5), 短暂重试即可;
# 重试是安全的, replace 要么整个成功要么什么都没发生
_REPLACE_RETRIES = 5
_REPLACE_BACKOFF_S = 0.02


def _replace_with_retry(src: Path, dst: Path) -> None:
    for attempt in range(_REPLACE_RETRIES):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == _REPLACE_RETRIES - 1:
                raise
            time.sleep(_REPLACE_BACKOFF_S * (attempt + 1))


class DataRootNotSetError(RuntimeError):
    """在上层设定 data root 之前就要求数据文件路径"""


def set_data_root(root: str | Path | None) -> None:
    """设定 data root; 传 None 清除 (测试用)。路径会被 resolve 成绝对路径"""
    global _data_root
    _data_root = Path(root).resolve() if root is not None else None


def is_data_root_set() -> bool:
    return _data_root is not None


def get_data_root() -> Path:
    if _data_root is None:
        raise DataRootNotSetError(
            "data root is not set; call lemony_storage_helper.files.set_data_root first"
        )
    return _data_root


def data_path(*parts: str | PurePath, mkdir_parent: bool = False) -> Path:
    """data root 下的路径。

    parts 必须是相对路径片段, 拼接后不能越出 data root (拒绝绝对路径、盘符与越界的 ``..``),
    不合法时抛 ValueError, 不做静默修正。mkdir_parent=True 时顺带创建父目录。
    """
    root = get_data_root()
    rel = PurePath(*parts) if parts else PurePath()
    if rel.is_absolute() or rel.drive or rel.anchor:
        raise ValueError(f"data path must be relative: {rel}")
    path = (root / rel).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"data path escapes the data root: {rel}")
    if mkdir_parent:
        path.parent.mkdir(parents=True, exist_ok=True)
    return path


def configured_data_path(raw: str | PurePath, *, mkdir_parent: bool = False) -> Path:
    """把配置项里写的路径解析成绝对路径。

    绝对路径原样返回; 相对路径以 data root 为根。早先的相对路径以 cwd (项目根) 为根,
    已生成的配置文件里常见 ``data/xxx`` 这种写法, 开头的 ``data`` 段会被去掉,
    指向同一个文件。
    """
    p = PurePath(raw)
    if p.is_absolute():
        path = Path(p)
        if mkdir_parent:
            path.parent.mkdir(parents=True, exist_ok=True)
        return path
    parts = p.parts
    if parts and parts[0] == "data":
        parts = parts[1:]
    return data_path(*parts, mkdir_parent=mkdir_parent)


def atomic_write_bytes(
    path: str | PurePath, data: bytes, *, fsync: bool = True
) -> Path:
    """原子写入字节: 同目录临时文件写完之后 replace, 失败时临时文件不留下。

    父目录不存在时自动创建。落盘的内容总是某一次写入的完整结果, 不会是两次写入
    拼起来的东西; 失败时原文件不动, 临时文件也不留下。
    并发写同一个路径时, Windows 的 replace 会撞共享冲突, 这里做了短暂重试,
    少量并发 (插件的实际用法) 不会报错; 同一路径被十几个线程同时抢时会仍然抛
    PermissionError, 那种场景应由调用方自己串行化或者各写各的文件名。
    fsync=True 只保证把文件内容刷下去, 目录项本身的持久化没保证 (真断电时可能丢
    掉这次 replace); fsync=False 连内容都不刷, 缓存类文件不需要, 断电可能得到空文件。
    POSIX 上新文件的权限是 0600 (``tempfile.mkstemp`` 的语义), 需要别人也能读时
    调用方自己 chmod。
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=target.parent, prefix=f".{target.name}.", suffix=".tmp"
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fp:
            fp.write(data)
            if fsync:
                fp.flush()
                os.fsync(fp.fileno())
        _replace_with_retry(tmp, target)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
        raise
    return target


def atomic_write_text(
    path: str | PurePath,
    text: str,
    *,
    encoding: str = "utf-8",
    fsync: bool = True,
) -> Path:
    """原子写入文本, 其余同 ``atomic_write_bytes``"""
    return atomic_write_bytes(path, text.encode(encoding), fsync=fsync)
