"""引用管线里 At 名字补全的调用约定: 只在有缺名字的 At 时才查, 查到的名字进入正文"""

import asyncio

from lemony_mface import MFaceBlocklist
from mbplugin_quote.model import SourceMessage, SourceSegment
from mbplugin_quote.pipeline import _normalize


def _msg(*segments: SourceSegment) -> SourceMessage:
    return SourceMessage("m1", 1, None, "甲", segments)


def test_member_names_fills_missing_at_names() -> None:
    calls: list[set[int]] = []

    async def lookup(uids: set[int]) -> dict[int, str]:
        calls.append(uids)
        return {3: "丙名片"}

    src = _msg(SourceSegment("at", {"qq": "3"}), SourceSegment("at", {"qq": "5"}))
    (qm,) = asyncio.run(_normalize([src], MFaceBlocklist(), lookup))
    assert calls == [{3, 5}]
    # 查不到的保持显示 QQ 号
    assert qm.text == "@丙名片 @5"


def test_member_names_not_called_when_nothing_missing() -> None:
    async def lookup(uids: set[int]) -> dict[int, str]:
        raise AssertionError("不该查")

    src = _msg(SourceSegment("at", {"qq": "1"}), SourceSegment("text", {"text": "hi"}))
    (qm,) = asyncio.run(_normalize([src], MFaceBlocklist(), lookup))
    assert qm.text == "@甲 hi"
