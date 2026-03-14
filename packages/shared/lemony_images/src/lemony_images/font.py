from collections.abc import Iterable
from contextlib import contextmanager
from contextvars import ContextVar

from PIL import ImageFont

from .typedef import _FontFileT


class FontCache:
    """因为发现 ImageDraw.text 方法中的 font_size 参数不起效，
    于是弄了个这样的类来做字体缓存"""

    def __init__(
        self, font_file: _FontFileT, preload_sizes: Iterable[int] | None = None
    ):
        self._font_file = font_file
        self._font_map: dict[int, ImageFont.FreeTypeFont] = {}
        if preload_sizes:
            for size in preload_sizes:
                self._font_map[size] = ImageFont.truetype(font_file, size=size)

    def use(self, size: int):
        size = int(size)
        if size not in self._font_map:
            self._font_map[size] = ImageFont.truetype(self._font_file, size=size)
        return self._font_map[size]

    @contextmanager
    def usec(self, size: int):
        yield self.use(size=size)

    def __getitem__(self, key: int):
        return self.use(key)


# 延迟加载，毕竟这个字体文件有点大
_default_font_cache: ContextVar[FontCache | None] = ContextVar(
    "lemony_images_default_font_cache", default=None
)


def get_default_font_cache() -> FontCache:
    instance = _default_font_cache.get()
    if instance is None:
        raise RuntimeError(
            "Default font cache not initialized. Call init_default_font_cache first."
        )
    return instance


def init_default_font_cache(
    font_file: _FontFileT,
    preload_sizes: Iterable[int] | None = None,
) -> FontCache:
    existing = _default_font_cache.get()
    if existing is not None:
        return existing
    instance = FontCache(font_file, preload_sizes=preload_sizes)
    _default_font_cache.set(instance)
    return instance


def _reset_for_testing() -> None:
    """将全局 FontCache 实例重置为 None.

    **仅供测试使用.** 在每个需要重新初始化的测试用例前调用.
    生产代码中禁止调用此函数.

    Example::

        def setup_function():
            lemony_images.font._reset_for_testing()
    """
    _default_font_cache.set(None)
