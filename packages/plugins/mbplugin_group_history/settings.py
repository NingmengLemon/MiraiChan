"""群史问答的配置"""

from __future__ import annotations

from lemony_settings import BaseSettings
from pydantic import Field

__all__ = ["GroupHistorySettings"]


class GroupHistorySettings(BaseSettings):
    alias: str = Field(
        default="chat",
        description="用哪个模型别名回答, 对应 LLMSettings 里 aliases 的键",
    )
    max_rounds: int = Field(
        default=4,
        ge=1,
        le=8,
        description="工具调用的最大轮数, 超过就按已有信息收尾",
    )
    max_tokens: int = Field(default=2048, gt=0, description="单次回答的输出上限")
    window_days: int = Field(
        default=30, ge=1, description="默认回溯多少天, 模型可以显式指定更短或更长"
    )
    max_window_days: int = Field(
        default=365, ge=1, description="单次检索允许回溯的上限, 防止全库扫描"
    )
    result_limit: int = Field(
        default=20, ge=1, le=100, description="单次检索最多返回多少条"
    )
    max_tool_chars: int = Field(
        default=3000, ge=200, description="单个工具结果回给模型的字符上限"
    )
    max_answer_chars: int = Field(
        default=200,
        ge=50,
        description="回答超过这个长度就转成合并转发; 默认按手机上一屏来算",
    )
    timezone: str = Field(
        default="Asia/Shanghai",
        description="展示发言时间与理解「昨晚」这类相对时间时用的时区",
    )
    cooldown_seconds: int = Field(
        default=30, ge=0, description="同一群两次提问的最小间隔"
    )
    enabled_groups: list[int] = Field(
        default_factory=list,
        description="允许使用的群号, 留空表示所有群都允许",
    )
