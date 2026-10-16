"""运行期数据文件的统一根目录 (data root)。

上层 (miraichan 主程序) 启动时用 ``set_data_root`` 设定一次, 之后插件和共享库都用
``data_path`` 拿数据文件的绝对路径, 不再依赖当前工作目录。

数据库的相对路径也以它为根: ``SqliteDatabaseHelper`` 在没有单独设置
``set_relative_path_base`` 时会退回到 data root。
"""

from pathlib import Path, PurePath

__all__ = [
    "DataRootNotSetError",
    "configured_data_path",
    "data_path",
    "get_data_root",
    "is_data_root_set",
    "set_data_root",
]

_data_root: Path | None = None


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
