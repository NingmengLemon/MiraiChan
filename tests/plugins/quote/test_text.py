import pytest
from mbplugin_quote.render.text import (
    draw_text_block,
    extract_emojis,
    fit_text,
    layout_text,
)
from PIL import Image, ImageFont


def font(size: int = 28) -> ImageFont.FreeTypeFont:
    f = ImageFont.load_default(size)
    assert isinstance(f, ImageFont.FreeTypeFont)
    return f


def line_texts(block) -> list[str]:
    return ["".join(r.text for r in line) for line in block.lines]


def test_hard_newlines_and_emoji_units() -> None:
    block = layout_text("ab😀\n👨‍👩‍👧", font())
    assert line_texts(block) == ["ab😀", "👨‍👩‍👧"]
    assert [r.is_emoji for r in block.lines[0]] == [False, True]
    # emoji 占一个字号宽
    assert block.line_widths[1] == 28


@pytest.mark.parametrize("width", [40, 90, 150, 333])
def test_wrapped_lines_fit_width(width: int) -> None:
    text = "the quick brown fox 跳过了懒狗 😀😀 jumps over the lazy dog" * 3
    block = layout_text(text, font(), max_width=width)
    assert len(block.lines) > 1
    assert all(w <= width for w in block.line_widths)
    # 断行不丢字 (行首软换行空格除外)
    assert "".join(line_texts(block)).replace(" ", "") == text.replace(" ", "")


def test_words_are_not_split_when_they_fit() -> None:
    block = layout_text("hello world", font(), max_width=font().getlength("hello w"))
    assert line_texts(block) == ["hello ", "world"]


def test_overlong_word_is_hard_split() -> None:
    block = layout_text("x" * 50, font(), max_width=100)
    assert all(w <= 100 for w in block.line_widths)
    assert "".join(line_texts(block)) == "x" * 50


def test_fit_text_shrinks_then_truncates() -> None:
    f, block = fit_text(
        "短", font, box_width=400, box_height=200, max_size=72, min_size=10
    )
    assert f.size == 72
    f, block = fit_text(
        "很长的文字" * 200,
        font,
        box_width=400,
        box_height=100,
        max_size=72,
        min_size=20,
    )
    assert f.size == 20
    assert block.height <= 100
    assert line_texts(block)[-1].endswith("…")
    assert all(w <= 400 for w in block.line_widths)


def test_extract_emojis() -> None:
    assert extract_emojis(["a😀", "b❤️", "c"]) == {"😀", "❤️"}


def test_draw_uses_provided_emoji_image() -> None:
    canvas = Image.new("RGBA", (200, 60), (255, 255, 255, 255))
    red = Image.new("RGBA", (64, 64), (255, 0, 0, 255))
    block = layout_text("😀", font(28))
    draw_text_block(
        canvas, (10, 10), block, font(28), fill=(0, 0, 0, 255), emojis={"😀": red}
    )
    top = 10 + (block.line_height - 28) // 2
    assert canvas.getpixel((10 + 14, top + 14)) == (255, 0, 0, 255)
    assert canvas.getpixel((150, 50)) == (255, 255, 255, 255)
