from urllib import request, parse, error
import json
import zlib,gzip
import os
import re
import sys
import atexit
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
asynchttp_session = None

def auto_retry(retry_time=3):
    def retry_decorator(func):
        @functools.wraps(func)
        def wrapped(*args,**kwargs):
            _run_counter = 0
            while True:
                _run_counter += 1
                try:
                    return func(*args,**kwargs)
                except Exception as e:
                    logger.error('Unexpected Error occurred while executing function {}: '\
                                  '{}; Retrying...'.format(str(func),str(e)))
                    if _run_counter > retry_time:
                        raise e
        return wrapped
    return retry_decorator

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

def make_opener():
    opener = request.build_opener()
    return opener

@auto_retry(retry_time)
def _get_response(url, headers=fake_headers_get):
    # install cookies
    opener = make_opener()

    response = opener.open(
        request.Request(url, headers=headers), None, timeout=timeout
    )

    data = response.read()
    data = _decode_data(data,response.info().get('Content-Encoding'))
    response.data = data
    logger.debug('Get Response from: '+url)
    return response

@auto_retry(retry_time)
def _post_request(url,data,headers=fake_headers_post):
    opener = make_opener()
    params = parse.urlencode(data).encode()
    response = opener.open(request.Request(url,data=params,headers=headers), timeout=timeout)
    data = response.read()
    data = _decode_data(data,response.info().get('Content-Encoding'))
    response.data = data
    if len(str(params)) <= 50:
        logger.debug('Post Data to {} with Params {}'.format(url,str(params)))
    else:
        logger.debug('Post Data to {} with a very long params'.format(url))
    return response

def post_data_str(url,data,headers=fake_headers_post,encoding='utf-8'):
    content = _post_request(url,data,headers).data
    data = content.decode(encoding, 'ignore')
    return data

def post_data_bytes(url,data,headers=fake_headers_post,encoding='utf-8'):
    response = _post_request(url,data,headers)
    return response.data

def get_content_str(url, encoding='utf-8', headers=fake_headers_get):
    content = _get_response(url, headers=headers).data
    data = content.decode(encoding, 'ignore')
    return data

def get_content_bytes(url, headers=fake_headers_get):
    content = _get_response(url, headers=headers).data
    return content

def get_redirect_url(url,headers=fake_headers_get):
    return _get_response(url=url, headers=headers).geturl()

#Download Operation
def download_common(url,tofile,headers=fake_headers_get):
    opener = make_opener()
    chunk_size = 1024
    with opener.open(request.Request(url,headers=headers),timeout=timeout) as response:
        with open(tofile,'wb+') as f:
            while True:
                data = response.read(chunk_size)
                if data:
                    f.write(data)
                else:
                    break
    logger.debug('Download file from {} to {}.'.format(url,tofile))
            

def convert_size(size):#单位:Byte
    if size < 1024:
        return '%.2f B'%size
    size /= 1024
    if size < 1024:
        return '%.2f KB'%size
    size /= 1024
    if size < 1024:
        return '%.2f MB'%size
    size /= 1024
    return '%.2f GB'%size

#Async Operation
async def aget_content_bytes(url,headers=fake_headers_get):
    if asynchttp_session:
        async with asynchttp_session.get(url=url) as response:
            content = await response.read()
            return content
    else:
        async with aiohttp.ClientSession(headers=headers,timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            async with session.get(url=url) as response:
                content = await response.read()
                return content

async def apost_data_bytes(url,data,headers=fake_headers_post):
    if asynchttp_session:
        async with asynchttp_session.post(url=url,data=data) as response:
            content = await response.read()
            return content
    else:
        async with aiohttp.ClientSession(headers=headers,timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            async with session.post(url=url,data=data) as response:
                content = await response.read()
                return content

async def aget_content_str(url,headers=fake_headers_get,encoding='utf-8'):
    content = await aget_content_bytes(url,headers=headers)
    return content.decode(encoding, 'ignore')

async def apost_data_str(url,data,headers=fake_headers_post,encoding='utf-8'):
    content = await aget_content_bytes(url,data=data,headers=headers)
    return content.decode(encoding, 'ignore')
