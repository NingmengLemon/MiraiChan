"""
pytest 配置文件和通用 fixtures.
"""

import shutil
import sys
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock

import pytest

# Mock melobot.log 模块, 避免测试时需要完整的 melobot 环境
mock_logger = MagicMock()
mock_log_module = MagicMock()
mock_log_module.get_logger = MagicMock(return_value=mock_logger)
sys.modules["melobot"] = MagicMock()
sys.modules["melobot.log"] = mock_log_module


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
    # 在导入之前先 mock
    yield
    # 测试后重置全局状态
    from lemony_settings import core, events, watcher

    core._global_settings = None
    core._SETTINGS_TABLE.clear()
    events._event_emitter = None
    watcher._file_watcher = None
