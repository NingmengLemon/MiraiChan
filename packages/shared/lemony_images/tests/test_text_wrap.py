"""按宽度断行: 不劈开词、遵守 CJK 禁则、超宽单元才硬断。

宽度都用真实字体量, 断言里出现的数字要么由 ``getlength`` 算出来, 要么留足余量,
免得换一个字体大小就整片失败。
"""

import math
import unicodedata
from typing import cast

import pytest
from lemony_images.text import line_width, wrap_text_by_width
from PIL import ImageFont

_WORD = "The quick brown fox jumps over the lazy dog"
_EMOJI_FAMILY = "👨\u200d👩\u200d👧\u200d👦"
_LONG_PATH = "E:\\" + "a" * 60 + "\\x.py"


def _words(lines: list[str]) -> list[str]:
    """按行切词: 词被劈开时切出来的碎片会和原文对不上"""
    return [word for line in lines for word in line.split()]


def _widths(
    lines: list[str], font: ImageFont.FreeTypeFont, *, emoji_as_square: bool
) -> list[float]:
    return [line_width(line, font, emoji_as_square=emoji_as_square) for line in lines]


class _KernFont:
    """测 kerning 用的假字体: 每个相邻字符对都吃掉 3px

    Pillow 自带的默认字体没有 kerning, 真实字体才看得出"跨 emoji 簇分别量"和
    "整段量"的差别, 所以这里造一个必然有 kerning 的测量函数。
    """

    size = 20

    def getlength(self, text: str) -> float:
        if not text:
            return 0.0
        return 12.0 * len(text) - 3.0 * (len(text) - 1)


def test_wraps_at_word_boundaries(font: ImageFont.FreeTypeFont) -> None:
    """逐字符断行会把词劈开, 这里要求切出来的词和原文完全一致"""
    limit = font.getlength("The quick brown")
    lines = wrap_text_by_width(_WORD, limit, font)
    assert len(lines) > 1
    assert _words(lines) == _WORD.split()


def test_a_word_that_fits_on_its_own_line_is_never_split(
    font: ImageFont.FreeTypeFont,
) -> None:
    """宽度只差一个尾随空格时, 词要整行挪下去, 不能就地劈开"""
    # 判据若把"词 + 会被丢掉的空格"算进宽度, 就会落进这个窗口
    limit = math.ceil(font.getlength("hello"))
    assert limit < font.getlength("hello ")
    lines = wrap_text_by_width("a hello b", limit, font)
    assert "hello" in lines


def test_only_the_over_long_word_is_broken(font: ImageFont.FreeTypeFont) -> None:
    """普通词整体挪到下一行, 只有比整行还宽的词才硬断"""
    text = "alpha " + "x" * 40 + " omega"
    lines = wrap_text_by_width(text, font.getlength("alpha ") * 1.5, font)
    words = _words(lines)
    assert words[0] == "alpha"
    assert words[-1] == "omega"
    # 硬断出来的碎片全是同一个字母, 且拼起来正好是那 40 个 x, 一个不多一个不少
    assert sum(len(word) for word in words if set(word) == {"x"}) == 40


def test_numbers_are_not_split(font: ImageFont.FreeTypeFont) -> None:
    text = "value 3.14159 and 1,000,000 ok"
    lines = wrap_text_by_width(text, font.getlength("value 3.14159") * 0.8, font)
    assert len(lines) > 1
    assert _words(lines) == text.split()


def test_cjk_kinsoku_keeps_closing_punctuation_off_the_line_start(
    font: ImageFont.FreeTypeFont,
) -> None:
    text = "中" * 5 + "。" + "文" * 5
    limit = font.getlength("中" * 5)
    # 前提: 按字数机械地切, 第二行会以句号开头
    naive = [text[i : i + 5] for i in range(0, len(text), 5)]
    assert naive[1].startswith("。")
    lines = wrap_text_by_width(text, limit, font)
    assert len(lines) > 1
    assert not any(line.startswith("。") for line in lines)


