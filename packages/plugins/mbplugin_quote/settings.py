from typing import Literal

from lemony_settings import BaseSettings
from pydantic import BaseModel, Field

__all__ = ["QuoteSettings"]

# 旧 MomoQuote 默认屏蔽的表情包
_LEGACY_BANNED_STICKER_SETS = [231182, 231412, 231764, 239439, 239546, 239871]


class ChatSettings(BaseModel):
    max_offset: int = Field(default=25, ge=0, description="区间端点绝对值上限")
    max_scale: float = Field(default=3.0, gt=0)
    max_canvas_pixels: int = Field(default=4096 * 8192, gt=0)
    banned_sticker_sets: list[int] = Field(
        default_factory=lambda: list(_LEGACY_BANNED_STICKER_SETS),
        description="被屏蔽的商城表情包 id, 屏蔽后画成替代文本",
    )


class ArchiveSettings(BaseModel):
    format: Literal["jpeg", "png", "webp"] = "jpeg"
    quality: int = Field(default=85, ge=1, le=100, description="jpeg / webp 质量")


class LimitSettings(BaseModel):
    same_target_cooldown: float = Field(
        default=600, ge=0, description="同一目标 (群, 消息, 样式, 参数) 的冷却秒数"
    )
    user_cooldown: float = Field(default=10, ge=0, description="同一用户的冷却秒数")
    render_workers: int = Field(default=1, ge=1, le=8)
    max_pending: int = Field(default=4, ge=1, description="排队上限, 超出时回复正忙")
    fetch_timeout: float = Field(default=10, gt=0)
    max_image_bytes: int = Field(default=20 * 1024 * 1024, gt=0)


class QuoteSettings(BaseSettings):
    font: str = Field(
        default="fonts/NotoSansSC-Medium.ttf", description="字体文件, 相对 data 根目录"
    )
    emoji_cdn: str | None = Field(
        default=None,
        description="emoji 图片服务地址 (EmojiServer), 不配置时 emoji 用字体字形",
    )
    allow_quote_self: bool = Field(default=False, description="能否引用 bot 自己的消息")
    show_timing: bool = Field(default=False, description="回复里附带耗时")
    chat: ChatSettings = Field(default_factory=ChatSettings)
    archive: ArchiveSettings = Field(default_factory=ArchiveSettings)
    limits: LimitSettings = Field(default_factory=LimitSettings)
