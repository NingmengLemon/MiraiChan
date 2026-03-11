from io import BytesIO
from urllib.parse import quote_plus

from pilmoji.source import HTTPBasedSource


class SelfHostSource(HTTPBasedSource):
    """因为神秘 pilmoji 不支持自定义 emoji 网络源所以自己写了

    ~~诸君，我喜欢 self-host~~"""

    STYLE = "google"

    def __init__(self, cdn: str):
        super().__init__()
        self._cdn = cdn.rstrip("/") + "/"

    def get_discord_emoji(self, id: int, /):
        return None

    def get_emoji(self, emoji: str, /):
        try:
            return BytesIO(
                self.request(self._cdn + quote_plus(emoji) + "?style=google")
            )
        except Exception:
            return None


# TODO: pilmoji 除了没有自定义源以外,
# 在某行中没有emoji外的其他内容时, 绘制的emoji的y轴会错位,
# 于是计划自己弄一个绘制工具, 届时将不需要 pilmoji 了, 现在先这样
