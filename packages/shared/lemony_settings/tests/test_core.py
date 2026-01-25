"""
测试 core 模块.
"""

from pathlib import Path

import pytest
from lemony_settings import (
    BaseSettings,
    LemonySettings,
    get_global_settings,
    init_global_settings,
    require,
    resolve_config_path,
)


class MyTestSettings(BaseSettings):
    name: str = "default_name"
    value: int = 42
    enabled: bool = True


class NestedSettings(BaseSettings):
    title: str = "nested"
    count: int = 0


class TestBaseSettings:
    def test_default_values(self) -> None:
        """测试 BaseSettings 子类可以用默认值初始化."""
        settings = MyTestSettings()
        assert settings.name == "default_name"
        assert settings.value == 42
        assert settings.enabled is True

    def test_custom_values(self) -> None:
        """测试自定义值."""
        settings = MyTestSettings(name="custom", value=100, enabled=False)
        assert settings.name == "custom"
        assert settings.value == 100
        assert settings.enabled is False

    def test_validate_assignment(self) -> None:
        """测试赋值时验证."""
        settings = MyTestSettings()
        settings.value = 999
        assert settings.value == 999

        # Pydantic 会验证类型
        with pytest.raises(Exception):  # ValidationError
            settings.value = "not_an_int"  # type: ignore


class TestResolveConfigPath:
    def test_resolve_global_config(self, tmp_path: Path) -> None:
        """测试解析全局配置路径."""
        config_path = resolve_config_path(tmp_path, "toml", id_ns=None)
        assert config_path == tmp_path / "global.toml"

    def test_resolve_plugin_config(self, tmp_path: Path) -> None:
        """测试解析插件配置路径."""
        config_path = resolve_config_path(
            tmp_path, "yaml", id_ns=("my_plugin", "settings")
        )
        assert config_path == tmp_path / "my_plugin" / "settings.yaml"

    def test_creates_directories(self, tmp_path: Path) -> None:
        """测试自动创建目录."""
        config_dir = tmp_path / "new_configs"
        config_path = resolve_config_path(
            config_dir, "json", id_ns=("plugin", "config")
        )
        assert config_path.parent.exists()

    def test_different_formats(self, tmp_path: Path) -> None:
        """测试不同格式的扩展名."""
        assert resolve_config_path(tmp_path, "toml").suffix == ".toml"
        assert resolve_config_path(tmp_path, "yaml").suffix == ".yaml"
        assert resolve_config_path(tmp_path, "json").suffix == ".json"


class TestInitGlobalSettings:
    def test_init_creates_global_config(self, tmp_path: Path) -> None:
        """测试初始化创建全局配置文件."""
        global_settings = init_global_settings(
            preference="toml", config_path=tmp_path / "configs"
        )

        assert global_settings is not None
        assert global_settings.preference == "toml"

        global_config_file = tmp_path / "configs" / "global.toml"
        assert global_config_file.exists()

    def test_init_twice_raises_error(self, tmp_path: Path) -> None:
        """测试重复初始化抛出错误."""
        init_global_settings(preference="toml", config_path=tmp_path / "configs")

        with pytest.raises(RuntimeError, match="already been initialized"):
            init_global_settings(preference="toml", config_path=tmp_path / "configs2")

    def test_get_global_settings_before_init(self) -> None:
        """测试初始化前获取全局设置抛出错误."""
        with pytest.raises(RuntimeError, match="has not been initialized"):
            get_global_settings()

    def test_get_global_settings_after_init(self, tmp_path: Path) -> None:
        """测试初始化后获取全局设置."""
        init_global_settings(preference="yaml", config_path=tmp_path / "configs")
        global_settings = get_global_settings()
        assert global_settings.preference == "yaml"


