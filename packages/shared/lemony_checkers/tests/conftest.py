"""
pytest 配置文件和通用 fixtures.
"""

import shutil
import sys
from pathlib import Path
from typing import Generator, Generic, TypeVar
from unittest.mock import MagicMock

import pytest

# Mock melobot.log 模块, 避免测试时需要完整的 melobot 环境
mock_logger = MagicMock()
mock_log_module = MagicMock()
mock_log_module.get_logger = MagicMock(return_value=mock_logger)
sys.modules["melobot"] = MagicMock()
sys.modules["melobot.log"] = mock_log_module

# Mock melobot.protocols.onebot.v11 模块
mock_v11 = MagicMock()


class MockMessageEvent:
    """Mock MessageEvent for testing."""

    def __init__(self, user_id: int, group_id: int | None = None):
        self.user_id = user_id
        self.group_id = group_id


class MockGroupMessageEvent(MockMessageEvent):
    """Mock GroupMessageEvent for testing."""

    def __init__(self, user_id: int, group_id: int):
        super().__init__(user_id, group_id)


mock_v11.MessageEvent = MockMessageEvent
mock_v11.GroupMessageEvent = MockGroupMessageEvent
sys.modules["melobot.protocols.onebot.v11"] = mock_v11


# Mock melobot.utils.check 模块 - 使用 Generic 支持类型参数
EventT = TypeVar("EventT")


class MockChecker(Generic[EventT]):
    """Mock base Checker class with Generic support."""

    def __init__(self):
        pass

    async def check(self, event: EventT) -> bool:
        return True


mock_check = MagicMock()
mock_check.Checker = MockChecker
sys.modules["melobot.utils.check"] = mock_check


@pytest.fixture
def temp_config_dir(tmp_path: Path) -> Generator[Path, None, None]:
    """创建临时配置目录."""
    config_dir = tmp_path / "configs"
    config_dir.mkdir(parents=True, exist_ok=True)
    yield config_dir
    # 清理
    if config_dir.exists():
        shutil.rmtree(config_dir)


@pytest.fixture(autouse=True)
def reset_global_state() -> Generator[None, None, None]:
    """每个测试前后重置全局状态."""
    yield
    # 测试后重置全局状态
    from lemony_settings import core, events, watcher

    core._global_settings = None
    core._SETTINGS_TABLE.clear()
    events._event_emitter = None
    watcher._file_watcher = None

    # 重置 lemony_checkers 的状态
    from lemony_checkers import settings as checker_settings

    checker_settings._global_checker_settings = None
    checker_settings._plugin_settings_cache.clear()


@pytest.fixture
def mock_message_event() -> MockMessageEvent:
    """创建一个 Mock 消息事件."""
    return MockMessageEvent(user_id=12345)


@pytest.fixture
def mock_group_message_event() -> MockGroupMessageEvent:
    """创建一个 Mock 群消息事件."""
    return MockGroupMessageEvent(user_id=12345, group_id=98765)
