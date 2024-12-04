import asyncio
import time

from melobot.utils import RWContext, singleton

from . import enemies, items, operators

__all__ = ["enemies", "items", "operators", "ArknSource"]


@singleton
class ArknSource:
    def __init__(self):
        self._enemies: enemies.EnemyLib | None = None
        self._items: items.ItemsLib | None = None
        self._operators: operators.OperatorLib | None = None
        self._operator_filters: operators.OperatorFilters | None = None
        self.last_update: float = 0
        self._rwc = RWContext()

    async def update(self):
        async with self._rwc.write():
            self._enemies, self._items = await asyncio.gather(
                enemies.fetch(),
                items.fetch(),
            )
            self._operators, self._operator_filters = await operators.fetch()
            self.last_update = time.time()

    async def enemies(self):
        async with self._rwc.read():
            return self._enemies.data.copy() if self._enemies else None

    async def items(self):
        async with self._rwc.read():
            return self._items.data.copy() if self._items else None

    async def operators(self):
        async with self._rwc.read():
            return self._operators.data.copy() if self._operators else None

    async def operator_filters(self):
        async with self._rwc.read():
            return (
                self._operator_filters.filters.copy()
                if self._operator_filters
                else None
            )
