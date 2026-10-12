"""插件加载的隔离: 一个坏插件不应该让整个 bot 起不来.

回归点:

- melobot 的 ``Bot.load_plugins`` 是裸循环, 任何插件抛异常都会中断后续所有插件的加载,
  于是一个依赖缺失的插件能让整个 bot 起不来。
- 插件解析阶段 ``except ModuleNotFoundError: pass`` 会把"插件自身依赖缺失"也当成
  "这个插件不是已安装的包", 最后报出与真实原因无关的路径解析失败。
"""

from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from melobot.exceptions import PluginLoadError
from miraichan import loader as loader_mod

# miraichan/__init__.py 导出了同名的 main 函数, 这里显式按模块导入
main_mod = importlib.import_module("miraichan.main")


class _FakeBot:
    def __init__(self, *, fail_for: set[str]) -> None:
        self.fail_for = fail_for
        self.loaded: list[str] = []

    def load_plugin(self, plugin: Any, load_depth: int = 1, **kwargs: Any) -> None:
        name = str(plugin)
        if name in self.fail_for:
            raise RuntimeError(f"boom: {name}")
        self.loaded.append(name)


class TestResolvePlugins:
    def test_skips_names_that_fail_to_resolve(self, monkeypatch: pytest.MonkeyPatch):
        def fake_resolve(name: str) -> str:
            if name == "bad":
                raise PluginLoadError("cannot resolve")
            return f"resolved:{name}"

        monkeypatch.setattr(main_mod, "resolve_plugin_path", fake_resolve)

        assert main_mod._resolve_plugins(["good", "bad", "also_good"]) == [
            ("good", "resolved:good"),
            ("also_good", "resolved:also_good"),
        ]

    def test_keeps_order(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(main_mod, "resolve_plugin_path", lambda name: name.upper())
        assert main_mod._resolve_plugins(["a", "b"]) == [("a", "A"), ("b", "B")]


class TestLoadPlugins:
    def test_continues_after_a_failing_plugin(self):
        bot = _FakeBot(fail_for={"bad"})
        plugins = [("good", "good"), ("bad", "bad"), ("also_good", "also_good")]

        main_mod._load_plugins(bot, plugins, load_depth=1)  # type: ignore[arg-type]

        assert bot.loaded == ["good", "also_good"]

    def test_loads_everything_when_nothing_fails(self):
        bot = _FakeBot(fail_for=set())
        main_mod._load_plugins(
            bot,  # type: ignore[arg-type]
            [("a", "a"), ("b", "b")],
            load_depth=2,
        )
        assert bot.loaded == ["a", "b"]

    def test_all_failures_are_tolerated(self):
        bot = _FakeBot(fail_for={"a", "b"})
        main_mod._load_plugins(bot, [("a", "a"), ("b", "b")], load_depth=1)  # type: ignore[arg-type]
        assert bot.loaded == []


class TestResolvePluginPathErrors:
    def test_missing_dependency_is_raised(self, monkeypatch: pytest.MonkeyPatch):
        """插件自身依赖缺失 (报错的名字不是插件名) 必须原样抛出, 不能被当成插件不存在."""

        class _FakeImportlib:
            util = SimpleNamespace(
                find_spec=staticmethod(
                    lambda name: SimpleNamespace(origin="somewhere.py")
                )
            )

            @staticmethod
            def import_module(name: str) -> None:
                raise ModuleNotFoundError(
                    "No module named 'missing_dep'", name="missing_dep"
                )

        monkeypatch.setattr(loader_mod, "importlib", _FakeImportlib)

        with pytest.raises(ModuleNotFoundError):
            loader_mod.resolve_plugin_path("mbplugin_x")

    def test_missing_plugin_name_falls_through(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        """报错的名字就是插件名时, 继续按本地/内置路径查找."""

        class _FakeImportlib:
            util = SimpleNamespace(
                find_spec=staticmethod(
                    lambda name: SimpleNamespace(origin="somewhere.py")
                )
            )

            @staticmethod
            def import_module(name: str) -> None:
                raise ModuleNotFoundError(
                    f"No module named {name!r}", name="mbplugin_x"
                )

        monkeypatch.setattr(loader_mod, "importlib", _FakeImportlib)
        monkeypatch.setattr(loader_mod, "get_project_root", lambda: tmp_path)

        with pytest.raises(PluginLoadError):
            loader_mod.resolve_plugin_path("mbplugin_x")
