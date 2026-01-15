from pydantic import BaseModel


class ForwWsIOConfigModel(BaseModel):
    url: str
    access_token: str | None = None


class GlobalConfigModel(BaseModel):
    forwwsio: ForwWsIOConfigModel
    debug: bool = False
    plugins: list[str] = []
    load_depth: int = 3
