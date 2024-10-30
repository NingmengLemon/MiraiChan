import atexit
from typing import Any
from melobot import get_logger
from melobot.plugin import Plugin, SyncShare
from melobot.protocols.onebot.v11.utils import (
    MsgCheckerFactory,
    MsgChecker,
    LevelRole,
    GroupRole,
)
from melobot.typ import AsyncCallable
from pydantic import BaseModel

from configloader import ConfigLoader, ConfigLoaderMetadata

__all__ = (
    "get_checker_factory",
    "get_checker",
    "owner",
    "get_super_users",
    "get_white_users",
    "get_black_users",
    "owner_checker",
    "super_checker",
    "white_checker",
    "normal_checker",
)


class ImmutableRoleModel(BaseModel):
    owner: int | None = None
    super_users: list[int] = []


class MutableRoleModel(BaseModel):
    white_users: list[int] = []
    black_users: list[int] = []


class CkConfModel(ImmutableRoleModel, MutableRoleModel):
    pass


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


def get_checker_factory():
    return MsgCheckerFactory(**_cfgloader.config.model_dump())


_factory = get_checker_factory()


def get_checker(role: LevelRole, fail_cb: AsyncCallable[[], None] | None = None):
    ck = _factory.get_group(role) | _factory.get_private(role)
    ck.set_fail_cb(fail_cb)
    return ck


owner = _cfgloader.config.owner
get_super_users = _cfgloader.config.super_users.copy
get_white_users = _cfgloader.config.white_users.copy
get_black_users = _cfgloader.config.black_users.copy

owner_checker = get_checker(LevelRole.OWNER)
super_checker = get_checker(LevelRole.SU)
white_checker = get_checker(LevelRole.WHITE)
normal_checker = get_checker(LevelRole.NORMAL)