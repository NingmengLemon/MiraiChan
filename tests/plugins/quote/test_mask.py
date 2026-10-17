"""遮罩参数的几何性质: 断言渐变的位置、宽度、倾斜与曲线, 不做像素金标。

默认参数 (0.113 / 0.257 / 0.191 / 0.5) 在卡宽 1920 时是顶边 217px 起、宽 493px、
底边右移 367px; 下面按这些像素值断言, 换掉默认值就该看见它们变化。
"""

import itertools

import pytest
from mbplugin_quote.render.mask import MaskCache, MaskStyle, build_mask
from mbplugin_quote.settings import MaskSettings
from PIL import Image


def alpha_at(mask: Image.Image, x: int, y: int) -> int:
    return mask.crop((x, y, x + 1, y + 1)).tobytes()[0]


def crossing(mask: Image.Image, y: int, level: int = 128) -> float:
    """第 y 行上 alpha 首次达到 level 的亚像素位置"""
    row = mask.crop((0, y, mask.width, y + 1)).tobytes()
    for x, v in enumerate(row):
        if v >= level:
            if x == 0:
                return 0.0
            lo = row[x - 1]
            return x - 1 + (level - lo) / (v - lo)
    raise AssertionError(f"第 {y} 行没有达到 {level}")


def test_mask_is_an_alpha_image_of_the_card() -> None:
    mask = build_mask((1920, 1080))
    assert mask.mode == "L"
    assert mask.size == (1920, 1080)
    # 左边全透明 (头像露出来), 右边全不透明 (深色底板)
    assert alpha_at(mask, 0, 540) == 0
    assert alpha_at(mask, 1919, 540) == 255


def test_fade_position_and_width_follow_the_style() -> None:
    style = MaskStyle(fade_from=0.25, fade_width=0.25, slant=0.0, curve=0.0)
    mask = build_mask((800, 400), style)
    # 直线过渡 (curve=0) 的 50% 点正好在渐变带中点, 无倾斜时每行都一样
    for y in (0, 200, 399):
        assert crossing(mask, y) == pytest.approx(800 * 0.375, abs=1.5)
    assert mask.crop((0, 0, 200, 400)).getextrema() == (0, 0)
    assert mask.crop((400, 0, 800, 400)).getextrema() == (255, 255)


def test_slant_shifts_the_band_down_the_card() -> None:
    style = MaskStyle(fade_from=0.1, fade_width=0.2, slant=0.2, curve=0.0)
    mask = build_mask((500, 250), style)
    assert crossing(mask, 0) == pytest.approx(500 * 0.2, abs=1.5)
    assert crossing(mask, 249) - crossing(mask, 0) == pytest.approx(500 * 0.2, abs=2)


def test_negative_slant_shifts_the_band_up_the_card() -> None:
    style = MaskStyle(fade_from=0.4, fade_width=0.2, slant=-0.2, curve=0.0)
    mask = build_mask((500, 250), style)
    assert crossing(mask, 249) - crossing(mask, 0) == pytest.approx(-500 * 0.2, abs=2)


@pytest.mark.parametrize("slant", [-1.0, -0.5, 0.0, 0.5, 1.0])
def test_every_row_fades_left_to_right(slant: float) -> None:
    """剪切后每行都得单调不降; 底图取样越界会被填成黑色, 这里能直接看见"""
    style = MaskStyle(fade_from=0.1, fade_width=0.2, slant=slant)
    mask = build_mask((320, 180), style)
    for y in range(0, 180, 15):
        row = mask.crop((0, y, 320, y + 1)).tobytes()
        assert all(a <= b for a, b in itertools.pairwise(row))


def test_curve_softens_both_ends() -> None:
    linear = build_mask(
        (600, 100), MaskStyle(fade_from=0.2, fade_width=0.4, slant=0.0, curve=0.0)
    )
    smooth = build_mask(
        (600, 100), MaskStyle(fade_from=0.2, fade_width=0.4, slant=0.0, curve=1.0)
    )
    start, width = 600 * 0.2, 600 * 0.4
    # 曲线的 S 形: 前 1/4 处更暗, 后 3/4 处更亮
    quarter = round(start + 0.25 * width)
    assert alpha_at(smooth, quarter, 50) < alpha_at(linear, quarter, 50)
    three_quarters = round(start + 0.75 * width)
    assert alpha_at(smooth, three_quarters, 50) > alpha_at(linear, three_quarters, 50)
    # 曲线只改过渡形状, 两端仍然是干净的 0 与 255
    for mask in (linear, smooth):
        assert alpha_at(mask, round(start), 50) == 0
        assert alpha_at(mask, round(start + width), 50) == 255


def test_default_style_reproduces_the_former_asset() -> None:
    mask = build_mask((1920, 1080))
    # 卡片原来那张图的位置: 顶边 5%/50%/95% 在 257/464/668, 底边 50% 在 830;
    # 现在的实现各处差 1px 以内 (465/669/831)
    assert crossing(mask, 0, 13) == pytest.approx(257, abs=3)
    assert crossing(mask, 0) == pytest.approx(464, abs=3)
    assert crossing(mask, 0, 242) == pytest.approx(668, abs=4)
    assert crossing(mask, 1079) == pytest.approx(830, abs=3)


def test_cache_redraws_only_when_size_or_style_changes() -> None:
    cache = MaskCache()
    first = cache.get((240, 120), MaskStyle())
    assert first.size == (240, 120)
    assert cache.get((240, 120), MaskStyle()) is first
    changed = cache.get((240, 120), MaskStyle(fade_from=0.3))
    assert changed is not first
    resized = cache.get((480, 240), MaskStyle())
    assert resized is not changed
    assert resized.size == (480, 240)


def test_mask_settings_convert_to_render_style() -> None:
    assert MaskSettings().to_style() == MaskStyle()
    style = MaskSettings(fade_from=0.5, fade_width=0.1, slant=0.0, curve=1.0).to_style()
    assert style == MaskStyle(fade_from=0.5, fade_width=0.1, slant=0.0, curve=1.0)
