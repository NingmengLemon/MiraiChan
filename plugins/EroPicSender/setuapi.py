import json
import random
import time
import os
import logging
import atexit
import re
import asyncio
import threading
from ruamel import yaml as ruayml
import yaml

from pycqBot.socketApp import asyncHttp

cache = []
cache_lock = threading.Lock()
cache_file = './data/setu_cache.json'
if os.path.isfile(cache_file):
    cache = json.load(open(cache_file,'r',encoding='utf-8',errors='ignore'))

history_path_req = './data/setu_history/datapacks/'
if not os.path.exists(history_path_req):
    os.makedirs(history_path_req,exist_ok=True)

@atexit.register
def save_cache():
    json.dump(cache,open(cache_file,'w+',encoding='utf-8',errors='ignore'))

async def request(reqer:asyncHttp, url:str, **options):
    '''
    可用的options:
    mod:str="get", data:dict={}, json:bool=True,
    allow_redirects:bool=False, proxy:dict=None,
    headers:dict={}, encoding:str=None
    '''
    return await reqer.link(url,**options)

async def lolicon_api(reqer, n=20):
    data = await request(
        reqer, f'https://api.lolicon.app/setu/v2?r18=0&num={n}',
        mod='get', json=True
        )
    assert not bool(data['error']),data['error']
    return data['data']

async def fetch(reqer):
    global cache
    data = await lolicon_api(reqer)
    flag = 'lolicon'
    filename = str(time.time())+'_'+flag+'.yml'
    with open(os.path.join(history_path_req,filename),'w+',encoding='utf-8') as f:
        #json.dump(data,f)
        ruayml.dump(data,f,Dumper=ruayml.RoundTripDumper)
    with cache_lock:
        cache += data
    logging.debug('接收了 %s 个涩图数据, 缓存里现有 %s 个'%(len(data),len(cache)))

def get_datapack():
    global cache
    if cache:
        with cache_lock:
            data = cache.pop(
                random.randint(0,len(cache)-1)
                )
        return data
    else:
        return None

def get_msg():
    global cache
    if cache:
        with cache_lock:
            data = cache.pop(
                random.randint(0,len(cache)-1)
                )
        url = data['urls']['original']
        url_cut = '/'+url.split('/',3)[-1]
        msg = 'URL: '+url_cut
        msg += '''
PixivID: {pid}
Author: {uid} ({author})
Size: {width}x{height}
Tags:
#'''.format(**data)+'# #'.join(data['tags'])+'#'
        return url,msg
    else:
        return None,'后台缓存为空，请等待系统自动刷新'
