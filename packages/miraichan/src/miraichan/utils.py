from functools import cache
from pathlib import Path

from melobot.log import get_logger

logger = get_logger()

PROJECT_ROOT_MAKERS = ("miracle_entrance.py",)


@cache
def get_project_root() -> Path:
    proj_root = search_upwards_for_files(
        Path(__file__).parent,
        *PROJECT_ROOT_MAKERS,
    )
    if proj_root is None:
        raise FileNotFoundError("Could not find the project root.")
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

        setattr(MetaInfoMeta, "logo", new_logo.strip())
    except Exception as e:
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
梅洛姬, 参上 Ciallo～(∠・ω< )⌒☆
"""
_ALTERNATIVE_NO_LOGO = r"""
梅洛姬气人, 启动中!
梅洛姬, 参上 Ciallo～(∠・ω< )⌒☆
"""


ALTERNATIVE_LOGOS = {
    "rebel": _ALTERNATIVE_LOGO_REBEL,
    "no_logo": _ALTERNATIVE_NO_LOGO,
}
