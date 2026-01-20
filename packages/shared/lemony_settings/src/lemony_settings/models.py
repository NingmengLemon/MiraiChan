import textwrap
from typing import Any

from pydantic import BaseModel, Field, ValidationInfo, model_validator


class BaseSettings(BaseModel):
    # 给所有设置模型定义一个基类, 以便于类型检查和识别.
    # 每个字段都需要有一个默认值, 以确保设置模型可以被正确初始化.
    def model_post_init(self, context: Any) -> None:
        return super().model_post_init(context)


class LemonySettings[SettingModelT: BaseSettings](BaseModel):
    identifier: str = Field(
        description=textwrap.dedent(
            """
            设置的唯一标识符. 遵循变量名命名规范.
            插件名/模块名, etc.
            """,
        ).strip(),
        frozen=True,
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*$",
    )
    namespace: str = Field(
        default="default",
        description=textwrap.dedent(
            """
            设置的命名空间.
            用于区分同一插件/模块的不同设置文件.
            """,
        ).strip(),
        frozen=True,
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*$",
    )
    # 试图初始化两个 (id, namespace) 相同的 LemonySettings 实例, 会导致冲突.
    # 此时应该抛出异常. (在更上层)

    model: type[SettingModelT] = Field(
        description=textwrap.dedent(
            """
            设置值的模型类型.
            用于反序列化和验证.
            """,
        ).strip(),
        frozen=True,
    )
    value: SettingModelT = Field(
        default=None,  # type: ignore
        # 这个值将在下面的 model_validator 中依据 model 字段的值被正确初始化.
        description=textwrap.dedent(
            """
            设置的值.
            模型由使用此设置的插件或模块定义.
            """,
        ).strip(),
        frozen=True,
        validate_default=False,
    )

    @model_validator(mode="before")
    @classmethod
    def _init_value(cls, data: dict[str, Any], info: ValidationInfo) -> dict[str, Any]:
        if not issubclass((model := data["model"]), BaseSettings):
            raise TypeError("model must be a subclass of BaseSettings")
        # 不允许直接把 BaseSettings 作为 model 类型.
        if model is BaseSettings:
            raise TypeError(
                "model cannot be BaseSettings directly, inherit a subclass instead"
            )

        # 如果 value 是 None, 则使用 model 的默认值初始化.
        # 这就是为什么 BaseSettings 的字段必须有默认值.
        if (value := data.get("value")) is None:
            try:
                model_instance = model()
            except Exception as e:
                raise ValueError(
                    f"Failed to initialize value with default model: {e}"
                ) from e
            data["value"] = model_instance
        elif not isinstance(value, model):
            raise TypeError(f"Expected value of type {model}, got {type(value)}")
        return data


class GlobalSettings(BaseModel):
    auto_save: bool = Field(
        default=True,
        description=textwrap.dedent(
            """
            是否启用自动保存功能.
            启用后, 当设置值被修改时, 会自动保存到配置文件中.
            """,
        ).strip(),
    )
    auto_reload: bool = Field(
        default=False,
        description=textwrap.dedent(
            """
            是否启用自动重载功能.
            启用后, 当设置值在配置文件中被修改时, 会自动重新加载.
            """,
        ).strip(),
    )


# 最终期望的文件目录结构:
# configs/  # 或许可以接收命令行参数来指定别的目录
#   global.toml
#   plugin_a/ # identifier
#     a.toml  # namespace.toml
#     b.toml
#   plugin_b/
#     c.toml
#   module_x/
#     x.toml


SETTINGS_TABLE: dict[tuple[str, str], LemonySettings] = {}


def require[T: BaseSettings](
    identifier: str, model: type[T], namespace: str = "default"
) -> T:
    """
    获取一个 LemonySettings 实例. 如果不存在则创建一个新的实例并返回其值.
    """
    key = (identifier, namespace)
    if key not in SETTINGS_TABLE:
        setting = LemonySettings(
            identifier=identifier,
            namespace=namespace,
            model=model,
        )
        SETTINGS_TABLE[key] = setting
    return SETTINGS_TABLE[key].value
