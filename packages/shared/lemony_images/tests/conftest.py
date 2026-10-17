"""文本相关的共享 fixture。

真实彩色字体不在仓库里, 这里把 Pillow 自带的字体落到临时目录, 好让断行与绘制
的测试按路径打开同一个字体文件。

只写一次: 字体文件被 FreeType 映射之后再截断同一条路径, Windows 会报 EINVAL。
"""

from io import BytesIO
from pathlib import Path

import pytest
from PIL import ImageFont


@pytest.fixture(scope="session")
def font_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """一个可用的字体文件路径"""
    path = tmp_path_factory.mktemp("font") / "default.otf"
    font = ImageFont.load_default(20)
    assert isinstance(font, ImageFont.FreeTypeFont)
    embedded = font.path
    if isinstance(embedded, BytesIO):
        path.write_bytes(embedded.getvalue())
        return path
    assert isinstance(embedded, str)
    return Path(embedded)


@pytest.fixture
def font(font_file: Path) -> ImageFont.FreeTypeFont:
    """按路径打开的字体, 字号 20"""
    return ImageFont.truetype(str(font_file), 20)