def test_cjk_kinsoku_keeps_opening_bracket_off_the_line_end(
    font: ImageFont.FreeTypeFont,
) -> None:
    text = "中中（" + "文" * 6
    limit = font.getlength("中" * 3)
    # 前提: 机械切行时括号会落在行尾
    naive = [text[i : i + 3] for i in range(0, len(text), 3)]
    assert naive[0].endswith("（")
    lines = wrap_text_by_width(text, limit, font)
    assert len(lines) > 1
    assert not any(line.endswith("（") for line in lines)


def test_long_unbreakable_run_is_hard_broken(font: ImageFont.FreeTypeFont) -> None:
    limit = 200
    lines = wrap_text_by_width(_LONG_PATH, limit, font)
    assert len(lines) > 1
    assert "".join(lines) == _LONG_PATH  # 一个字符都不少
    assert max(_widths(lines, font, emoji_as_square=False)) <= limit


def test_a_stalled_input_does_not_spin(font: ImageFont.FreeTypeFont) -> None:
    """``E:`` 后面接超长路径时, 断点曾经会原地打转"""
    lines = wrap_text_by_width(_LONG_PATH, 100, font)
    assert lines[0].startswith("E:\\")  # 冒号后面还能塞字符, 不该空着
    assert max(_widths(lines, font, emoji_as_square=False)) <= 100


def test_soft_break_drops_the_whitespace(font: ImageFont.FreeTypeFont) -> None:
    limit = max(font.getlength("alpha"), font.getlength("omega")) + 2
    assert wrap_text_by_width("alpha    omega", limit, font) == ["alpha", "omega"]


def test_whitespace_between_words_is_dropped_on_both_sides(
    font: ImageFont.FreeTypeFont,
) -> None:
    """断点落在空白之前时, 那串空白一样不保留"""
    limit = math.ceil(font.getlength("English"))
    lines = wrap_text_by_width("中文    English", limit, font)
    assert lines == ["中文", "English"]


def test_trailing_whitespace_never_widens_a_line(
    font: ImageFont.FreeTypeFont,
) -> None:
    """行尾空白不画, 断行判据也按剥掉之后算, 否则画布会被撑宽"""
    assert wrap_text_by_width("abc   ", 1000, font) == ["abc"]
    assert wrap_text_by_width("A" + " " * 200, 1920, font) == ["A"]
    # 整行都是空白时退化成空行, 但一行都不能少
    assert wrap_text_by_width("   ", 1000, font) == [""]


def test_breaking_does_not_lose_characters(font: ImageFont.FreeTypeFont) -> None:
    text = "中" * 20 + "。" + "English words " * 3 + "结尾"
    lines = wrap_text_by_width(text, font.getlength("中文 English wor"), font)
    assert len(lines) > 1
    # 断点处的空白会被吃掉, 其余字符一个不少、顺序不变
    assert "".join("".join(lines).split()) == "".join(text.split())


def test_newlines_are_preserved(font: ImageFont.FreeTypeFont) -> None:
    assert wrap_text_by_width("ab\r\ncd", 1000, font) == ["ab", "cd"]
    assert wrap_text_by_width("A\n", 1000, font) == ["A", ""]
    assert wrap_text_by_width("\n", 1000, font) == ["", ""]


def test_a_combining_mark_stays_with_its_base(font: ImageFont.FreeTypeFont) -> None:
    text = "e\u0301" * 4
    lines = wrap_text_by_width(text, font.getlength("e\u0301") + 2, font)
    assert len(lines) > 1
    assert all(not unicodedata.combining(line[0]) for line in lines)
    # 也不能把组合符丢在断点上
    assert "".join(lines) == text


def test_emoji_clusters_are_never_split(font: ImageFont.FreeTypeFont) -> None:
    lines = wrap_text_by_width(_EMOJI_FAMILY * 4, 30, font, emoji_as_square=True)
    assert lines == [_EMOJI_FAMILY] * 4


