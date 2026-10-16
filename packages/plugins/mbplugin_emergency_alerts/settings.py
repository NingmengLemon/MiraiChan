"""插件配置, 持久化在 configs/emergency_alerts/default.json"""

from __future__ import annotations

from lemony_settings import BaseSettings
from pydantic import Field

__all__ = ["AlertSettings"]


class AlertSettings(BaseSettings):
    ws_base_url: str = Field(
        default="wss://ws-api.wolfx.jp",
        description="Wolfx WebSocket 根地址; 本地调试可指向 tools/mock_wolfx_server.py",
    )
    endpoints: list[str] = Field(
        # all_eew 汇总所有预警; 两个速报端点单独连, 重复报文由去重处理
        default_factory=lambda: ["all_eew", "cenc_eqlist", "jma_eqlist"],
        description="要连接的端点, 每个端点一条连接",
    )
    eew_max_age_minutes: float = Field(
        default=10, gt=0, description="发报时间早于这么多分钟的预警不推送"
    )
    report_max_age_minutes: float = Field(
        default=60, gt=0, description="发报时间早于这么多分钟的速报不推送"
    )
    idle_timeout: float = Field(
        default=150, gt=0, description="这么多秒没有任何报文 (含心跳) 就重连"
    )
    send_interval: float = Field(
        default=0.5, ge=0, description="向多个会话推送时, 相邻两次发送的间隔秒数"
    )
