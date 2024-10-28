import atexit
from typing import Any
from melobot import Plugin
from melobot.protocols.onebot.v11.utils import (
    MsgCheckerFactory,
    MsgChecker,
    LevelRole,
    GroupRole,
)
from melobot.typ import AsyncCallable
from pydantic import BaseModel

from configloader import ConfigLoader, ConfigLoaderMetadata


class ImmutableRoleModel(BaseModel):
    owner: int | None = None
    super_users: list[int] = []


class MutableRoleModel(BaseModel):
    white_users: list[int] = []
    black_users: list[int] = []
    white_groups: list[int] = []


class CkConfModel(ImmutableRoleModel, MutableRoleModel):
    pass


cfgloader = ConfigLoader(
    ConfigLoaderMetadata(
        model=CkConfModel,
        filename="checkers_conf.json",
    )
)
cfgloader.load_config()
atexit.register(cfgloader.save_config)


def _get_checker_factory():
    return MsgCheckerFactory(**cfgloader.config.model_dump())


_checker_factory = _get_checker_factory()


def get_checker(role: LevelRole, fail_cb: AsyncCallable[[], None] | None = None):
    ck = _checker_factory.get_group(role) | _checker_factory.get_private(role)
    ck.set_fail_cb(fail_cb)
    return ck


class CheckerProvider(Plugin):
    author = "LemonyNingmeng"
    version = "0.1.0"
    funcs = (get_checker,)
