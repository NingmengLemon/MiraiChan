from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, Secret

from .utils import get_project_root

DEFAULT_CONFIG_PATH = get_project_root() / "config.json"


class WebsocketIOConfigModel(BaseModel):
    access_token: Secret[str | None] = Secret(None)
    cd_time: int = Field(default=0, ge=0)


class ReverseWebsocketIOConfigModel(WebsocketIOConfigModel):
    host: str = "127.0.0.1"
    port: int = Field(default=10721, ge=0)
    type: Literal["reverse"] = "reverse"


class ForwardWebsocketIOConfigModel(WebsocketIOConfigModel):
    url: str = "ws://127.0.0.1:10721"
    type: Literal["forward"] = "forward"


class GlobalConfigModel(BaseModel):
    debug: bool = False
    websocket: ForwardWebsocketIOConfigModel | ReverseWebsocketIOConfigModel = Field(
        discriminator="type", default_factory=lambda: ForwardWebsocketIOConfigModel()
    )

    load_depth: int = 3
    plugins: list[str] = []

    settings_format: Literal["json", "yaml"] | str = "json"
    config_root: str | Path = Field(default=get_project_root() / "configs")

    default_font_path: str | Path = Field(
        default=get_project_root() / "data" / "fonts" / "sarasa-mono-sc-semibold.ttf"
    )
