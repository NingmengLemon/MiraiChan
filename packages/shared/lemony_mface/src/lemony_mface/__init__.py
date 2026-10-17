"""QQ 商城表情 (mface) 的识别、URL 与屏蔽表。

不同 OneBot 实现上报商城表情的方式不同:

- Lagrange 等: ``mface`` 段, 字段 ``emoji_id`` / ``emoji_package_id`` / ``key`` / ``summary``;
- SnowLuma: ``image`` 段, 额外挂同名字段, 发送时也凭 ``emoji_id`` 认回商城表情;
- 字段被丢弃的 ``image`` 段: 只剩指向 ``gxh.vip.qq.com/club/item/parcel/item/`` 的 url。

``parse_mface`` 把这几种统一成 :class:`MFace`。本模块只做纯计算, 不做网络与磁盘 IO。
"""

from .core import (
    MFACE_HOST,
    MFace,
    MFaceBlocklist,
    is_summary_echo,
    mface_image_url,
    mface_package_url,
    parse_mface,
)

__all__ = [
    "MFACE_HOST",
    "MFace",
    "MFaceBlocklist",
    "is_summary_echo",
    "mface_image_url",
    "mface_package_url",
    "parse_mface",
]
