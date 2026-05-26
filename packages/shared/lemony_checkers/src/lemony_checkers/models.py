"""
权限检查器的配置模型.

使用 lemony_settings 进行配置管理.
"""

import textwrap
from dataclasses import dataclass, make_dataclass
from functools import lru_cache
from typing import Annotated, Any, Generic, Literal, Self, get_args, get_origin

from lemony_settings import BaseSettings
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    SerializeAsAny,
    field_validator,
    model_validator,
)
from typing_extensions import TypeVar

from .exceptions import LemonyInternalImplError, LemonyProgrammingError

PCT = TypeVar("PCT", bound=str)
OB11_PROTOCOL_IDENTIFIER = "OneBot-v11@Meloland"
type Constraint = dict[str, list[Any]]

_UNIQUE_USER_MODEL_REGISTRY: list[
    tuple[type["UniqueUserDataclassBase"], type["UniqueUserBase"]]
] = []
_UNIQUE_USER_PROTOCOL_REGISTRY: dict[str, type["UniqueUserBase"]] = {}


def _extract_literal_protocol(protocol_annotation: Any) -> str | None:
    """从 UniqueUserBase 子类的 protocol 注解中提取唯一协议字符串."""
    origin = get_origin(protocol_annotation)
    if origin is Literal:
        args = get_args(protocol_annotation)
        if len(args) == 1 and isinstance(args[0], str):
            return args[0]
    if origin is not None:
        for arg in get_args(protocol_annotation):
            if (protocol := _extract_literal_protocol(arg)) is not None:
                return protocol
    return None


def _validate_unique_user_config(value: Any) -> "UniqueUserBase":
    """按 protocol 字段将配置数据恢复为具体 UniqueUserBase 子类."""
    if isinstance(value, UniqueUserBase):
        data = value.model_dump()
    elif isinstance(value, dict):
        data = value
    else:
        raise TypeError(f"Invalid unique user config item: {value!r}")

    protocol = data.get("protocol")
    if not isinstance(protocol, str):
        raise ValueError("Unique user config item must contain string field 'protocol'")

    model = _UNIQUE_USER_PROTOCOL_REGISTRY.get(protocol)
    if model is None:
        raise ValueError(f"No UniqueUser model registered for protocol {protocol!r}")
    return model.model_validate(data)


UniqueUserConfig = Annotated[
    SerializeAsAny["UniqueUserBase"],
    BeforeValidator(_validate_unique_user_config),
]

# 寻思是这样的
# 因为 pydantic model 太大坨了不适合高频使用 (真的吗?)
# 于是用 frozen slotted dataclass 当作轻量级替代
# pydantic model 只用于配置中

# 协议适配器的典型实现方法参见
# .adapters.ob11


@dataclass(slots=True, weakref_slot=True, frozen=True)
class UniqueUserDataclassBase(Generic[PCT]):
    @classmethod
    @lru_cache(1)
    def get_pydantic_model(cls) -> type["UniqueUserBase[PCT]"]:
        for dataclass_type, pydantic_type in _UNIQUE_USER_MODEL_REGISTRY:
            if dataclass_type is cls:
                return pydantic_type
        raise LemonyInternalImplError(f"No pydantic model found for {cls}")

    @classmethod
    def from_kwargs(cls, **data: Any) -> Self:
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {field: getattr(self, field) for field in self.__dataclass_fields__}

    def to_tuple(self) -> tuple[Any, ...]:
        return tuple(getattr(self, field) for field in self.__dataclass_fields__)


