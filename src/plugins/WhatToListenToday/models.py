from typing import Literal, TypedDict

from pydantic import BaseModel


class WTLTConfig(BaseModel):
    share_host: str = "http://127.0.0.1:8000"  # 分享的链接的地址
    server: str = "http://127.0.0.1:8000"  # 连接到的后端的地址
    access_token: str = "114514"
    share_link: bool = False


class DrawResp(TypedDict):
    id: str
    title: str | None
    album: str | None
    artists: list[str]
    albumartists: list[str]
    duration: float
    filename: str
    session: str
    href: str
    player: str
    lyrics: str | None


class StatusResp(TypedDict):
    status: Literal["pause", "running"]
    count: int
    online: float
    time: float
