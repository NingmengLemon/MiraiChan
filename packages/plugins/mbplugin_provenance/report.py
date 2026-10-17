"""把检测结果整理成回给群里的文本。

只做字符串拼接, 方便单测; 不依赖 melobot。
"""

from collections.abc import Sequence

from .client import ProvenanceResult

__all__ = ["format_report"]

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