class TestLemonySettings:
    def test_identifier_validation(self, tmp_path: Path) -> None:
        """测试标识符验证."""
        init_global_settings(preference="toml", config_path=tmp_path / "configs")

        # 有效的标识符
        settings = LemonySettings("valid_id", "namespace", MyTestSettings)
        assert settings.identifier == "valid_id"

        # 无效的标识符
        with pytest.raises(ValueError, match="does not match"):
            LemonySettings("123invalid", "namespace", MyTestSettings)

        with pytest.raises(ValueError, match="does not match"):
            LemonySettings("valid", "has-dash", MyTestSettings)

    def test_duplicate_settings_raises_error(self, tmp_path: Path) -> None:
        """测试重复创建同一个设置抛出错误."""
        init_global_settings(preference="toml", config_path=tmp_path / "configs")

        LemonySettings("plugin", "config", MyTestSettings)

        with pytest.raises(ValueError, match="already exists"):
            LemonySettings("plugin", "config", MyTestSettings)

    def test_value_not_loaded_error(self, tmp_path: Path) -> None:
        """测试未加载时访问 value 抛出错误."""
        init_global_settings(preference="toml", config_path=tmp_path / "configs")

        settings = LemonySettings("test_plugin", "default", MyTestSettings)

        with pytest.raises(RuntimeError, match="has not been loaded"):
            _ = settings.value

    def test_load_creates_default_config(self, tmp_path: Path) -> None:
        """测试加载时如果文件不存在则创建默认配置."""
        init_global_settings(preference="toml", config_path=tmp_path / "configs")

        settings = LemonySettings("new_plugin", "settings", MyTestSettings)
        settings.load()

        # 检查值已加载
        assert settings.value.name == "default_name"
        assert settings.value.value == 42

        # 检查文件已创建
        config_file = tmp_path / "configs" / "new_plugin" / "settings.toml"
        assert config_file.exists()

    def test_load_from_existing_file(self, tmp_path: Path) -> None:
        """测试从现有文件加载."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        # 先创建配置文件
        plugin_dir = config_dir / "existing_plugin"
        plugin_dir.mkdir(parents=True)
        config_file = plugin_dir / "settings.toml"

        import tomli_w

        with config_file.open("wb") as f:
            tomli_w.dump({"name": "from_file", "value": 123, "enabled": False}, f)

        # 加载
        settings = LemonySettings("existing_plugin", "settings", MyTestSettings)
        settings.load()

        assert settings.value.name == "from_file"
        assert settings.value.value == 123
        assert settings.value.enabled is False

    def test_save(self, tmp_path: Path) -> None:
        """测试保存功能."""
        init_global_settings(preference="toml", config_path=tmp_path / "configs")

        settings = LemonySettings("save_test", "config", MyTestSettings)
        settings.load()

        # 修改值
        settings.value.name = "modified"
        settings.value.value = 999

        # 手动保存
        settings.save()

        # 验证文件内容
        config_file = tmp_path / "configs" / "save_test" / "config.toml"
        import tomli

        with config_file.open("rb") as f:
            data = tomli.load(f)

        assert data["name"] == "modified"
        assert data["value"] == 999


class TestRequire:
    def test_require_creates_and_loads_new_settings(self, tmp_path: Path) -> None:
        """测试 require 创建并自动加载新设置."""
        init_global_settings(preference="toml", config_path=tmp_path / "configs")

        # require 应该自动创建并加载配置
        settings = require(MyTestSettings, "require_test")
        settings.load()
        value = settings.value
        # 应该返回默认值
        assert value.name == "default_name"
        assert value.value == 42

        # 配置文件应该已被创建
        config_file = tmp_path / "configs" / "require_test" / "default.toml"
        assert config_file.exists()

    def test_require_returns_same_instance(self, tmp_path: Path) -> None:
        """测试 require 返回相同实例."""
        init_global_settings(preference="toml", config_path=tmp_path / "configs")

        # 第一次调用 require 会创建并加载
        value1 = require(MyTestSettings, "same_test", namespace="default")

        # 第二次调用应该返回相同的 value
        value2 = require(MyTestSettings, "same_test", namespace="default")
        assert value1 is value2
