import pytest
from lemony_images.color import (
    average_color,
    contrast_ratio,
    darken,
    ensure_4inttuple_color,
    lighten,
    mix,
    readable_on,
    to_hex,
    with_alpha,
)
from PIL import Image

RED = (200, 50, 50, 255)


def test_convert_helpers() -> None:
    assert ensure_4inttuple_color("#c83232") == RED
    assert ensure_4inttuple_color(0xC83232) == RED
    assert to_hex(RED) == "#c83232"
    assert to_hex(with_alpha(RED, 0x80), alpha=True) == "#c8323280"
    with pytest.raises(ValueError):
        with_alpha(RED, 256)


def test_contrast_known_values() -> None:
    assert contrast_ratio((0, 0, 0), (255, 255, 255)) == pytest.approx(21)
    assert contrast_ratio(RED, RED) == pytest.approx(1)
    assert readable_on((19, 19, 21, 255)) == (255, 255, 255, 255)
    assert readable_on((240, 240, 240, 255)) == (0, 0, 0, 255)


def test_mix_endpoints_and_midpoint() -> None:
    white = (255, 255, 255, 255)
    assert mix(RED, white, 0) == RED
    assert mix(RED, white, 1) == white
    mid = mix(RED, white, 0.5)
    # OKLab 的中点比 sRGB 线性插值 (227, 152, 152) 更亮
    assert sum(mid[:3]) > 227 + 152 + 152
    assert mix((0, 0, 0, 0), white, 0.5)[3] == 128
    with pytest.raises(ValueError):
        mix(RED, white, 1.5)


def test_lighten_darken_keep_hue() -> None:
    light, dark = lighten(RED, 0.2), darken(RED, 0.2)
    assert sum(light[:3]) > sum(RED[:3]) > sum(dark[:3])
    for r, g, b, _ in (light, dark):
        assert r > g and r > b
    assert lighten(RED, 1) == (255, 255, 255, 255)
    assert darken(RED, 1) == (0, 0, 0, 255)


def test_average_color() -> None:
    img = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    assert average_color(img) is None
    img.paste((200, 50, 50, 255), (0, 0, 10, 5))
    img.paste((0, 0, 255, 255), (0, 5, 10, 10))
    assert average_color(img) == (100, 25, 152, 255)
