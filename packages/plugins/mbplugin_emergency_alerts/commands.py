"""``.预警`` 指令的解析与执行.

不依赖 bot 上下文: 输入当前会话、分词后的参数和权限判定结果, 输出回复文本以及
订阅是否被修改, 由插件入口负责保存与发送.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from .quake import QuakeKind
from .sources.wolfx import SOURCES
from .subscription import (
    KIND_LABELS,
    Subscription,
    SubscriptionStore,
    TargetKey,
    UpdatePolicy,
)

__all__ = ["HELP", "CommandError", "CommandResult", "execute"]

HELP = """\
地震预警订阅 (每个群聊 / 私聊一份订阅)
.预警 状态            查看本会话的订阅
.预警 订阅            按默认条件订阅 (或恢复已暂停的订阅)
.预警 暂停 / 退订
.预警 设置 <项> <值>  修改条件, 可用的项:
  种类  预警 / 速报 / 全部
  来源  数据源标识 (见 .预警 来源), 多个用空格分开; 全部
  地区  关键词, 匹配震源地 (如 四川 日本); 不限
  震级  最小震级, 如 4.5
  烈度  最小烈度 (中国源), 如 5; 不限
  震度  最小震度 (日本源), 如 5-; 不限
  更新  首报 / 最终 / 全部 (预警多报时推几次)
