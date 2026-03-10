"""
配置管理模块.

使用 lemony_settings 进行配置的加载和管理.
"""

import warnings
from collections.abc import Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from lemony_settings import LemonySettings, require
from melobot.log import get_logger

from .models import CheckerGlobalSettings, CheckerPluginSettings

if TYPE_CHECKING:
    from .checkers import AdminChecker, FailCallback, LemonyChecker, OwnerChecker

logger = get_logger()

# 模块标识符
MODULE_IDENTIFIER = "lemony_checkers"


class LemonyCheckerFactory:
    """
    权限检查器工厂类. 提供获取和管理权限配置的接口.
    """

    def __init__(self):
        # 全局配置实例
        self._global_checker_settings: LemonySettings[CheckerGlobalSettings] | None = (
            None
        )
        # 插件配置缓存
        self._plugin_settings_cache: dict[
            str, LemonySettings[CheckerPluginSettings]
        ] = {}

    def post_init(self):
        if self._global_checker_settings is None:
            self._global_checker_settings = require(
                identifier=MODULE_IDENTIFIER,
                namespace="global",
                model=CheckerGlobalSettings,
            )
            logger.info("Loaded checker global settings")
        else:
            warnings.warn(
                "LemonyCheckerFactory post_init called but global settings already initialized."
            )

    def new_checker(
        self,
        plugin_name: str | None = None,
        command_name: str | None = None,
        *,
        fail_cb: "FailCallback | None" = None,
        allow_admin: bool = True,
    ) -> "LemonyChecker":
        """创建一个新的 LemonyChecker 实例."""
        from .checkers import LemonyChecker

        return LemonyChecker(
            plugin_name=plugin_name,
            command_name=command_name,
            fail_cb=fail_cb,
            allow_admin=allow_admin,
            factory=self,
        )

    def new_owner_checker(
        self, fail_cb: "FailCallback | None" = None
    ) -> "OwnerChecker":
        """创建一个只允许 Owner 的检查器."""
        from .checkers import OwnerChecker

        return OwnerChecker(factory=self, fail_cb=fail_cb)

    def new_admin_checker(
        self, fail_cb: "FailCallback | None" = None
    ) -> "AdminChecker":
        """创建一个允许 Owner 和 Admin 的检查器."""
        from .checkers import AdminChecker

        return AdminChecker(factory=self, fail_cb=fail_cb)

    @property
    def global_settings(self) -> CheckerGlobalSettings:
        """
        获取权限检查器的全局配置.

        Returns:
            CheckerGlobalSettings: 全局配置实例

        Raises:
            RuntimeError: 如果配置尚未初始化
        """
        if self._global_checker_settings is None:
            raise RuntimeError(
                "LemonyCheckerFactory global settings not initialized. "
                "Call post_init() first or use init_checker_factory()."
            )
        return self._global_checker_settings.value

    def get_plugin_settings(self, plugin_name: str) -> CheckerPluginSettings:
        """
        获取指定插件的权限配置.

        Args:
            plugin_name: 插件名称

        Returns:
            CheckerPluginSettings: 插件配置实例
        """
        if plugin_name not in self._plugin_settings_cache:
            settings = require(
                identifier=MODULE_IDENTIFIER,
                namespace=plugin_name,
                model=CheckerPluginSettings,
            )
            self._plugin_settings_cache[plugin_name] = settings
            logger.info(f"Loaded checker settings for plugin: {plugin_name}")

        return self._plugin_settings_cache[plugin_name].value

    # edit / save / reload methods

    def save_global_settings(self) -> None:
        """
        保存全局配置到文件.

        在使用编程式 API 修改全局配置后调用此函数来持久化更改.
        """
        if self._global_checker_settings is not None:
            self._global_checker_settings.save()
            logger.info("Global checker settings saved")
        else:
            logger.warning("Global checker settings not initialized, nothing to save")

    def save_plugin_settings(self, plugin_name: str) -> None:
        """
        保存指定插件的配置到文件.

        在使用编程式 API 修改插件配置后调用此函数来持久化更改.

        Args:
            plugin_name: 插件名称
        """
        if plugin_name in self._plugin_settings_cache:
            self._plugin_settings_cache[plugin_name].save()
            logger.info(f"Plugin '{plugin_name}' checker settings saved")
        else:
            logger.warning(
                f"Plugin '{plugin_name}' settings not loaded, nothing to save"
            )

    def reload_global_settings(self) -> CheckerGlobalSettings:
        """
        重新加载全局配置.

        Returns:
            CheckerGlobalSettings: 重新加载后的全局配置
        """
        if self._global_checker_settings is not None:
            self._global_checker_settings.load()
            logger.info("Reloaded checker global settings")

        return self.global_settings

    def reload_plugin_settings(self, plugin_name: str) -> CheckerPluginSettings:
        """
        重新加载指定插件的配置.

        Args:
            plugin_name: 插件名称

        Returns:
            CheckerPluginSettings: 重新加载后的插件配置
        """
        if plugin_name in self._plugin_settings_cache:
            self._plugin_settings_cache[plugin_name].load()
            logger.info(f"Reloaded checker settings for plugin: {plugin_name}")

        return self.get_plugin_settings(plugin_name)

    @contextmanager
    def edit_global_settings(self) -> Generator[CheckerGlobalSettings, None, None]:
        """
        编辑全局配置.
        """
        yield self.global_settings
        self.save_global_settings()

    @contextmanager
    def edit_plugin_settings(
        self, plugin_name: str
    ) -> Generator[CheckerPluginSettings, None, None]:
        """
        编辑插件配置.

        Args:
            plugin_name: 插件名称
        """
        yield self.get_plugin_settings(plugin_name)
        self.save_plugin_settings(plugin_name)

    # 权限检查相关方法

    def is_owner(self, user_id: int) -> bool:
        """
        检查用户是否是机器人所有者.

        Args:
            user_id: 用户QQ号

        Returns:
            bool: 是否是所有者
        """
        global_settings = self.global_settings
        return global_settings.owner is not None and global_settings.owner == user_id

    def is_admin(self, user_id: int) -> bool:
        """
        检查用户是否是机器人管理员.

        Args:
            user_id: 用户QQ号

        Returns:
            bool: 是否是管理员
        """
        global_settings = self.global_settings
        return user_id in global_settings.admins

    def get_owner(self) -> int | None:
        """
        获取机器人所有者的QQ号.

        Returns:
            int | None: 所有者QQ号, 如果未设置则返回 None
        """
        return self.global_settings.owner

    def get_admins(self) -> list[int]:
        """
        获取机器人管理员列表.

        Returns:
            list[int]: 管理员QQ号列表
        """
        return self.global_settings.admins.copy()


