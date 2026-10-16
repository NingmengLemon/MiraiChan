import json
import os
import shutil
import tempfile
import warnings
from abc import ABC, abstractmethod
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

import json5
import tomli
import tomli_w
import yaml
from pydantic import BaseModel


def _atomic_write(file: Path, content: str | bytes) -> None:
    """原子写入配置文件: 先写同目录下的临时文件, 再 os.replace 覆盖目标.

    直接截断写目标文件时, 写到一半崩溃 / 断电 / 磁盘写满都会留下半个配置文件: 下次加载
    解析失败, 而文件"存在"又不会重新生成默认配置。临时文件与目标同目录, 保证 replace 是
    同文件系统内的原子重命名。

    临时文件名由 mkstemp 生成, 同一目标的并发写入不会共用同一个临时文件。mkstemp 建出的
    文件权限是 0600, 目标已存在时沿用目标的权限位, 新建的配置则保持 0600 (配置里可能有凭据)。
    """
    fd, tmp_name = tempfile.mkstemp(
        dir=file.parent, prefix=f".{file.name}.", suffix=".tmp"
    )
    tmp = Path(tmp_name)
    try:
        # str 走文本模式, 与直接写文件时的换行处理保持一致
        mode, encoding = ("wb", None) if isinstance(content, bytes) else ("w", "utf-8")
        with os.fdopen(fd, mode, encoding=encoding) as fp:
            fp.write(content)
            fp.flush()
            os.fsync(fp.fileno())
        if file.exists():
            shutil.copymode(file, tmp)
        os.replace(tmp, file)
    except BaseException:
        # 取消 (CancelledError) 不是 Exception, 同样要清掉半成品
        with suppress(OSError):
            tmp.unlink(missing_ok=True)
        raise


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
                f"ReadWriter for format {key!r} is already registered, it will be overwritten.",
                stacklevel=2,
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
        # 保持原来的二进制写出方式 (不经过文本模式的换行转换)
        _atomic_write(file, tomli_w.dumps(data_dict).encode("utf-8"))


@register_readwriter("yaml")
class YamlReadWriter(ConfigReadWriterABC):
    def read[MT: BaseModel](self, file: Path, model: type[MT]) -> MT:
        with file.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return model.model_validate(data)

    def write(self, file: Path, data: BaseModel) -> None:
        _atomic_write(file, yaml.safe_dump(data.model_dump(), allow_unicode=True))


@register_readwriter("json")
class JsonReadWriter(ConfigReadWriterABC):
    def read[MT: BaseModel](self, file: Path, model: type[MT]) -> MT:
        with file.open("r", encoding="utf-8") as f:
            data = json5.load(f)
        return model.model_validate(data)

    def write(self, file: Path, data: BaseModel) -> None:
        # 宽进严出这一块, 用 json5 读用 json 写是故意的
        _atomic_write(
            file,
            json.dumps(data.model_dump(), indent=4, ensure_ascii=False),
        )


def get_readwriter(format: str) -> ConfigReadWriterABC:
    if format not in _readwriter_instances:
        if format not in _readwriter_registry:
            raise ValueError(f"Unsupported config format: {format}")
        _readwriter_instances[format] = _readwriter_registry[format]()
    return _readwriter_instances[format]
