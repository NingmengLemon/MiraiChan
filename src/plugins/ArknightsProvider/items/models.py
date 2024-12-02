from typing import TypedDict

from pydantic import BaseModel


class Item(TypedDict):
    id: int
    name: str
    description: str
    usage: str
    obtain_approach: str
    rarity: int
    category: list[str]
    file: str


class ItemsLib(BaseModel):
    data: list[Item]
