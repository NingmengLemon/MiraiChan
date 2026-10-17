import os
from functools import cache
from pathlib import Path

from melobot.log import get_logger

logger = get_logger()

PROJECT_ROOT_MAKERS = ("miracle_entrance.py",)
PROJECT_ROOT_ENV = "MIRAICHAN_PROJECT_ROOT"


@cache
def get_project_root() -> Path:
    """项目根目录: 环境变量 MIRAICHAN_PROJECT_ROOT 优先, 用于在隔离目录里运行
    (测试、演练); 否则从包所在位置向上找 miracle_entrance.py"""
    if override := os.environ.get(PROJECT_ROOT_ENV):
        root = Path(override).resolve()
        if not root.is_dir():
            raise RuntimeError(f"{PROJECT_ROOT_ENV}={override!r} is not a directory")
        return root
    if (
        proj_root := search_upwards_for_files(
            Path(__file__).parent,
            *PROJECT_ROOT_MAKERS,
        )
    ) is None:
        logger.debug("Project root not found, using current working directory.")
        return Path.cwd()
    logger.debug(f"Project root found at: {proj_root}")
    return proj_root


def search_upwards_for_files(start_path: Path, *target_files: str) -> Path | None:
    """
    向上搜索直到找到包含所有 target_files 的目录，并返回该目录的路径。如果没有找到，返回 None。
    """
    current_path = start_path
    while current_path != current_path.parent:
        if all((current_path / target_file).exists() for target_file in target_files):
            return current_path
        current_path = current_path.parent
    return None


def customize_melobot_logo(new_logo: str) -> None:
    try:
        from melobot._meta import MetaInfoMeta
        # 咳咳私有成员注意, 后续随时可能被改掉

        # logo 在类型上是 ReadOnlyAttr, 运行时可写; 用 setattr 绕开只读声明
        setattr(MetaInfoMeta, "logo", new_logo.strip())  # noqa: B010
    except Exception as e:  # noqa: BLE001 - 私有 API 随版本变化, 失败只是不换 logo
        logger.warning(
            f"Failed to patch MetaInfoMeta: {e}, logo will not be customized."
        )


_ALTERNATIVE_LOGO_REBEL = r"""
                          ████           █████               █████   
                         ▒▒███          ▒▒███               ▒▒███    
 █████████████    ██████  ▒███   ██████  ▒███████   ██████  ███████  
▒▒███▒▒███▒▒███  ███▒▒███ ▒███  ███▒▒███ ▒███▒▒███ ███▒▒███▒▒▒███▒   
 ▒███ ▒███ ▒███ ▒███████  ▒███ ▒███ ▒███ ▒███ ▒███▒███ ▒███  ▒███    
 ▒███ ▒███ ▒███ ▒███▒▒▒   ▒███ ▒███ ▒███ ▒███ ▒███▒███ ▒███  ▒███ ███
 █████▒███ █████▒▒██████  █████▒▒██████  ████████ ▒▒██████   ▒▒█████ 
▒▒▒▒▒ ▒▒▒ ▒▒▒▒▒  ▒▒▒▒▒▒  ▒▒▒▒▒  ▒▒▒▒▒▒  ▒▒▒▒▒▒▒▒   ▒▒▒▒▒▒     ▒▒▒▒▒  
梅洛姬, 参上 ～(∠・ω< )⌒☆
"""
_ALTERNATIVE_NO_LOGO = r"""
梅洛姬气人, 启动中!
梅洛姬, 参上 ～(∠・ω< )⌒☆
"""


ALTERNATIVE_LOGOS = {
    "rebel": _ALTERNATIVE_LOGO_REBEL,
    "no_logo": _ALTERNATIVE_NO_LOGO,
}
