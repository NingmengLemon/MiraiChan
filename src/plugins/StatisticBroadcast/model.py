from typing import TypedDict

from pydantic import BaseModel, Field


class PrivateReg(TypedDict):
    id: str
    user_id: int
    group_id: int

    days: int = 1
    hour: int = 0
    minute: int = 0


class CfgModel(BaseModel):
    private_registrations: list[PrivateReg] = Field(default_factory=list)