.预警 来源            列出数据源
.预警 测试            向本会话发一条测试推送"""

_ALL = {"全部", "all", "*"}
_NONE = {"不限", "none", "无", "all", "全部"}
_KIND_WORDS: dict[str, QuakeKind] = {
    "预警": "eew",
    "eew": "eew",
    "速报": "report",
    "report": "report",
}
_UPDATE_WORDS: dict[str, UpdatePolicy] = {
    "首报": "first",
    "first": "first",
    "最终": "final",
    "最终报": "final",
    "final": "final",
    "全部": "all",
    "每报": "all",
    "all": "all",
}


class CommandError(Exception):
    """直接回复给用户的错误"""


@dataclass(frozen=True, slots=True)
class CommandResult:
    reply: str
    changed: bool = False
    send_test: bool = False


def _one(values: Sequence[str], key: str) -> str:
    if len(values) != 1:
        raise CommandError(f"{key} 只接受一个值")
    return values[0]


def _float_or_none(values: Sequence[str], key: str) -> float | None:
    v = _one(values, key)
    if v.lower() in _NONE:
        return None
    try:
        return float(v)
    except ValueError:
        raise CommandError(f"{key} 需要一个数字, 收到 {v!r}") from None


def _set_kinds(values: Sequence[str]) -> dict[str, Any]:
    if any(v.lower() in _ALL for v in values):
        return {"kinds": ["eew", "report"]}
    try:
        return {"kinds": [_KIND_WORDS[v.lower()] for v in values]}
    except KeyError as e:
        raise CommandError(f"未知种类 {e.args[0]!r}, 可用: 预警 速报 全部") from None


def _set_sources(values: Sequence[str]) -> dict[str, Any]:
    if any(v.lower() in _ALL for v in values):
        return {"sources": []}
    return {"sources": [v.lower() for v in values]}


def _set_regions(values: Sequence[str]) -> dict[str, Any]:
    if any(v.lower() in _NONE for v in values):
        return {"regions": []}
    return {"regions": list(values)}


def _set_magnitude(values: Sequence[str]) -> dict[str, Any]:
    mag = _float_or_none(values, "震级")
    return {"min_magnitude": 0.0 if mag is None else mag}


def _set_intensity(values: Sequence[str]) -> dict[str, Any]:
    return {"min_intensity": _float_or_none(values, "烈度")}


def _set_shindo(values: Sequence[str]) -> dict[str, Any]:
    v = _one(values, "震度")
    return {"min_shindo": None if v.lower() in _NONE else v}


def _set_updates(values: Sequence[str]) -> dict[str, Any]:
    v = _one(values, "更新").lower()
    if v not in _UPDATE_WORDS:
        raise CommandError(f"未知更新策略 {v!r}, 可用: 首报 最终 全部")
    return {"updates": _UPDATE_WORDS[v]}


_SETTERS: dict[str, Callable[[Sequence[str]], dict[str, Any]]] = {}
for _names, _fn in (
    (("种类", "kinds"), _set_kinds),
    (("来源", "数据源", "sources"), _set_sources),
    (("地区", "regions"), _set_regions),
    (("震级", "mag", "magnitude"), _set_magnitude),
    (("烈度", "intensity"), _set_intensity),
    (("震度", "shindo"), _set_shindo),
    (("更新", "updates"), _set_updates),
):
    for _n in _names:
        _SETTERS[_n] = _fn


def _apply(sub: Subscription, key: str, values: Sequence[str]) -> Subscription:
    setter = _SETTERS.get(key.lower())
    if setter is None:
        raise CommandError(f"未知设置项 {key!r}, 发送 .预警 查看用法")
    if not values:
        raise CommandError(f"{key} 缺少值")
    try:
        return Subscription.model_validate({**sub.model_dump(), **setter(values)})
    except ValidationError as e:
        msgs = "; ".join(err["msg"].removeprefix("Value error, ") for err in e.errors())
        raise CommandError(f"设置无效: {msgs}") from None


def _sources_text() -> str:
    lines = ["数据源:"]
    for key, info in SOURCES.items():
        lines.append(f"  {key}  {info.name} ({KIND_LABELS[info.kind]})")
    return "\n".join(lines)


def _require_manage(can_manage: bool) -> None:
    if not can_manage:
        raise CommandError("只有群管理员或 bot 管理员可以修改本群的订阅")


def execute(
    store: SubscriptionStore,
    target: TargetKey,
    tokens: Sequence[str],
    *,
    can_manage: bool,
    status_extra: str = "",
) -> CommandResult:
    """执行一条 ``.预警`` 指令; 修改订阅时直接改 ``store``"""
    if not tokens or tokens[0].lower() in {"help", "帮助"}:
        return CommandResult(HELP)
    sub_cmd, rest = tokens[0].lower(), list(tokens[1:])
    current = store.get(target)

    match sub_cmd:
        case "状态" | "status":
            body = "本会话尚未订阅" if current is None else current.describe()
            return CommandResult(f"{body}\n{status_extra}".rstrip())
        case "来源" | "数据源" | "sources":
            return CommandResult(_sources_text())
        case "订阅" | "开启" | "on":
            _require_manage(can_manage)
            if current is not None and current.enabled:
                return CommandResult("本会话已经订阅了\n" + current.describe())
            sub = (
                current.model_copy(update={"enabled": True})
                if current is not None
                else Subscription(target_type=target[0], target_id=target[1])
            )
            store.upsert(sub)
            return CommandResult("已订阅\n" + sub.describe(), changed=True)
        case "暂停" | "关闭" | "off":
            _require_manage(can_manage)
            if current is None:
                raise CommandError("本会话尚未订阅")
            store.upsert(current.model_copy(update={"enabled": False}))
            return CommandResult("已暂停, 条件保留, 发送 .预警 订阅 恢复", changed=True)
        case "退订" | "删除" | "remove":
            _require_manage(can_manage)
            if not store.remove(target):
                raise CommandError("本会话尚未订阅")
            return CommandResult("已退订", changed=True)
        case "设置" | "set":
            _require_manage(can_manage)
            if not rest:
                raise CommandError("用法: .预警 设置 <项> <值>")
            created = current is None
            base = current or Subscription(target_type=target[0], target_id=target[1])
            sub = _apply(base, rest[0], rest[1:])
            store.upsert(sub)
            head = "已创建订阅并设置" if created else "已更新"
            return CommandResult(f"{head}\n{sub.describe()}", changed=True)
        case "测试" | "test":
            _require_manage(can_manage)
            return CommandResult("", send_test=True)
        case _:
            raise CommandError(f"未知子命令 {tokens[0]!r}, 发送 .预警 查看用法")
