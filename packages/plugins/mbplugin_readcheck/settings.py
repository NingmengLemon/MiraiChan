"""精读与核查的配置"""

from __future__ import annotations

from lemony_settings import BaseSettings
from pydantic import Field

__all__ = ["ReadCheckSettings"]


class ReadCheckSettings(BaseSettings):
    alias: str = Field(default="chat", description="用哪个模型别名")
    base_url: str = Field(
        default="https://api.deepseek.com",
        description="联网检索与抓取接口的地址, 默认 DeepSeek 官方",
    )
    api_key_ref: str = Field(
        default="readcheck.tools.api_key",
        description="检索与抓取用的凭据键名, 由 get_secret 解析",
    )
    timezone: str = Field(default="Asia/Shanghai", description="展示日期用的时区")
    max_rounds: int = Field(default=5, ge=1, le=10, description="工具调用最大轮数")
    max_tokens: int = Field(default=2048, gt=0, description="单次回答的输出上限")
    max_answer_chars: int = Field(
        default=200, ge=50, description="超过这个长度就转合并转发, 默认按手机一屏"
    )
    max_input_chars: int = Field(
        default=6000, ge=500, description="用户贴进来的正文最多带多少字给模型"
    )
    max_fetch_chars: int = Field(
        default=12000, ge=1000, description="抓回来的正文最多带多少字给模型"
    )
    search_count: int = Field(default=8, ge=1, le=20, description="每次检索返回多少条")
    cooldown_seconds: int = Field(
        default=30, ge=0, description="同一群两次使用的最小间隔"
    )
    enabled_groups: list[int] = Field(
        default_factory=list, description="允许使用的群号, 留空表示不限制"
    )
