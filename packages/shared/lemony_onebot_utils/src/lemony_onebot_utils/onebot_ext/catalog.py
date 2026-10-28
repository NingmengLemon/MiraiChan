"""实现端扩展清单

不是每个实现端都支持同一批扩展, 支持情况也随版本变化。这份表是"我们实际看过源码/实测过"的记录,
插件按需选用; 模块本身不做能力探测, 遇到不支持的 action 用 :func:`try_extension` 退让即可。

条目里的 ``impls`` 只写有证据的来源, ``notes`` 记录还没核实完的传闻, 避免把"应该支持"写成事实。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = ["EXTENSIONS", "ExtensionSpec", "find", "for_impl"]

ExtensionKind = Literal["action", "event", "segment"]

#: 目前核对过的实现端标识
IMPLS = ("snowluma", "napcat", "lagrange")


@dataclass(frozen=True, slots=True)
class ExtensionSpec:
    name: str
    kind: ExtensionKind
    summary: str
    impls: tuple[str, ...] = ()
    notes: str = ""
    source: str = ""

    def supported_by(self, impl: str) -> bool:
        return impl in self.impls


def _a(
    name: str,
    summary: str,
    *,
    impls: tuple[str, ...] = ("snowluma",),
    notes: str = "",
    source: str = "snowluma",
) -> ExtensionSpec:
    return ExtensionSpec(name, "action", summary, impls, notes, source)


def _e(
    name: str,
    summary: str,
    *,
    impls: tuple[str, ...] = ("snowluma",),
    notes: str = "",
    source: str = "snowluma",
) -> ExtensionSpec:
    return ExtensionSpec(name, "event", summary, impls, notes, source)


def _s(
    name: str,
    summary: str,
    *,
    impls: tuple[str, ...] = ("snowluma",),
    notes: str = "",
    source: str = "snowluma",
) -> ExtensionSpec:
    return ExtensionSpec(name, "segment", summary, impls, notes, source)


_ITEMS = [
    # actions: 表情回应
    _a(
        "set_msg_emoji_like",
        "在一条消息上添加或移除表情回应",
        notes="参数 message_id / emoji_id / set; emoji_id 是 Unicode 码位字符串",
    ),
    _a(
        "set_group_reaction",
        "给群消息贴一个 QQ 表情 (code 为表情编号)",
        notes="参数 group_id / message_id / code / is_set",
    ),
    # actions: 拍一拍与历史
    _a("friend_poke", "拍一拍好友", impls=("snowluma", "lagrange")),
    _a("group_poke", "拍一拍群成员", impls=("snowluma", "lagrange")),
    _a("get_group_msg_history", "拉取群消息历史"),
    _a("get_friend_msg_history", "拉取好友消息历史"),
    # actions: 群文件
    _a("upload_group_file", "上传群文件"),
    _a("upload_private_file", "上传私聊文件"),
    _a("create_group_file_folder", "新建群文件夹"),
    _a("get_group_root_files", "列出群文件根目录"),
    _a("get_group_files_by_folder", "列出群文件夹内容"),
    _a("get_group_file_url", "获取群文件下载地址"),
    # actions: 精华消息
    _a("set_essence_msg", "设为精华消息"),
    _a("delete_essence_msg", "移出精华消息"),
    _a("get_essence_msg_list", "列出精华消息"),
    # actions: 自定义表情
    _a("fetch_custom_face", "列出收藏的表情", impls=("snowluma", "lagrange")),
    # events
    _e(
        "group_msg_emoji_like",
        "群消息被贴表情回应",
        notes="notice_type=group_msg_emoji_like; sub_type 为 add/remove, likes 里带 emoji_id 与 count",
    ),
    _e(
        "group_card",
        "群名片变更通知",
        notes="NapCat 也有同名字段, 未在 SnowLuma 之外的实现上实测",
    ),
    _e("bot_offline", "bot 掉线通知"),
    _e(
        "message_sent",
        "bot 自己发出的消息 (post_type=message_sent)",
        notes="melobot 目前把它当未知 post_type 的通用事件, 用 event.raw 读",
    ),
    # segments
    _s("mface", "商城表情消息段", notes="解析优先用 lemony_mface, 这里只登记形状"),
    _s("poke", "拍一拍消息段", notes="通常同时伴随 notify 事件"),
    _s("flash_file", "闪传文件消息段"),
    _s("forward", "合并转发引用段", notes="发送侧用 send_group_forward_msg 的 nodes"),
]

#: 名称 -> 条目; 同一名称在 action/event/segment 里重名时加后缀区分, 目前没有冲突
EXTENSIONS: dict[str, ExtensionSpec] = {item.name: item for item in _ITEMS}


def find(name: str) -> ExtensionSpec | None:
    return EXTENSIONS.get(name)


def for_impl(impl: str) -> tuple[ExtensionSpec, ...]:
    """某个实现端有证据支持的扩展"""
    return tuple(spec for spec in EXTENSIONS.values() if spec.supported_by(impl))
