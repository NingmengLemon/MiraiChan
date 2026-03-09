from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, Secret

from .utils import get_project_root

CONFIG_PATH = Path("config.json")


class ForwWsIOConfigModel(BaseModel):
    url: str
    access_token: Secret[str | None] = Secret(None)


class GlobalConfigModel(BaseModel):
    debug: bool = False
    forwwsio: ForwWsIOConfigModel

    load_depth: int = 3
    plugins: list[str] = []

    settings_format: Literal["json", "yaml"] | str = "json"
    config_root: str | Path = Field(
        default_factory=lambda: get_project_root() / "configs"
    )
