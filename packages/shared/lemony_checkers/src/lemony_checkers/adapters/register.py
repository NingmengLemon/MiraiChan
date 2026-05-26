import warnings
from collections.abc import Callable

from lemony_utils.concurrency import SyncRWContext
from melobot.adapter import Event as RootEvent

from ..models import UniqueUserDataclassBase
from .base import IdExtractorProtocol

__all__ = ["registry"]


class _IdExtractorRegistry:
    def __init__(self) -> None:
        self._uniid_extractor_registry: dict[
            str, list[IdExtractorProtocol]  # 一系列可能适用的提取器, 按顺序尝试提取
            # 若最终也没能提取直接 reject
        ] = {}
        self._rwlock = SyncRWContext()

    def register_uniid_extractor[ExT: IdExtractorProtocol](
        self,
        protocol_id: str,
    ) -> Callable[[ExT], ExT]:
        def decorator(extractor_cls: ExT) -> ExT:
            with self._rwlock.write():
                if protocol_id not in self._uniid_extractor_registry:
                    self._uniid_extractor_registry[protocol_id] = []
                if extractor_cls in self._uniid_extractor_registry[protocol_id]:
                    warnings.warn(
                        f"Extractor {extractor_cls} is already registered for protocol {protocol_id}. "
                    )
                else:
                    self._uniid_extractor_registry[protocol_id].append(extractor_cls)
            return extractor_cls

        return decorator

    def get_uniid_extractors(self, protocol_id: str) -> tuple[IdExtractorProtocol, ...]:
        with self._rwlock.read():
            extractors = self._uniid_extractor_registry.get(protocol_id)
            return tuple(extractors or [])

    def extract_uniid(
        self, protocol_id: str, event: RootEvent
    ) -> UniqueUserDataclassBase | None:
        for extractor in self.get_uniid_extractors(protocol_id):
            uniid = extractor(event)
            if uniid is not None:
                return uniid
        return None

    def extract_uniid_any(self, event: RootEvent) -> UniqueUserDataclassBase | None:
        """自动从事件中提取 UniqueUser, 利用 event.protocol 匹配已注册的 extractor."""
        return self.extract_uniid(str(event.protocol), event)

    def clear_uniid_extractors(self) -> None:
        with self._rwlock.write():
            self._uniid_extractor_registry.clear()


registry = _IdExtractorRegistry()
