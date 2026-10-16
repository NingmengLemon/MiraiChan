"""把 ``Quake`` 渲染成推送文本."""

from __future__ import annotations

from .quake import CST, Quake

__all__ = ["render_quake", "render_test"]

DISCLAIMER = "信息来自 Wolfx 转发, 仅供参考, 以官方发布为准"


def _num(v: float | None, fmt: str = "g") -> str:
    return "未知" if v is None else format(v, fmt)


def _title(q: Quake) -> str:
    if q.is_cancel:
        return f"【取消】{q.info.name}"
    if q.kind == "eew":
        stage = "最终报" if q.is_final else f"第{q.seq}报"
        warn = " 警报" if q.is_warn else ""
        return f"【{q.info.name}{warn}】{stage}"
    stage = "自动测定" if q.automatic else "正式测定"
    return f"【{q.info.name}】{stage}"


def render_quake(q: Quake) -> str:
    """推送正文. 时间统一换算到北京时间, 日本源同时保留当地时间"""
    origin = q.origin_time.astimezone(CST).strftime("%Y-%m-%d %H:%M:%S")
    if q.info.tz is not CST:
        local = q.origin_time.strftime("%H:%M:%S")
        origin += f" (当地 {local})"
    lines = [
        _title(q),
        f"震中: {q.hypocenter}",
        f"发震时间: {origin}",
        f"震级: M{_num(q.magnitude)}",
    ]
    if q.depth is not None:
        lines.append(f"深度: {_num(q.depth)} km")
    if q.intensity is not None:
        label = "预估最大烈度" if q.kind == "eew" else "最大烈度"
        lines.append(f"{label}: {q.intensity:g}")
    if q.shindo is not None:
        lines.append(f"最大震度: {q.shindo}")
    if q.note:
        lines.append(q.note)
    if q.is_cancel:
        lines.append("此前的预警已被取消")
    lines.append(DISCLAIMER)
    return "\n".join(lines)


def render_test(conditions: str) -> str:
    return "\n".join(
        [
            "【测试】地震信息推送测试, 这不是真实地震",
            "本会话的订阅条件:",
            conditions,
            DISCLAIMER,
        ]
    )
