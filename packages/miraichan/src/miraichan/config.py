from pathlib import Path

from pydantic import BaseModel, Secret

CONFIG_PATH = Path("config.json")


class ForwWsIOConfigModel(BaseModel):
    url: str
    access_token: Secret[str | None] = Secret(None)


class GlobalConfigModel(BaseModel):
    forwwsio: ForwWsIOConfigModel
    debug: bool = False
    plugins: list[str] = []
    load_depth: int = 3
