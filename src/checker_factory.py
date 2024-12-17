import atexit
from typing import Any
from melobot import get_logger
from melobot.protocols.onebot.v11.utils import (
    MsgCheckerFactory,
    MsgChecker,
    LevelRole,
    GroupRole,
)
from pydantic import BaseModel

from configloader import ConfigLoader, ConfigLoaderMetadata

__all__ = [
    "OWNER",
    "get_owner_checker",
    "get_su_checker",
    "get_normal_checker",
    "get_white_checker",
]


class CkConfModel(BaseModel):
    owner: int | None = None
    super_users: list[int] = []
    white_users: list[int] = []
    black_users: list[int] = []


logger = get_logger()

_cfgloader = ConfigLoader(
    ConfigLoaderMetadata(
        model=CkConfModel,
        filename="checkers_conf.json",
    )
)
_cfgloader.load_config()
atexit.register(_cfgloader.save_config)
logger.debug("privilege_list: " + _cfgloader.config.model_dump_json(indent=4))
_FACTORY = MsgCheckerFactory(**_cfgloader.config.model_dump())
OWNER = _cfgloader.config.owner


def _get_level_checker(level: LevelRole):
    return _FACTORY.get_base(level)


def get_owner_checker():
    return _get_level_checker(LevelRole.OWNER)


def get_su_checker():
    return _get_level_checker(LevelRole.SU)


def get_normal_checker():
    return _get_level_checker(LevelRole.NORMAL)


def get_white_checker():
    return _get_level_checker(LevelRole.WHITE)
