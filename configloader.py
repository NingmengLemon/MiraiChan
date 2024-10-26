from dataclasses import dataclass
import os
from typing import Type

from pydantic import BaseModel

# 十分甚至九分简陋的配置文件加载器（逃


@dataclass(kw_only=True)
class ConfigLoaderMetadata[T: BaseModel]:
    model: Type[T]
    filename: str
    location: str = "./plugin_config/"


class ConfigLoader[T: BaseModel]:
    __config: T
    __metadata: ConfigLoaderMetadata[T]

    def __init__(self, metadata: ConfigLoaderMetadata[T] | None = None):
        self.__is_set = False
        self.__is_loaded = False
        if metadata:
            self.set_config(metadata)

    def __set_checker(self):
        if not self.__is_set:
            raise RuntimeError("Config not set yet")

    def __load_checker(self):
        if not self.__is_loaded:
            raise RuntimeError("Config not loaded yet")

    def set_config(self, metadata: ConfigLoaderMetadata[T]):
        self.__metadata = metadata
        self.__is_set = True

    @property
    def is_set(self):
        return self.__is_set

    @property
    def is_loaded(self):
        return self.__is_loaded

    @property
    def is_ready(self):
        return self.is_loaded and self.is_set

    @property
    def config(self):
        self.__load_checker()
        return self.__config

    def load_config(self):
        self.__set_checker()
        self.__config = load_config(self.__metadata)
        self.__is_loaded = True

    def save_config(self):
        self.__set_checker()
        save_config(self.__metadata, self.__config)


def save_config[T: BaseModel](metadata: ConfigLoaderMetadata[T], config: T):
    filepath = os.path.join(metadata.location, metadata.filename)
    with open(filepath, "w+", encoding="utf-8") as fp:
        fp.write(config.model_dump_json(indent=4))


def load_config[T: BaseModel](metadata: ConfigLoaderMetadata[T]):
    filepath = os.path.join(metadata.location, metadata.filename)
    if os.path.isfile(filepath):
        with open(filepath, "rb") as fp:
            return metadata.model.model_validate_json(fp.read())
    return metadata.model()
