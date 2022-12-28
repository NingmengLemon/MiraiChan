from .. import requester
#import requester
import json
import random
import time
import os
from loguru import logger
import atexit
import re

cache = []
cache_file = './cache/setu_cache.json'
if os.path.exists('./cache/'):
    if os.path.exists(cache_file):
        cache = json.load(open(cache_file,'r',encoding='utf-8',errors='ignore'))
else:
    os.mkdir('./cache/')
history_path_req = './data/setu_history/jsons/'
if not os.path.exists(history_path_req):
    os.makedirs(history_path_req,exist_ok=True)

#弃用
#https://dev.iw233.cn/API/index.php
async def iw233_api(n=5):#max=100
    api = random.choice([
        'https://iw233.cn/api.php?sort=iw233&type=json&num={n}',
        'http://ap1.iw233.cn/api.php?sort=iw233&type=json&num={n}',
        'http://api.iw233.cn/api.php?sort=iw233&type=json&num={n}',
        'https://dev.iw233.cn/api.php?sort=iw233&type=json&num={n}'
        ]).format(n=n)
    #经ping测试，没有一个可以连接
    data = json.loads(await requester.aget_content_str(api))
    return data['pic']
#返回的直接就是图片url数组，图床是sinaimg.cn

async def lolicon_api(n=10):#max=20
    #https://api.lolicon.app/#/setu
    api = f'https://api.lolicon.app/setu/v2?r18=0&num={n}'#&tag=%E8%90%9D%E8%8E%89|%E5%B0%91%E5%A5%B3&exclueAI=true'
    data = json.loads(await requester.aget_content_str(api))
    assert not bool(data['error']),data['error']
    return data['data']

lolicon_notes = '''
字段名	数据类型	说明
pid	int	作品 pid
p	int	作品所在页
uid	int	作者 uid
title	string	作品标题
author	string	作者名（入库时，并过滤掉 @ 及其后内容）
r18	boolean	是否 R18（在库中的分类，不等同于作品本身的 R18 标识）
width	int	原图宽度 px
height	int	原图高度 px
tags	string[]	作品标签，包含标签的中文翻译（有的话）
ext	string	图片扩展名
aiType	number	是否是 AI 作品，0 未知（旧画作或字段未更新），1 不是，2 是
uploadDate	int	作品上传日期；时间戳，单位为毫秒
urls	object	包含了所有指定size的图片地址
'''

async def lolisuki_api(n=5):#max=5
    #https://lolisuki.cc/#/setu
    api = f'https://lolisuki.cc/api/setu/v1?r18=0&num={n}&level=0-2&taste=0'
    data = json.loads(await requester.aget_content_str(api))
    assert data['code']==0,data['error']
    return data['data']

lolisuki_notes = '''
字段名	数据类型	说明
pid	int	作品 pid
p	int	作品所在页
total	int	作品包含的图片数量
uid	int	作者 uid
author	string	作者名称
level	int	社保级别，详见 level 说明
taste	int	图片类型，详见 taste 说明，这里0表示未分类
title	string	作品标题
description	string	作品描述
r18	boolean	是否包含 R-18 标签
gif	boolean	是否动图，即包含动图标签
original	boolean	是否原图，pixiv 作品中返回的一个标识
width	int	原图宽度 px
height	int	原图高度 px
ext	string	图片扩展名
uploadDate	int	作品上传日期；时间戳，单位为毫秒
urls	object	作品所在页的4种尺寸的图片地址
fullUrls	object[]	作品所有页的4种尺寸的图片地址
tags	string[]	作品标签，包含标签的中文翻译（有的话）
extags	string[]	扩展标签，指本人额外添加的标签（如果有空添加的话）
'''

@atexit.register
def save_cache():
    json.dump(cache,open(cache_file,'w+',encoding='utf-8',errors='ignore'))

async def fetch():
    global cache
    rc = random.randint(2,3)
    flag = {#1:'iw233',
            2:'lolicon',
            3:'lolisuki'
            }[rc]
    
    filename = str(time.time())+'_'+flag+'.json'
    #if rc == 1:
    #    data = await iw233_api()
    #el
    if rc == 2:
        data = await lolicon_api()
    else:
        data = await lolisuki_api()
    json.dump(data,open(os.path.join(history_path_req,filename),'w+',encoding='utf-8',errors='ignore'))
    cache += data
    logger.debug('Fetched setu data from {}, {} left in lib'.format(flag,len(cache)))

async def get():
    global cache
    if not cache:
        return None,'后台数据库为空，请等待后台刷新，然后重新找咱要涩图(´;ω;`)'
    data = cache.pop(len(cache)-1)
    #if type(data) == str:
    #    return data,f'图源：{data}\n没有附加信息\nTechnical support by iw233'
    #el
    url = data['urls']['original']
    url_cut = '/'+url.split('/',3)[-1]
    if 'taste' in data: #taste字段为lolisuki api特有，故以此区分
        return url,'''URL：{url}
PixivID：{pid}
Lv.{level}
Author：{uid}（{author}）
Size：{width}x{height}
Tags：\n#'''.format(**data,url=url_cut)+'# #'.join(data['tags'])+'#\nTechnical support by Lolisuki'
    else:
        return url,'''URL：{url}
PixivID：{pid}
Author：{uid}（{author}）
Size：{width}x{height}
Tags：\n#'''.format(**data,url=url_cut)+'# #'.join(data['tags'])+'#\nTechnical support by Lolicon'