def test_a_single_unit_wider_than_the_line_gets_its_own_line(
    font: ImageFont.FreeTypeFont,
) -> None:
    assert wrap_text_by_width("中文", 5, font) == ["中", "文"]
    assert wrap_text_by_width(_EMOJI_FAMILY, 10, font, emoji_as_square=True) == [
        _EMOJI_FAMILY
    ]


def test_emoji_mode_fills_the_line_after_the_cluster(
    font: ImageFont.FreeTypeFont,
) -> None:
    """emoji 模式下列表按方块算, 后面那串西文仍要按词/字符填满, 不能整串丢到下一行"""
    text = "⭐" + "a" * 60
    lines = wrap_text_by_width(text, 100, font, emoji_as_square=True)
    assert len(lines) > 1
    assert lines[0].startswith("⭐a")
    assert max(_widths(lines, font, emoji_as_square=True)) <= 100


def test_emoji_mode_keeps_kinsoku_at_a_cluster_boundary(
    font: ImageFont.FreeTypeFont,
) -> None:
    """簇边界可以断, 但不能因此把句号顶到行首"""
    limit = 35
    # 前提: "中⭐" 放得下, 所以不守禁则的话断点会落在 emoji 与句号之间
    assert line_width("中⭐", font, emoji_as_square=True) <= limit
    assert line_width("中⭐。", font, emoji_as_square=True) > limit
    lines = wrap_text_by_width("中⭐。", limit, font, emoji_as_square=True)
    assert len(lines) > 1
    assert not any(line.startswith("。") for line in lines)


def test_emoji_mode_measures_each_cluster_like_the_renderer() -> None:
    """跨 emoji 簇的 kerning 不能丢: 判据得等于 ``line_width``

    默认字体在 RAQM 下也有跨簇 kerning, 但幅度随字体版本变化; 这里用假字体把幅度
    固定下来, 测试就不会因为换了个字体而变成"刚好抓不到"。
    """
    kern = cast(ImageFont.FreeTypeFont, _KernFont())
    text = "A⭐VA"
    limit = 51
    # 前提: 把两侧文字并成一段量会得到 50, 逐簇量才是真实的 53
    assert kern.getlength("AVA") + kern.size <= limit
    assert line_width(text, kern, emoji_as_square=True) > limit
    lines = wrap_text_by_width(text, limit, kern, emoji_as_square=True)
    assert len(lines) > 1
    for line in lines:
        assert line_width(line, kern, emoji_as_square=True) <= limit


def test_emoji_mode_matches_plain_mode_without_emoji(
    font: ImageFont.FreeTypeFont,
) -> None:
    text = "中文 English 混排 test 12345"
    limit = font.getlength("中文 English 混")
    assert wrap_text_by_width(text, limit, font) == wrap_text_by_width(
        text, limit, font, emoji_as_square=True
    )


@pytest.mark.parametrize("emoji_as_square", [False, True])
def test_no_line_exceeds_the_limit(
    font: ImageFont.FreeTypeFont, *, emoji_as_square: bool
) -> None:
    """在各种宽度下都不许画出超宽的行 (最小宽度比最宽的字形还大, 所以没有例外)"""
    texts = [
        _WORD,
        "中" * 30 + "。" + "文" * 30,
        "E:\\" + "a" * 80 + "\\x.py",
        "mixed 中文 English 1234567890",
        f"a⭐b 中文{_EMOJI_FAMILY} mixed",
        "trailing spaces here" + " " * 40,
        "   leading and trailing   ",
    ]
    for limit in range(30, 400, 17):
        for text in texts:
            lines = wrap_text_by_width(
                text, limit, font, emoji_as_square=emoji_as_square
            )
            assert lines, f"limit={limit} 断出了空列表"
            for line in lines:
                width = line_width(line, font, emoji_as_square=emoji_as_square)
                assert width <= limit, f"limit={limit} 画出了 {width} 宽的行: {line!r}"
