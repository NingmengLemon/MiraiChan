"""
测试 readwriter 模块.
"""

import json
from pathlib import Path

import pytest
import tomli
import yaml
from lemony_settings import BaseSettings
from lemony_settings.readwriter import (
    JsonReadWriter,
    TomlReadWriter,
    YamlReadWriter,
    get_read_writer,
)


class SampleSettings(BaseSettings):
    name: str = "default"
    count: int = 0
    enabled: bool = True
    optional_field: str | None = None


class TestTomlReadWriter:
    def test_write_and_read(self, tmp_path: Path) -> None:
        """测试 TOML 写入和读取."""
        file_path = tmp_path / "test.toml"
        writer = TomlReadWriter()

        settings = SampleSettings(name="test", count=42, enabled=False)
        writer.write(file_path, settings)

        assert file_path.exists()

        # 验证文件内容
        with file_path.open("rb") as f:
            data = tomli.load(f)
        assert data["name"] == "test"
        assert data["count"] == 42
        assert data["enabled"] is False

        # 读取回来
        loaded = writer.read(file_path, SampleSettings)
        assert loaded.name == "test"
        assert loaded.count == 42
        assert loaded.enabled is False

    def test_none_values_excluded(self, tmp_path: Path) -> None:
        """测试 TOML 写入时排除 None 值 (TOML 不支持 null)."""
        file_path = tmp_path / "test.toml"
        writer = TomlReadWriter()

        settings = SampleSettings(name="test", optional_field=None)
        writer.write(file_path, settings)

        with file_path.open("rb") as f:
            data = tomli.load(f)

        # optional_field 不应该在文件中
        assert "optional_field" not in data

    def test_read_partial_file_uses_defaults(self, tmp_path: Path) -> None:
        """测试读取部分字段的文件时, Pydantic 使用默认值."""
        file_path = tmp_path / "test.toml"

        # 手动创建一个只包含部分字段的文件
        with file_path.open("wb") as f:
            import tomli_w

            # 只写入 name 和 count, 缺少 enabled 和 optional_field
            tomli_w.dump({"name": "partial", "count": 10}, f)

        writer = TomlReadWriter()
        loaded = writer.read(file_path, SampleSettings)

        assert loaded.name == "partial"
        assert loaded.count == 10
        # Pydantic 使用模型定义的默认值
        assert loaded.enabled is True  # 默认值
        assert loaded.optional_field is None  # 默认值 (Optional 字段)


class TestYamlReadWriter:
    def test_write_and_read(self, tmp_path: Path) -> None:
        """测试 YAML 写入和读取."""
        file_path = tmp_path / "test.yaml"
        writer = YamlReadWriter()

        settings = SampleSettings(name="yaml_test", count=100, enabled=True)
        writer.write(file_path, settings)

        assert file_path.exists()

        # 验证文件内容
        with file_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert data["name"] == "yaml_test"
        assert data["count"] == 100

        # 读取回来
        loaded = writer.read(file_path, SampleSettings)
        assert loaded.name == "yaml_test"
        assert loaded.count == 100

    def test_none_values_preserved(self, tmp_path: Path) -> None:
        """测试 YAML 支持 None 值."""
        file_path = tmp_path / "test.yaml"
        writer = YamlReadWriter()

        settings = SampleSettings(name="test", optional_field=None)
        writer.write(file_path, settings)

        with file_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        # YAML 支持 null
        assert "optional_field" in data
        assert data["optional_field"] is None


class TestJsonReadWriter:
    def test_write_and_read(self, tmp_path: Path) -> None:
        """测试 JSON 写入和读取."""
        file_path = tmp_path / "test.json"
        writer = JsonReadWriter()

        settings = SampleSettings(name="json_test", count=999, enabled=False)
        writer.write(file_path, settings)

        assert file_path.exists()

        # 验证文件内容
        with file_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["name"] == "json_test"
        assert data["count"] == 999

        # 读取回来
        loaded = writer.read(file_path, SampleSettings)
        assert loaded.name == "json_test"
        assert loaded.count == 999


class TestGetReadWriter:
    def test_get_toml_writer(self) -> None:
        writer = get_read_writer("toml")
        assert isinstance(writer, TomlReadWriter)

    def test_get_yaml_writer(self) -> None:
        writer = get_read_writer("yaml")
        assert isinstance(writer, YamlReadWriter)

    def test_get_json_writer(self) -> None:
        writer = get_read_writer("json")
        assert isinstance(writer, JsonReadWriter)

    def test_singleton_pattern(self) -> None:
        """测试读写器是单例模式."""
        writer1 = get_read_writer("toml")
        writer2 = get_read_writer("toml")
        assert writer1 is writer2

    def test_unsupported_format(self) -> None:
        with pytest.raises(ValueError, match="Unsupported config format"):
            get_read_writer("xml")
