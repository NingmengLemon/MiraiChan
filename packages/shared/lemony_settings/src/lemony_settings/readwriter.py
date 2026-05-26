import json
import warnings
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path

import json5
import tomli
import tomli_w
import yaml
from pydantic import BaseModel


# 预期是无状态的通用工具
class ConfigReadWriterABC(ABC):
    @abstractmethod
    def read[MT: BaseModel](self, file: Path, model: type[MT]) -> MT:
        raise NotImplementedError

    @abstractmethod
    def write(self, file: Path, data: BaseModel) -> None:
        raise NotImplementedError


_readwriter_registry: dict[str, type[ConfigReadWriterABC]] = {}
_readwriter_instances: dict[str, ConfigReadWriterABC] = {}


def register_readwriter[T: ConfigReadWriterABC](
    format: str,  # 需要注册的格式名称, 同时为扩展名
) -> Callable[[type[T]], type[T]]:
    def decorator(cls: type[T]) -> type[T]:
        if (key := format.lower().strip()) in _readwriter_registry:
            warnings.warn(
                f"ReadWriter for format {key!r} is already registered, it will be overwritten."
            )
        _readwriter_registry[key] = cls
        return cls

    return decorator


@register_readwriter("toml")
class TomlReadWriter(ConfigReadWriterABC):
    def read[MT: BaseModel](self, file: Path, model: type[MT]) -> MT:
        with file.open("rb") as f:
            data = tomli.load(f)
        # 因为先前写入时排除了 None
        # 预期会发生一些神秘的问题
        # 解决方法是暂不使用 toml
        return model.model_validate(data)

    def write(self, file: Path, data: BaseModel) -> None:
        # toml 不支持 None/null/nil
        # see https://github.com/toml-lang/toml/issues/921
        data_dict = data.model_dump(exclude_none=True)
        with file.open("wb") as f:
            tomli_w.dump(data_dict, f)


@register_readwriter("yaml")
class YamlReadWriter(ConfigReadWriterABC):
    def read[MT: BaseModel](self, file: Path, model: type[MT]) -> MT:
        with file.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return model.model_validate(data)

    def write(self, file: Path, data: BaseModel) -> None:
        with file.open("w", encoding="utf-8") as f:
            yaml.safe_dump(data.model_dump(), f, allow_unicode=True)


@register_readwriter("json")
class JsonReadWriter(ConfigReadWriterABC):
    def read[MT: BaseModel](self, file: Path, model: type[MT]) -> MT:
        with file.open("r", encoding="utf-8") as f:
            data = json5.load(f)
        return model.model_validate(data)

    def write(self, file: Path, data: BaseModel) -> None:
        with file.open("w", encoding="utf-8") as f:
            # 宽进严出这一块, 用 json5 读用 json 写是故意的
            json.dump(data.model_dump(), f, indent=4, ensure_ascii=False)


def get_readwriter(format: str) -> ConfigReadWriterABC:
    if format not in _readwriter_instances:
        if format not in _readwriter_registry:
            raise ValueError(f"Unsupported config format: {format}")
        _readwriter_instances[format] = _readwriter_registry[format]()
    return _readwriter_instances[format]
