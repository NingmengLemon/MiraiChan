"""lemony_mface 的识别规则。

样本形态取自实测上报 (标识符已替换为构造值):
SnowLuma 输出带 emoji_id 的 image 段, 随后是一条与 summary 相同的 text 段。
"""

import pytest
from lemony_mface import (
    MFace,
    MFaceBlocklist,
    is_summary_echo,
    mface_image_url,
    parse_mface,
)

EMOJI_ID = "ab" + "0" * 30
URL = mface_image_url(EMOJI_ID)

SNOWLUMA_IMAGE = {
    "file": f"ab-{EMOJI_ID}.gif",
    "url": URL,
    "summary": "[喵喵消息]",
    "sub_type": 0,
    "emoji_id": EMOJI_ID,
    "emoji_package_id": 248907,
    "key": "k" * 16,
}


def test_url_shape() -> None:
    assert URL == (
        f"https://gxh.vip.qq.com/club/item/parcel/item/ab/{EMOJI_ID}/raw300.gif"
    )


def test_snowluma_image_segment_is_mface() -> None:
    mf = parse_mface("image", SNOWLUMA_IMAGE)
    assert mf == MFace(
        emoji_id=EMOJI_ID,
        package_id=248907,
        summary="[喵喵消息]",
        key="k" * 16,
        url=URL,
    )


def test_dedicated_mface_segment() -> None:
    mf = parse_mface(
        "mface",
        {"emoji_id": EMOJI_ID.upper(), "emoji_package_id": "1234", "summary": "[哈]"},
    )
    assert mf is not None
    assert (mf.emoji_id, mf.package_id, mf.url) == (EMOJI_ID, 1234, URL)


def test_image_with_only_mface_url_is_recognized() -> None:
    mf = parse_mface("image", {"file": "x.gif", "url": URL})
    assert mf is not None
    assert (mf.emoji_id, mf.package_id, mf.summary) == (EMOJI_ID, None, None)


@pytest.mark.parametrize(
    ("seg_type", "data"),
    [
        ("image", {"file": "x.png", "url": "https://multimedia.nt.qq.com.cn/x"}),
        ("image", {"url": "https://gxh.vip.qq.com/other/path"}),
        # 目录与 id 前两位不一致, 不是合法的表情地址
        ("image", {"url": URL.replace("/item/ab/", "/item/cd/")}),
        ("image", {"emoji_id": "not-hex", "url": "https://example.invalid/a.png"}),
        ("text", {"text": "[喵喵消息]", "emoji_id": EMOJI_ID}),
        ("face", {"id": "1"}),
    ],
)
def test_non_mface(seg_type: str, data: dict) -> None:
    assert parse_mface(seg_type, data) is None


def test_zero_package_id_means_unknown() -> None:
    mf = parse_mface("image", {**SNOWLUMA_IMAGE, "emoji_package_id": 0})
    assert mf is not None and mf.package_id is None


def test_summary_echo() -> None:
    mf = parse_mface("image", SNOWLUMA_IMAGE)
    assert mf is not None
    assert is_summary_echo(mf, "text", {"text": "[喵喵消息]"})
    assert not is_summary_echo(mf, "text", {"text": "[喵喵消息] 真的吗"})
    assert not is_summary_echo(mf, "image", {"text": "[喵喵消息]"})


def test_blocklist() -> None:
    blocked = parse_mface("image", SNOWLUMA_IMAGE)
    unknown = parse_mface("image", {"url": URL})
    assert blocked is not None and unknown is not None
    bl = MFaceBlocklist([248907])
    assert blocked in bl
    assert unknown not in bl
    assert "248907" not in bl
