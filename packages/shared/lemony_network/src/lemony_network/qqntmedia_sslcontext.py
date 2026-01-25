import ssl

__all__ = ["QQNTMEDIA_SSL_CONTEXT"]

# https://gist.github.com/pk5ls20/a2ded67daf09b38458d7d56e4c30b53f
# Normally access files under `https://multimedia.nt.qq.com.cn` using aiohttp
QQNTMEDIA_SSL_CONTEXT = ssl.create_default_context()
QQNTMEDIA_SSL_CONTEXT.set_ciphers("DEFAULT")
QQNTMEDIA_SSL_CONTEXT.options |= ssl.OP_NO_SSLv2
QQNTMEDIA_SSL_CONTEXT.options |= ssl.OP_NO_SSLv3
QQNTMEDIA_SSL_CONTEXT.options |= ssl.OP_NO_TLSv1
QQNTMEDIA_SSL_CONTEXT.options |= ssl.OP_NO_TLSv1_1
QQNTMEDIA_SSL_CONTEXT.options |= ssl.OP_NO_COMPRESSION
