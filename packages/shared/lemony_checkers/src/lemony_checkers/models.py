"""
权限检查器的配置模型.

使用 lemony_settings 进行配置管理.
"""

import textwrap
from typing import Literal

from lemony_settings import BaseSettings
from pydantic import BaseModel, Field


class Rule(BaseModel):
    """
    权限规则.

    规则按顺序应用, 直到匹配为止.
    """

    action: Literal["allow", "deny"] = Field(
        description="规则的动作, 允许或拒绝.",
    )
    ids: list[int] | None = Field(
        default=None,
        description="适用此规则的用户或群组ID列表. 为 None 表示匹配所有. 空列表表示的是空规则.",
    )


class RuleSet(BaseModel):
    """
    规则集合, 包含用户规则和群组规则.
    """

    user_rules: list[Rule] = Field(
        default_factory=list,
        description="用户规则列表. 按顺序匹配用户ID, 在私聊和群聊中都适用.",
    )
    group_rules: list[Rule] = Field(
        default_factory=list,
        description="群组规则列表. 按顺序匹配群组ID, 仅在群聊中适用.",
    )


class CheckerGlobalSettings(BaseSettings):
    """
    权限检查器的全局配置.

    保存在 configs/lemony_checkers/global.{format} 中.
    """

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
    owner: int | None = Field(
        default=None,
        description="机器人所有者的QQ号. 无视所有权限检查, 始终通过.",
    )
    admins: list[int] = Field(
        default_factory=list,
        description=textwrap.dedent(
            """
            机器人的管理员QQ号列表. 拥有较高权限, 可在插件中自定义处理.
            """
        ).strip(),
    )
    rules: RuleSet = Field(
        default_factory=RuleSet,
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
    rules: RuleSet = Field(
        default_factory=RuleSet,
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
