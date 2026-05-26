from typing import Protocol

from melobot.adapter.model import Event

from ..models import UniqueUserDataclassBase


class IdExtractorProtocol[EventT: Event](Protocol):
    def __call__(self, event: EventT) -> UniqueUserDataclassBase | None: ...
