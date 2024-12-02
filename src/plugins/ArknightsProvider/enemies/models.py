from typing import TypedDict
from pydantic import BaseModel


class Enemy(TypedDict):
    sortId: int
    name: str
    enemyIndex: str
    enemyLink: str
    enemyRace: str
    enemyLevel: str
    enemyRes: str
    enemyDamageRes: str
    attackType: str
    damageType: str
    motion: str
    endure: str
    attack: str
    defence: str
    moveSpeed: str
    attackSpeed: str
    resistance: str
    ability: str


class EnemyLib(BaseModel):
    data: list[Enemy]
