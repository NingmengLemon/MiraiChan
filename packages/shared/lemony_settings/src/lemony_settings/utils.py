import re
from pathlib import Path
from typing import Literal

from .consts import IDENTIFIER_PATTERN


def check_identifier(value: str) -> str:
    if re.fullmatch(IDENTIFIER_PATTERN, value) is None:
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
    """
    config_root = Path(config_path).resolve()
    config_root.mkdir(parents=True, exist_ok=True)

    if id_ns is None:
        return config_root / f"global.{preference}"
    identifier, namespace = id_ns
    file = config_root / identifier / f"{namespace}.{preference}"
    file.parent.mkdir(parents=True, exist_ok=True)
    return file
