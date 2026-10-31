"""EditContext 的保存失败回滚语义."""

from typing import Any, cast

import pytest
from lemony_checkers import CheckerSettingsSaveError, EditContext
from lemony_checkers.models import CheckerGlobalSettings, CheckerPluginSettings


class _FakeFactory:
    def __init__(
        self,
        global_settings: CheckerGlobalSettings,
        plugins: dict[str, CheckerPluginSettings] | None = None,
    ) -> None:
        self.global_settings = global_settings
        self.plugins = {} if plugins is None else plugins
        self.fail: set[str] = set()
        self.saved: list[str] = []

    def get_plugin_settings(self, plugin_name: str) -> CheckerPluginSettings:
        return self.plugins[plugin_name]

    def save_global_settings(self) -> None:
        if "global" in self.fail:
            raise OSError("disk full")
        self.saved.append("global")

    def save_plugin_settings(self, plugin_name: str) -> None:
        if plugin_name in self.fail:
            raise OSError("disk full")
        self.saved.append(plugin_name)


def _context(factory: _FakeFactory) -> EditContext:
    return EditContext(cast(Any, factory))


def test_global_save_failure_rolls_back_in_memory_change() -> None:
    settings = CheckerGlobalSettings(mode="blacklist")
    factory = _FakeFactory(settings)
    factory.fail.add("global")

    with pytest.raises(CheckerSettingsSaveError) as exc_info, _context(factory) as ctx:
        ctx.set_global_mode("whitelist")

    assert settings.mode == "blacklist"
    assert factory.saved == []
    assert set(exc_info.value.failures) == {"global"}


def test_plugin_save_failure_keeps_targets_that_were_written() -> None:
    global_settings = CheckerGlobalSettings(mode="blacklist")
    plugin_a = CheckerPluginSettings(enabled=True)
    plugin_b = CheckerPluginSettings(enabled=True)
    factory = _FakeFactory(global_settings, {"a": plugin_a, "b": plugin_b})
    factory.fail.add("a")

    with pytest.raises(CheckerSettingsSaveError) as exc_info, _context(factory) as ctx:
        ctx.set_global_mode("whitelist")
        ctx.set_plugin_enabled("a", False)
        ctx.set_plugin_enabled("b", False)

    # 全局与 b 已成功写入, 保留内存修改; a 写入失败, 回滚到快照
    assert global_settings.mode == "whitelist"
    assert plugin_a.enabled is True
    assert plugin_b.enabled is False
    assert set(factory.saved) == {"global", "b"}
    assert set(exc_info.value.failures) == {"a"}


def test_body_exception_rolls_back_all_without_saving() -> None:
    settings = CheckerGlobalSettings(mode="blacklist")
    factory = _FakeFactory(settings)

    with pytest.raises(RuntimeError), _context(factory) as ctx:
        ctx.set_global_mode("whitelist")
        raise RuntimeError("stop here")

    assert settings.mode == "blacklist"
    assert factory.saved == []


@pytest.mark.asyncio
async def test_async_save_failure_rolls_back_in_memory_change() -> None:
    settings = CheckerGlobalSettings(mode="blacklist")
    factory = _FakeFactory(settings)
    factory.fail.add("global")

    with pytest.raises(CheckerSettingsSaveError) as exc_info:
        async with _context(factory) as ctx:
            ctx.set_global_mode("whitelist")

    assert settings.mode == "blacklist"
    assert factory.saved == []
    assert set(exc_info.value.failures) == {"global"}
