import textwrap
from typing import Literal

from pydantic import BaseModel, Field


class Rule(BaseModel):
    action: Literal["allow", "deny"] = Field(
        description="规则的动作, 允许或拒绝.",
    )

    ids: list[int] = Field(
        default_factory=list, description="适用此规则的用户或群组ID列表."
    )
    # 定义见下


class RuleConfig(BaseModel):
    private: list[Rule] = Field(default_factory=list, description="私聊相关的规则列表.")
    group: list[Rule] = Field(default_factory=list, description="群聊相关的规则列表.")


class GlobalConfig(BaseModel):
    mode: Literal["whitelist", "blacklist"] = Field(
        default="blacklist",
        description=textwrap.dedent(
            """
            全局配置的模式, 决定未在插件中指定配置时的默认行为. 可被插件配置覆盖.
            `whitelist`: 仅允许在规则中明确允许的操作.
            `blacklist`: 仅禁止在规则中明确禁止的操作.
            """,
        ).strip(),
    )
    owner: int | None = Field(
        default=None,
        description="机器人所有者的QQ号. 不可被插件配置覆盖. 无视所有权限检查.",
    )
    admins: list[int] = Field(
        default_factory=list,
        description=textwrap.dedent(
            """
            机器人的管理员列表. 不可被插件配置覆盖. 拥有较高权限.
            有一说一这个档位的权限定位有点尴尬, 看插件自己怎么用.
            """,
        ),
    )
    rules: RuleConfig = Field(
        default_factory=RuleConfig,
        description=textwrap.dedent(
            """
            全局权限规则列表. 优先于插件配置的规则列表.
            在此基础上每个插件可以有自己的规则列表, 用于细粒度的权限控制.
            """,
        ),
        # 按顺序应用规则, 直到匹配为止.
        # 如果没有规则匹配, 则根据 mode 决定允许或拒绝.
    )
    # deny_message 可以在初始化 checker 的时候通过 fail_cb 实现
    # 所以这里不需要再定义一个字段.


class PluginConfig(BaseModel):
    name: str = Field(
        description="插件名称, 用于标识插件的配置.",
    )
    mode: Literal["whitelist", "blacklist"] | None = Field(default=None)
    rules: RuleConfig = Field(
        default_factory=RuleConfig,
        description=textwrap.dedent(
            """
            插件特定的权限规则列表.
            优先于全局配置的规则列表.
            """,
        ),
    )

    commands: dict[str, bool] = Field(
        default_factory=dict,
        description=textwrap.dedent(
            """
            插件内各命令的启用状态映射.
            键为命令名称, 值为布尔值表示是否启用该命令.
            """,
        ),
    )
    # 插件在初始化 checker 的时候可以额外传入命令名来实现命令级别的启停控制
