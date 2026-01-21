import json
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

import tomli
import tomli_w
import yaml
from pydantic import BaseModel

MT = TypeVar("MT", bound=BaseModel)


# 预期是无状态的通用工具
class ConfigReadWriterABC(ABC):
    @abstractmethod
    def read(self, file: Path, model: type[MT]) -> MT:
        raise NotImplementedError

    @abstractmethod
    def write(self, file: Path, data: BaseModel) -> None:
        raise NotImplementedError


_read_writer_registry: dict[str, type[ConfigReadWriterABC]] = {}
_read_writer_instances: dict[str, ConfigReadWriterABC] = {}


def register_read_writer[T: ConfigReadWriterABC](
    format: str,  # 需要注册的格式名称, 同时为扩展名
) -> Callable[[type[T]], type[T]]:
    def decorator(cls: type[T]) -> type[T]:
        _read_writer_registry[format.lower()] = cls
        return cls

    return decorator


def fill_missing_with_none(data: dict[str, Any], model_cls: type[BaseModel]) -> None:
    # 对照模型定义, 给缺失的字段补 None
    for field_name, field_info in model_cls.model_fields.items():
        if field_name not in data:
            data[field_name] = None
        elif isinstance(data.get(field_name), dict):
            # 如果字段是嵌套的 BaseModel, 递归处理
            annotation = field_info.annotation
            if (
                annotation
                and isinstance(annotation, type)
                and issubclass(annotation, BaseModel)
            ):
                fill_missing_with_none(data[field_name], annotation)


@register_read_writer("toml")
class TomlReadWriter(ConfigReadWriterABC):
    def read(self, file: Path, model: type[MT]) -> MT:
        with file.open("rb") as f:
            data = tomli.load(f)
        # 因为先前写入时排除了 None, 所以这里需要给缺失的字段补 None
        fill_missing_with_none(data, model)
        return model.model_validate(data)

    def write(self, file: Path, data: BaseModel) -> None:
        # toml 不支持 None/null/nil
        # see https://github.com/toml-lang/toml/issues/921
        data_dict = data.model_dump(exclude_none=True)
        with file.open("wb") as f:
            tomli_w.dump(data_dict, f)


@register_read_writer("yaml")
class YamlReadWriter(ConfigReadWriterABC):
    def read(self, file: Path, model: type[MT]) -> MT:
        with file.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return model.model_validate(data)

    def write(self, file: Path, data: BaseModel) -> None:
        with file.open("w", encoding="utf-8") as f:
            yaml.safe_dump(data.model_dump(), f)


@register_read_writer("json")
class JsonReadWriter(ConfigReadWriterABC):
    def read(self, file: Path, model: type[MT]) -> MT:
        with file.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return model.model_validate(data)

    def write(self, file: Path, data: BaseModel) -> None:
        with file.open("w", encoding="utf-8") as f:
            json.dump(data.model_dump(), f, indent=4)


def get_read_writer(format: str) -> ConfigReadWriterABC:
    if format not in _read_writer_instances:
        if format not in _read_writer_registry:
            raise ValueError(f"Unsupported config format: {format}")
        _read_writer_instances[format] = _read_writer_registry[format]()
    return _read_writer_instances[format]