class UniqueUserBase(BaseModel, Generic[PCT]):
    model_config = ConfigDict(frozen=True)
    protocol: PCT

    @classmethod
    def __pydantic_on_complete__(cls) -> None:
        super().__pydantic_on_complete__()
        # 跳过参数化的基类自身 (如 UniqueUserBase[Literal[...]]), 只处理具体子类
        if cls is globals().get("UniqueUserBase"):
            return
        if cls.__module__ == __name__ and cls.__name__.startswith("UniqueUserBase["):
            return
        if len(getattr(cls, "__parameters__", ())) > 0:
            return
        cls._register_unique_user_model()

    @classmethod
    def _register_unique_user_model(cls) -> None:
        inherited_fields: set[str] = set()
        for base in cls.__mro__[1:]:
            inherited_fields.update(getattr(base, "model_fields", {}))

        extra_fields = set(cls.model_fields) - inherited_fields
        if not extra_fields:
            raise LemonyProgrammingError(
                f"{cls.__name__} must declare at least 1 field more than its parent"
            )

        dataclass_type = cls.get_dataclass()
        if (dataclass_type, cls) not in _UNIQUE_USER_MODEL_REGISTRY:
            _UNIQUE_USER_MODEL_REGISTRY.append((dataclass_type, cls))
        protocol = _extract_literal_protocol(cls.model_fields["protocol"].annotation)
        if protocol is not None:
            existing = _UNIQUE_USER_PROTOCOL_REGISTRY.get(protocol)
            if existing is not None and existing is not cls:
                raise LemonyProgrammingError(
                    f"Duplicate UniqueUser model for protocol {protocol!r}: "
                    f"{existing} and {cls}"
                )
            _UNIQUE_USER_PROTOCOL_REGISTRY[protocol] = cls

    @classmethod
    @lru_cache(1)
    def get_dataclass(cls) -> type[UniqueUserDataclassBase[PCT]]:
        return make_dataclass(
            cls_name=cls.__name__,
            fields=[
                (name, field.annotation, field)
                for name, field in cls.model_fields.items()
            ],
            bases=(UniqueUserDataclassBase,),
            slots=True,
            weakref_slot=True,
            frozen=True,
        )


class Rule(BaseModel):
    """
    权限规则.

    规则按顺序应用, 直到匹配为止.
    """

    action: Literal["allow", "deny"] = Field(
        description="规则的动作, 允许或拒绝.",
    )
    # None -> 无条件匹配
    # 不为 None 时, 外层列表中任意一个 constraint 匹配即可；单个 constraint 内各字段为 AND 关系。
    constrains: list[Constraint] | None = None
    protocol: str = Field(
        description="适用此规则的协议. 需要先在 adapter 中注册 extractor. "
        "通常可以从 protocol.const 中找到, 比如 "
        "melobot.protocols.onebot.v11.const.PROTOCOL_IDENTIFIER",
    )

    @field_validator("constrains", mode="before")
    @classmethod
    def _migrate_single_constraint(cls, value: Any) -> Any:
        # 兼容本次改动前的 {field: [values]} 形态。
        if value is None:
            return None
        if isinstance(value, dict):
            return [value]
        return value


def _legacy_ob11_user_config(user_id: int) -> dict[str, Any]:
    return {
        "protocol": OB11_PROTOCOL_IDENTIFIER,
        "user_id": user_id,
        "group_id": None,
    }


def _legacy_ob11_rule(
    action: Any, constrains: dict[str, list[int]] | None
) -> dict[str, Any]:
    return {
        "action": action,
        "protocol": OB11_PROTOCOL_IDENTIFIER,
        "constrains": constrains,
    }


def _migrate_legacy_rules(value: Any, *, rule_priority: str = "group_first") -> Any:
    if not isinstance(value, dict):
        return value
    if "user_rules" not in value and "group_rules" not in value:
        return value

    user_rules: list[dict[str, Any]] = []
    for raw_rule in value.get("user_rules") or []:
        if not isinstance(raw_rule, dict):
            user_rules.append(raw_rule)
            continue
        ids = raw_rule.get("ids")
        constrains = None if ids is None else {"user_id": ids}
        user_rules.append(_legacy_ob11_rule(raw_rule.get("action"), constrains))

    group_rules: list[dict[str, Any]] = []
    for raw_rule in value.get("group_rules") or []:
        if not isinstance(raw_rule, dict):
            group_rules.append(raw_rule)
            continue
        ids = raw_rule.get("ids")
        constrains = None if ids is None else {"group_id": ids}
        group_rules.append(_legacy_ob11_rule(raw_rule.get("action"), constrains))

    if rule_priority == "user_first":
        return [*user_rules, *group_rules]
    return [*group_rules, *user_rules]


