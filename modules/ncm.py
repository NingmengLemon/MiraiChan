import os
import re
import sys
import time
import json
from io import BytesIO
import winreg
from bs4 import BeautifulSoup as BS
import logging
from . import requester
from functools import wraps

def get_info(mid):
    url = 'https://music.163.com/song?id={mid}'.format(mid=mid)
    bs = BS(requester.get_content_str(url),'html.parser')
    res = {
        'title':bs.find('em',class_='f-ff2').get_text(),
        'artists':[i.get_text() for i in bs.find_all('p',class_='des s-fc4')[0].find_all('a',class_='s-fc7')],
        'album':bs.find_all('p',class_='des s-fc4')[1].find('a',class_='s-fc7').get_text(),
        'album_id':int(bs.find_all('p',class_='des s-fc4')[1].find('a',class_='s-fc7').attrs['href'].split('?id=')[-1]),
        #'subtitle':bs.find('div',class_='subtit f-fs1 f-ff2').get_text(),
        'cover:':bs.find('img',class_='j-img').attrs['data-src']
        }
    return res

def get_album(aid):
    url = 'https://music.163.com/album?id={aid}'.format(aid=aid)
    bs = BS(requester.get_content_str(url),'html.parser')
    data = json.loads(bs.find('textarea',id='song-list-pre-data').get_text())
    res = {
        'music_list':[{
            'order':i['no'],
            'title':i['name'],
            'mid':i['id'],
            'artists':[a['name'] for a in i['artists']],
            } for i in data],
        'aid':aid,
        'title':bs.find('h2',class_='f-ff2').get_text(),
        'artists':[i.get_text() for i in bs.find('p',class_='intr').find_all('a',class_='s-fc7')]
        }
    return res

def search_music(*kws,limit=10,offset=0):
    url = 'https://music.163.com/api/search/get/?s={}&limit={}&type=1&offset={}'.format('+'.join([requester.parse.quote(kw) for kw in kws]),limit,offset)
    data = json.loads(requester.get_content_str(url))
    if 'songs' in data['result']:
        res = [{
            'mid':i['id'],'title':i['name'],
            'artists':[a['name'] for a in i['artists']],
            'album':i['album']['name'],
            'album_id':i['album']['id']
            #'trans_titles':i['transNames'],
            } for i in data['result']['songs']]
        return res
    else:
        return []

def get_lyrics(mid):
    api = f'https://music.163.com/api/song/lyric?id={str(mid)}&lv=1&kv=1&tv=-1'
    data = json.loads(requester.get_content_str(api))
    if 'lrc' in data:
        lyrics = data['lrc']['lyric']
        if 'tlyric' in data:
            if data['tlyric']['lyric'].strip():
                lyrics_trans = data['tlyric']['lyric']
            else:
                lyrics_trans = None
        else:
            lyrics_trans = None
    else:
        lyrics = lyrics_trans = None
    return lyrics,lyrics_trans
