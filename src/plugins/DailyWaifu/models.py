import uuid
import time

from pydantic import BaseModel
from sqlmodel import Field, SQLModel


class ConfigModel(BaseModel):
    dburl: str = "sqlite:///data/group_waifus.db"


class DailyWaifuRel(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    src: int
    dst: int
    gid: int
    time: float = Field(default_factory=time.time)


class MarriageRel(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    a: int
    b: int
    gid: int
    time: float = Field(default_factory=time.time)
