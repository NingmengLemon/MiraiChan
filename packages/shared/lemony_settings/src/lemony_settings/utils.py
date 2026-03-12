from pathlib import Path
from typing import Literal

from .consts import IDENTIFIER_PATTERN


def check_identifier(value: str) -> str:
    if IDENTIFIER_PATTERN.fullmatch(value) is None:
        raise ValueError(
            f"Value '{value}' does not match the pattern '{IDENTIFIER_PATTERN}'"
        )
    return value


def resolve_config_path(
    config_path: str | Path,
    preference: Literal["yaml", "json"] | str,
    # yaml 和 json 是 builtin, 要使用其他格式需要先在 readwriter 中注册
    id_ns: tuple[str, str] | None,
) -> Path:
    """
    获取当前设置对应的配置文件路径.

    注意: 这个函数只做路径计算, 不创建目录.
    目录创建应由调用方在写入操作时负责.
    """
    config_root = Path(config_path).resolve()

    if id_ns is None:
        return config_root / f"global.{preference}"
    identifier, namespace = id_ns
    file = config_root / identifier / f"{namespace}.{preference}"
    return file


def ensure_config_path(path: Path) -> Path:
    """
    确保配置文件的父目录存在. 在写入配置文件前调用.

    Returns:
        传入的 path, 方便链式调用.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
