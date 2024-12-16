import atexit
from typing import Any
from melobot import get_logger
from melobot.protocols.onebot.v11.utils import (
    MsgCheckerFactory,
    MsgChecker,
    LevelRole,
    GroupRole,
)
from melobot.typ import AsyncCallable
from pydantic import BaseModel

from configloader import ConfigLoader, ConfigLoaderMetadata

__all__ = ("owner",)


class CkConfModel(BaseModel):
    owner: int | None = None
    super_users: list[int] = []
    # white_users: list[int] = []
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

owner = _cfgloader.config.owner
