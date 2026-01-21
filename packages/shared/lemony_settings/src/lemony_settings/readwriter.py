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


def fill_missing_optional_with_none(
    data: dict[str, Any], model_cls: type[BaseModel]
) -> None:
    """
    对照模型定义, 给缺失的 Optional 字段补 None.

    只处理类型注解包含 None 的字段 (即 Optional 或 Union[..., None]).
    对于有默认值但不允许 None 的字段, 让 Pydantic 使用默认值.
    """
    from typing import Union, get_args, get_origin

    for field_name, field_info in model_cls.model_fields.items():
        if field_name not in data:
            # 检查字段是否允许 None
            annotation = field_info.annotation
            allows_none = False

            if annotation is None:
                allows_none = True
            elif annotation is type(None):
                allows_none = True
            else:
                # 检查是否是 Optional[X] 或 Union[X, None]
                origin = get_origin(annotation)
                if origin is Union:
                    args = get_args(annotation)
                    allows_none = type(None) in args

            if allows_none:
                data[field_name] = None
            # 否则让 Pydantic 使用默认值或报验证错误

        elif isinstance(data.get(field_name), dict):
            # 如果字段是嵌套的 BaseModel, 递归处理
            annotation = field_info.annotation
            if (
                annotation
                and isinstance(annotation, type)
                and issubclass(annotation, BaseModel)
            ):
                fill_missing_optional_with_none(data[field_name], annotation)


@register_read_writer("toml")
class TomlReadWriter(ConfigReadWriterABC):
    def read(self, file: Path, model: type[MT]) -> MT:
        with file.open("rb") as f:
            data = tomli.load(f)
        # 因为先前写入时排除了 None, 所以这里需要给缺失的 Optional 字段补 None
        fill_missing_optional_with_none(data, model)
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
