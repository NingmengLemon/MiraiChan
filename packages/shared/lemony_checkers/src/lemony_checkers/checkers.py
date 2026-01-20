from melobot.adapter.model import EventT
from melobot.utils.check import Checker


class LemonyChecker(Checker[EventT]):
    async def check(self, event: EventT) -> bool:
        # 在这里实现你的检查逻辑
        return True
