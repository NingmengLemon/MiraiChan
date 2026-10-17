"""核验结果的文本格式。"""

from mbplugin_provenance.client import ProvenanceResult
from mbplugin_provenance.report import format_report, summarize


def _c2pa() -> ProvenanceResult:
    return ProvenanceResult(
        type="c2pa",
        outcome="detected",
        issuer="OpenAI OpCo, LLC",
        model="gpt-image-1",
        validation_state="trusted",
        generated_at="2026-07-27T18:34:12Z",
    )


def _synthid(outcome: str) -> ProvenanceResult:
    return ProvenanceResult(type="synthid", outcome=outcome, model="gpt-image-1")


def test_report_lists_each_signal_and_the_size() -> None:
    text = format_report(
        1,
        2,
        mime="image/png",
        size=int(34.2 * 1024),
        results=[ProvenanceResult("c2pa", "not_detected"), _synthid("not_detected")],
    )
    assert text.splitlines() == [
        "图片 1/2 (image/png, 34.2 KB)",
        "C2PA 清单: 未检测到",
        "SynthID: 未检测到",
    ]


def test_report_shows_the_details_of_a_detected_signal() -> None:
    text = format_report(
        1, 1, mime="image/png", size=2 * 1024 * 1024, results=[_c2pa()]
    )
    assert "图片 1/1 (image/png, 2.0 MB)" in text
    assert "C2PA 清单: 检测到 (签发方=OpenAI OpCo, LLC, 模型=gpt-image-1, " in text
    assert "校验=trusted" in text and "生成时间=2026-07-27T18:34:12Z" in text


def test_report_only_renders_the_signals_that_are_present() -> None:
    # 音频只有 synthid, 没有 c2pa 项
    text = format_report(
        2, 2, mime="audio/ogg", size=1024, results=[_synthid("detected")]
    )
    assert text.splitlines() == [
        "图片 2/2 (audio/ogg, 1.0 KB)",
        "SynthID: 检测到 (模型=gpt-image-1)",
    ]


def test_report_without_results_is_just_the_header() -> None:
    assert format_report(1, 1, mime="image/png", size=512, results=[]) == (
        "图片 1/1 (image/png, 0.5 KB)"
    )


def test_unknown_signal_type_is_labelled_by_its_name() -> None:
    text = format_report(
        1,
        1,
        mime="image/png",
        size=1024,
        results=[ProvenanceResult("future", "detected")],
    )
    assert "future: 检测到" in text


def test_summary_reports_detected_signals() -> None:
    assert summarize([_c2pa(), _synthid("not_detected")]) == (
        "结论: 检测到 OpenAI 支持的生成痕迹 (C2PA 清单)"
    )


def test_summary_is_careful_when_nothing_is_found() -> None:
    text = summarize([ProvenanceResult("c2pa", "not_detected")])
    assert text.startswith("结论: 没有检测到 OpenAI 支持的来源信号")
    assert "不代表一定不是 AI 生成" in text
