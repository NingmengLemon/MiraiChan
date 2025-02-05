import ssl

# https://gist.github.com/pk5ls20/a2ded67daf09b38458d7d56e4c30b53f
# Normally access files under `https://multimedia.nt.qq.com.cn` using aiohttp
SSL_CONTEXT = ssl.create_default_context()
SSL_CONTEXT.set_ciphers("DEFAULT")
SSL_CONTEXT.options |= ssl.OP_NO_SSLv2
SSL_CONTEXT.options |= ssl.OP_NO_SSLv3
SSL_CONTEXT.options |= ssl.OP_NO_TLSv1
SSL_CONTEXT.options |= ssl.OP_NO_TLSv1_1
SSL_CONTEXT.options |= ssl.OP_NO_COMPRESSION
