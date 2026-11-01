"""QQ NT 图床所需的 TLS 上下文; 首次真正下载时才构造."""

import ssl
from functools import lru_cache

__all__ = ["qqntmedia_ssl_context"]


# https://gist.github.com/pk5ls20/a2ded67daf09b38458d7d56e4c30b53f
# Normally access files under `https://multimedia.nt.qq.com.cn` using aiohttp
@lru_cache(maxsize=1)
def qqntmedia_ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.set_ciphers("DEFAULT")
    context.options |= ssl.OP_NO_SSLv2
    context.options |= ssl.OP_NO_SSLv3
    context.options |= ssl.OP_NO_TLSv1
    context.options |= ssl.OP_NO_TLSv1_1
    context.options |= ssl.OP_NO_COMPRESSION
    return context
