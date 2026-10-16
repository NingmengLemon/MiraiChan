import pytest
from lemony_images import (
    SchemeVariant,
    contrast_ratio,
    readable_tone,
    scheme_from_color,
    source_color,
    source_colors,
    tone_of,
)
from lemony_images.dynamic_color import argb_to_rgba, rgba_to_argb
from PIL import Image

RED = (200, 50, 50, 255)
PANEL = (19, 19, 21, 255)


def test_argb_roundtrip() -> None:
    assert rgba_to_argb((0x12, 0x34, 0x56, 0xFF)) == 0xFF123456
    assert argb_to_rgba(0xFF123456) == (0x12, 0x34, 0x56, 0xFF)
    assert rgba_to_argb((1, 2, 3)) == 0xFF010203


@pytest.mark.parametrize(
    "image",
    [
        Image.new("RGB", (64, 64), (128, 128, 128)),
        Image.new("RGB", (64, 64), (0, 0, 0)),
        Image.new("RGBA", (64, 64), (0, 0, 0, 0)),
        # 半透明像素不参与统计
        Image.new("RGBA", (64, 64), (200, 50, 50, 128)),
    ],
)
def test_achromatic_image_has_no_source(image: Image.Image) -> None:
    assert source_color(image) is None
    assert source_colors(image) == []


def test_real_fallback_color_is_kept() -> None:
    # MCU 的回退色本身出现在图里时不能被当成"没取到"
    img = Image.new("RGB", (64, 64), (0x42, 0x85, 0xF4))
    assert source_color(img) == (0x42, 0x85, 0xF4, 255)


def test_small_colored_patch_wins_over_grey() -> None:
    img = Image.new("RGB", (64, 64), (128, 128, 128))
    img.paste((200, 50, 50), (0, 0, 8, 8))
    assert source_color(img) == RED


def test_tone_of_keeps_hue_and_hits_extremes() -> None:
    assert tone_of(RED, 0) == (0, 0, 0, 255)
    assert tone_of(RED, 100) == (255, 255, 255, 255)
    light = tone_of(RED, 80)
    assert light[0] > light[1] and light[0] > light[2]  # 仍是红色系


@pytest.mark.parametrize(
    "color", [RED, (255, 255, 0, 255), (40, 0, 60, 255), (19, 19, 21, 255)]
)
def test_readable_tone_meets_contrast(color: tuple[int, int, int, int]) -> None:
    out = readable_tone(color, background=PANEL, min_contrast=4.5)
    assert contrast_ratio(out, PANEL) >= 4.5
    assert out == readable_tone(color, background=PANEL, min_contrast=4.5)


def test_readable_tone_falls_back_to_black_or_white() -> None:
    # 中灰背景上任何明度都到不了 7:1, 取黑白中更好的那个
    grey = (119, 119, 119, 255)
    out = readable_tone(RED, background=grey, min_contrast=7)
    assert out in {(0, 0, 0, 255), (255, 255, 255, 255)}


def test_scheme_roles_and_variants() -> None:
    dark = scheme_from_color(RED)
    assert dark.is_dark and dark.variant is SchemeVariant.CONTENT
    assert {"primary", "on_primary", "surface", "on_surface"} <= set(dark)
    assert all(len(c) == 4 and c[3] == 255 for c in dark.values())
    # MD3 保证 on_x 与 x 的对比度
    assert contrast_ratio(dark["on_surface"], dark["surface"]) >= 4.5
    light = scheme_from_color(RED, dark=False, variant=SchemeVariant.TONALSPOT)
    assert light["primary"] != dark["primary"]
    # 所有变体都能构造
    for v in SchemeVariant:
        assert scheme_from_color(RED, variant=v).variant is v
