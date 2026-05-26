import textwrap
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class BaseSettings(BaseModel):
    """
    所有设置模型的基类.

    每个字段都需要有一个默认值, 以确保设置模型可以被正确初始化.
    """

    model_config = {"validate_assignment": True}


class PersistentGlobalSettings(BaseSettings):
    # 这些设定会保存到 configs/global.{preference} 文件中.
    auto_reload: bool = Field(
        default=False,
        description=textwrap.dedent(
            """
            是否启用自动重载功能.
            启用后, 当设置值在配置文件中被修改时, 会自动重新加载.
            """,
        ).strip(),
    )


class GlobalSettings(BaseSettings):
    # 分为可持久化的设置和非持久化的设置.
    # 可持久化的设置会被保存到配置文件中.
    preference: Literal["yaml", "json"] | str = Field(
        default="json",
        description=textwrap.dedent(
            """
            配置文件的首选格式.
            支持 'yaml', 'json'.
            """,
        ).strip(),
        frozen=True,
    )
    config_path: str | Path = Field(
        default="configs",
        description=textwrap.dedent(
            """
            配置文件的存储目录.
            """,
        ).strip(),
        frozen=True,
    )
    # 上述两个字段是非持久化的, 将在初始化时传入.
    # 比如, 开发者可以把它做成命令行参数传入.

    # 下面的字段是可持久化字段的数据模型.
    persistent: "PersistentGlobalSettings" = Field(
        default_factory=lambda: PersistentGlobalSettings(),
        description=textwrap.dedent(
            """
            全局设置的文件相关设置.
            """,
        ).strip(),
        frozen=False,  # frozen 不作用于嵌套模型的内容
    )
