"""adapters 单元测试 —— 协议提取器注册表 + OB11 提取器."""

from __future__ import annotations

import warnings
from unittest.mock import MagicMock

import pytest
from lemony_checkers.adapters.ob11 import (
    OB11_PROTOCOL_ID,
    builtin_ob11_uniid_extractor,
)
from lemony_checkers.adapters.register import _IdExtractorRegistry

# ============================================================
# _IdExtractorRegistry
# ============================================================


class TestIdExtractorRegistry:
    """测试 _IdExtractorRegistry."""

    @pytest.fixture
    def registry(self) -> _IdExtractorRegistry:
        """每个测试使用独立的 registry 实例."""
        return _IdExtractorRegistry()

    def test_register_and_get(self, registry):
        """注册提取器后可通过 get_uniid_extractors 获取."""

        def dummy_extractor(event: object) -> None:
            return None

        registry.register_uniid_extractor("test-protocol")(dummy_extractor)
        extractors = registry.get_uniid_extractors("test-protocol")
        assert len(extractors) == 1
        assert extractors[0] is dummy_extractor

    def test_get_unregistered_protocol_returns_empty(self, registry):
        """未注册的协议返回空元组."""
        extractors = registry.get_uniid_extractors("unknown")
        assert extractors == ()

    def test_multiple_extractors_same_protocol(self, registry):
        """同一协议注册多个提取器, 按注册顺序返回."""
        results: list[int] = []

        def ex1(event: object) -> None:
            results.append(1)
            return None

        def ex2(event: object) -> None:
            results.append(2)
            return None

        registry.register_uniid_extractor("test-protocol")(ex1)
        registry.register_uniid_extractor("test-protocol")(ex2)

        extractors = registry.get_uniid_extractors("test-protocol")
        assert len(extractors) == 2

    def test_extract_uniid_returns_first_match(self, registry):
        """extract_uniid 返回第一个非 None 的结果."""

        class FakeEvent:
            pass

        def ex1(event: object) -> str | None:
            return None

        def ex2(event: object) -> str | None:
            return "matched"

        def ex3(event: object) -> str | None:
            return "never_reached"

        registry.register_uniid_extractor("test-protocol")(ex1)
        registry.register_uniid_extractor("test-protocol")(ex2)
        registry.register_uniid_extractor("test-protocol")(ex3)

        result = registry.extract_uniid("test-protocol", FakeEvent())
        assert result == "matched"

    def test_extract_uniid_all_none(self, registry):
        """所有提取器都返回 None 时返回 None."""

        def ex(event: object) -> None:
            return None

        registry.register_uniid_extractor("test-protocol")(ex)
        result = registry.extract_uniid("test-protocol", object())
        assert result is None

    def test_extract_uniid_any_uses_event_protocol(self, registry):
        """extract_uniid_any 从 event.protocol 获取协议."""

        class FakeEvent:
            protocol = "fake-protocol"

        matched_value = object()

        def ex(event: object) -> object | None:
            return matched_value

        registry.register_uniid_extractor("fake-protocol")(ex)
        result = registry.extract_uniid_any(FakeEvent())
        assert result is matched_value

    def test_duplicate_registration_warns(self, registry):
        """重复注册同一提取器产生警告."""

        def ex(event: object) -> None:
            return None

        registry.register_uniid_extractor("test-protocol")(ex)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            registry.register_uniid_extractor("test-protocol")(ex)
            assert len(w) == 1
            assert "already registered" in str(w[0].message)

    def test_clear_extractors(self, registry):
        """清除后所有注册信息丢失."""

        def ex(event: object) -> None:
            return None

        registry.register_uniid_extractor("test-protocol")(ex)
        assert len(registry.get_uniid_extractors("test-protocol")) == 1

        registry.clear_uniid_extractors()
        assert len(registry.get_uniid_extractors("test-protocol")) == 0


# ============================================================
# builtin_ob11_uniid_extractor
# ============================================================


class TestBuiltinOb11Extractor:
    """测试内置 OB11 提取器 (使用 mock 事件)."""

    def test_group_message_extracts_correctly(self):
        """群聊消息正确提取 user_id 和 group_id."""
        event = MagicMock()
        # 需要满足 melobot OB11 Event/MessageEvent/GroupMessageEvent 的 isinstance 检查
        # 通过 mock 返回合适的 sub_type 来避开匿名检查
        from melobot.protocols.onebot.v11 import GroupMessageEvent

        # 用 spec 让 isinstance 通过
        event = MagicMock(spec=GroupMessageEvent)
        event.user_id = 1001
        event.group_id = 5000
        event.sub_type = "normal"

        result = builtin_ob11_uniid_extractor(event)
        assert result is not None
        d = result.to_dict()
        assert d["user_id"] == 1001
        assert d["group_id"] == 5000
        assert d["protocol"] == OB11_PROTOCOL_ID

    def test_private_message_extracts_correctly(self):
        """私聊消息 group_id 为 None."""
        from melobot.protocols.onebot.v11 import PrivateMessageEvent

        event = MagicMock(spec=PrivateMessageEvent)
        event.user_id = 1001
        event.sub_type = "friend"

        result = builtin_ob11_uniid_extractor(event)
        assert result is not None
        d = result.to_dict()
        assert d["user_id"] == 1001
        assert d["group_id"] is None
        assert d["protocol"] == OB11_PROTOCOL_ID

    def test_anonymous_message_returns_none(self):
        """匿名消息返回 None."""
        from melobot.protocols.onebot.v11 import GroupMessageEvent

        event = MagicMock(spec=GroupMessageEvent)
        event.user_id = 1001
        event.group_id = 5000
        event.sub_type = "anonymous"

        result = builtin_ob11_uniid_extractor(event)
        assert result is None

    def test_non_message_event_returns_none(self):
        """非 MessageEvent 返回 None."""
        from melobot.protocols.onebot.v11 import Event

        event = MagicMock(spec=Event)
        result = builtin_ob11_uniid_extractor(event)
        assert result is None

    def test_non_ob11_event_returns_none(self):
        """通用 object 返回 None."""
        result = builtin_ob11_uniid_extractor(object())  # type: ignore[arg-type]
        assert result is None
