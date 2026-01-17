import textwrap
from pathlib import Path
from typing import Literal, TypedDict

from melobot.utils import singleton
from pydantic import BaseModel, Field


class Rule(BaseModel):
    action: Literal["allow", "deny"] = Field(
        description="规则的动作, 允许或拒绝.",
    )
    command: str | None = Field(
        default=None,
        description="适用此规则的命令名称. 若为 None, 则适用于所有命令.",
    )
    ids: list[int] = Field(
        default_factory=list, description="适用此规则的用户或群组ID列表."
    )
    deny_message: str | None = Field(
        default=None,
        description="允许为单个规则指定拒绝消息, 覆盖全局配置.",
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
            `whitelist`: 仅允许在插件中明确允许的操作.
            `blacklist`: 仅禁止在插件中明确禁止的操作.
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
    deny_message: str | None = Field(
        default=None,
        description=textwrap.dedent(
            """
            当操作被拒绝时发送的消息内容.
            若为`None`, 则不发送任何消息. (静默拒绝)
            可被插件配置覆盖.
            """,
        ).strip(),
    )  # 可以被 checker 初始化时候传入的 deny_cb 覆盖


class PluginConfig(BaseModel):
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
    deny_message: str | None = Field(
        default=None,
        description=textwrap.dedent(
            """
            当操作被拒绝时发送的消息内容.
            若为`None`, 则不发送任何消息. (静默拒绝)
            优先于全局配置的 deny_message.
            """,
        ).strip(),
    )
