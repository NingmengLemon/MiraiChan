import json
import zlib,gzip
import os
import re
import sys
from io import BytesIO
from loguru import logger
import copy
import time
import functools
import aiohttp
import asyncio

import brotli

filter_emoji = False
user_name = os.getlogin()

fake_headers_get = {
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',  # noqa
    'Accept-Charset': 'UTF-8,*;q=0.5',
    'Accept-Encoding': 'gzip,deflate,sdch',
    'Accept-Language': 'en-US,en;q=0.8',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/79.0.3945.74 Safari/537.36 Edg/79.0.309.43',  # noqa
}

fake_headers_post = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/79.0.3945.74 Safari/537.36 Edg/79.0.309.43'
    }

timeout = 15
retry_time = 3

def _replaceChr(text):
    repChr = {'/':'／',
              '*':'＊',
              ':':'：',
              '\\':'＼',
              '>':'＞',
              '<':'＜',
              '|':'｜',
              '?':'？',
              '"':'＂'}
    for t in list(repChr.keys()):
        text = text.replace(t,repChr[t])
    return text

def _ungzip(data):
    """Decompresses data for Content-Encoding: gzip.
    """
    buffer = BytesIO(data)
    f = gzip.GzipFile(fileobj=buffer)
    return f.read()

def _undeflate(data):
    """Decompresses data for Content-Encoding: deflate.
    (the zlib compression is used.)
    """
    decompressobj = zlib.decompressobj(-zlib.MAX_WBITS)
    return decompressobj.decompress(data)+decompressobj.flush()

def _unbrotli(data):
    return brotli.decompress(data)

def _dict_to_headers(dict_to_conv):
    keys = list(dict_to_conv.keys())
    values = list(dict_to_conv.values())
    res = []
    for i in range(len(keys)):
        res.append((keys[i],values[i]))
    return res

def _decode_data(data,encoding):
    if encoding == 'gzip':
        data = _ungzip(data)
    elif encoding == 'deflate':
        data = _undeflate(data)
    elif encoding == 'br':
        data = _unbrotli(data)
    return data

#Async Operation
async def aget_content_bytes(url,headers=fake_headers_get):
    async with aiohttp.ClientSession(headers=headers,timeout=aiohttp.ClientTimeout(total=timeout)) as session:
        async with session.get(url=url) as response:
            content = await response.read()
            #content = _decode_data(content,response.headers['content-encoding'])
            return content

async def apost_data_bytes(url,data,headers=fake_headers_post):
    async with aiohttp.ClientSession(headers=headers,timeout=aiohttp.ClientTimeout(total=timeout)) as session:
        async with session.post(url=url,data=data) as response:
            content = await response.read()
            #content = _decode_data(content,response.headers['content-encoding'])
            return content

async def aget_content_str(url,headers=fake_headers_get,encoding='utf-8'):
    content = await aget_content_bytes(url,headers=headers)
    return content.decode(encoding, 'ignore')

async def apost_data_str(url,data,headers=fake_headers_post,encoding='utf-8'):
    content = await aget_content_bytes(url,data=data,headers=headers)
    return content.decode(encoding, 'ignore')
