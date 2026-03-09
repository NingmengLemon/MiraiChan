from functools import cache
from pathlib import Path

PROJECT_ROOT_MAKERS = ("miracle_entrance.py",)


@cache
def get_project_root() -> Path:
    proj_root = search_upwards_for_files(
        Path(__file__).parent,
        *PROJECT_ROOT_MAKERS,
    )
    if proj_root is None:
        raise FileNotFoundError("Could not find the project root.")
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
