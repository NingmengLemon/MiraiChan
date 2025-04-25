from typing import TypedDict

from pydantic import BaseModel, Field


class PrivateReg(TypedDict):
    id: str
    user_id: int
    group_id: int

    days: int
    hour: int
    minute: int


class CfgModel(BaseModel):
    private_registrations: list[PrivateReg] = Field(default_factory=list)