def _migrate_legacy_unique_user_list(value: Any) -> Any:
    if value is None:
        return []
    if isinstance(value, int):
        return [_legacy_ob11_user_config(value)]
    if isinstance(value, list):
        return [
            _legacy_ob11_user_config(item) if isinstance(item, int) else item
            for item in value
        ]
    return value


class CheckerGlobalSettings(BaseSettings):
    """
    权限检查器的全局配置.

    保存在 configs/lemony_checkers/global.{format} 中.
    """

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_config(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        migrated = dict(data)
        if "owner" in migrated:
            migrated["owner"] = _migrate_legacy_unique_user_list(migrated["owner"])
        if "admins" in migrated:
            migrated["admins"] = _migrate_legacy_unique_user_list(migrated["admins"])
        if "rules" in migrated:
            migrated["rules"] = _migrate_legacy_rules(
                migrated["rules"],
                rule_priority=str(migrated.get("rule_priority", "group_first")),
            )
        return migrated

    mode: Literal["whitelist", "blacklist"] = Field(
        default="blacklist",
        description=textwrap.dedent(
            """
            全局配置的模式, 决定未在规则中明确指定时的默认行为.
            - whitelist: 默认拒绝, 仅允许在规则中明确允许的操作.
            - blacklist: 默认允许, 仅禁止在规则中明确禁止的操作.
            """
        ).strip(),
    )
    owner: list[UniqueUserConfig] = Field(
        default_factory=list,
        description="机器人所有者的ID列表. 无视所有权限检查, 始终通过.",
    )
    admins: list[UniqueUserConfig] = Field(
        default_factory=list,
        description=textwrap.dedent(
            """
            机器人的管理员ID列表. 拥有较高权限, 可在插件中自定义处理.
            """
        ).strip(),
    )
    rules: list[Rule] = Field(
        default_factory=list,
        description=textwrap.dedent(
            """
            全局权限规则. 优先于插件特定规则.
            规则按顺序应用, 直到匹配为止.
            """
        ).strip(),
    )


class CheckerPluginSettings(BaseSettings):
    """
    插件特定的权限配置.

    每个插件可以有自己的配置文件, 保存在 configs/lemony_checkers/{plugin_name}.{format} 中.
    """

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_config(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        migrated = dict(data)
        if "rules" in migrated:
            migrated["rules"] = _migrate_legacy_rules(
                migrated["rules"],
                rule_priority=str(migrated.get("rule_priority", "group_first")),
            )
        return migrated

    enabled: bool = Field(
        default=True,
        description="插件是否启用. 禁用后所有请求都会被拒绝.",
    )
    mode: Literal["whitelist", "blacklist"] | None = Field(
        default=None,
        description=textwrap.dedent(
            """
            插件的权限模式. 为 None 时使用全局配置的模式.
            - whitelist: 默认拒绝, 仅允许在规则中明确允许的操作.
            - blacklist: 默认允许, 仅禁止在规则中明确禁止的操作.
            """
        ).strip(),
    )
    rules: list[Rule] = Field(
        default_factory=list,
        description=textwrap.dedent(
            """
            插件特定的权限规则.
            在全局规则之后应用, 用于细粒度的权限控制.
            """
        ).strip(),
    )
    commands: dict[str, bool] = Field(
        default_factory=dict,
        description=textwrap.dedent(
            """
            插件内各命令的启用状态映射.
            键为命令名称, 值为布尔值表示是否启用该命令.
            未列出的命令默认启用.
            """
        ).strip(),
    )