_lemony_checker_factory: LemonyCheckerFactory | None = None


def get_checker_factory() -> LemonyCheckerFactory:
    """
    获取全局的 LemonyCheckerFactory 实例.
    """
    if _lemony_checker_factory is None:
        raise RuntimeError(
            "LemonyCheckerFactory has not been initialized. Please call init_checker_factory() first."
        )
    return _lemony_checker_factory


def init_checker_factory() -> LemonyCheckerFactory:
    """
    初始化全局的 LemonyCheckerFactory 实例.

    Returns:
        LemonyCheckerFactory: 全局 factory 实例 (已初始化或已存在的).
    """
    global _lemony_checker_factory
    if _lemony_checker_factory is not None:
        warnings.warn(
            "LemonyCheckerFactory has already been initialized. Returning the existing instance."
        )
        return _lemony_checker_factory
    _lemony_checker_factory = LemonyCheckerFactory()
    _lemony_checker_factory.post_init()
    return _lemony_checker_factory


def _reset_for_testing() -> None:
    """将全局 factory 实例重置为 None.

    **仅供测试使用.** 在每个需要重新初始化的测试用例前调用.
    生产代码中禁止调用此函数.

    Example::

        def setup_function():
            lemony_checkers.factory._reset_for_testing()
            lemony_settings.manager._reset_for_testing()
    """
    global _lemony_checker_factory
    _lemony_checker_factory = None
