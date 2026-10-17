"""把检测结果整理成回给群里的文本。

只做字符串拼接, 方便单测; 不依赖 melobot。
"""

from collections.abc import Sequence

from .client import ProvenanceResult

__all__ = ["format_report", "summarize"]

_LABELS = {"c2pa": "C2PA 清单", "synthid": "SynthID"}


def _size_label(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{size / 1024:.1f} KB"


def _details(result: ProvenanceResult) -> str:
    parts: list[str] = []
    if result.issuer:
        parts.append(f"签发方={result.issuer}")
    if result.model:
        parts.append(f"模型={result.model}")
    if result.validation_state:
        parts.append(f"校验={result.validation_state}")
    if result.generated_at:
        parts.append(f"生成时间={result.generated_at}")
    return f" ({', '.join(parts)})" if parts else ""


def _one_line(result: ProvenanceResult) -> str:
    label = _LABELS.get(result.type, result.type)
    if result.outcome == "detected":
        return f"{label}: 检测到{_details(result)}"
    if result.outcome == "not_detected":
        return f"{label}: 未检测到"
    return f"{label}: {result.outcome}"


def format_report(
    index: int,
    total: int,
    *,
    mime: str,
    size: int,
    results: Sequence[ProvenanceResult],
) -> str:
    """单张图片的报告, 形如::

    图片 1/2 (image/png, 34.2 KB)
    C2PA 清单: 未检测到
    SynthID: 未检测到
    """
    lines = [f"图片 {index}/{total} ({mime}, {_size_label(size)})"]
    lines.extend(_one_line(r) for r in results)
    return "\n".join(lines)


def summarize(results: Sequence[ProvenanceResult]) -> str:
    """整条消息的结论, 附带"只覆盖 OpenAI 信号"的说明"""
    detected = [r for r in results if r.detected]
    if detected:
        kinds = ", ".join(_LABELS.get(r.type, r.type) for r in detected)
        return f"结论: 检测到 OpenAI 支持的生成痕迹 ({kinds})"
    return (
        "结论: 没有检测到 OpenAI 支持的来源信号。"
        "元数据被抹掉、水印被破坏或者是别家模型生成时也会是这个结果, 不代表一定不是 AI 生成。"
    )
