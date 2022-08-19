from .. import requester
#import requester
import json
import time
import threading
from loguru import logger
import os
import re

__all__ = ['query_text','query_data','fetch','afetch']

api_domestic = 'https://api.inews.qq.com/newsqa/v1/query/inner/publish/modules/list?modules=diseaseh5Shelf'
api_foreign = 'https://api.tianapi.com/ncovabroad/index?key=9336c2e9e1be9dbda6c22d641c2a9f06'
cache_domestic = None
cache_foreign = None

def timestamp_to_time(ts):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))

def fetch():
    global cache_domestic
    global cache_foreign
    data_do = json.loads(requester.get_content_str(api_domestic))['data']['diseaseh5Shelf']
    data_fo = json.loads(requester.get_content_str(api_foreign))['newslist']
    
    cache_domestic = data_do
    cache_foreign = data_fo

async def afetch():
    global cache_domestic
    global cache_foreign

    org_json_do = await requester.aget_content_str(api_domestic)
    cache_domestic = json.loads(org_json_do)['data']['diseaseh5Shelf']
    org_json_fo = await requester.aget_content_str(api_foreign)
    cache_foreign = json.loads(org_json_fo)['newslist']

def province_data_handler(data,parent,timestr):
    return {
        'name':data['name'],
        'parent':parent,
        'type':'province',
        'time':timestr,
        'confirmed_today':data['today']['confirm'],
        'total':{
            'confirmed':data['total']['confirm'],
            'death':data['total']['dead'],
            'cured':data['total']['heal']
            },
        'current':{
            'confirmed':data['total']['nowConfirm'],
            'localconfirmed':data['total']['provinceLocalConfirm']
            }
        }

def country_data_handler(data):
    return {
        'name':data['provinceName'],
        'parent':data['continents'],
        'type':'foreign',
        'time':timestamp_to_time(data['modifyTime']/1000),
        'total':{
            'confirmed':data['confirmedCount'],
            'cured':data['curedCount'],
            'death':data['deadCount']
            },
        'current':{
            'confirmed':data['currentConfirmedCount']
            },
        'rate_death':data['deadRate'],
        'rate_death_rank':data['deadRateRank'],
        'death_rank':data['deadCountRank']
        }

def query_data(area=None):
    if cache_domestic and cache_foreign:
        area = re.sub(r'[县省市区]','',area)
        data_do = cache_domestic.copy()
        if area != '中国' and area:
            for province in data_do['areaTree'][0]['children']:
                if area in province['name']:
                    return province_data_handler(province,'中国',data_do['lastUpdateTime'])
                if 'children' in province:
                    for place in province['children']:
                        if area in place['name'] and place['name'] not in ['地区待确认','境外输入']:
                            return province_data_handler(place,province['name'],data_do['lastUpdateTime'])
            data_fo = cache_foreign.copy()
            for country in data_fo:
                if country['provinceName'] == area:
                    return country_data_handler(country)
        else:
            incr = data_do['chinaAdd']
            total = data_do['chinaTotal']
            return {
                'name':'中国',
                'parent':None,
                'type':'domestic',
                'time':data_do['lastUpdateTime'],
                'increase':{
                    'confirmed_total':incr['confirm'],
                    'death_total':incr['dead'],
                    'cured_total':incr['heal'],
                    'confirmed_current':incr['nowConfirm'],
                    'symptomless_current':incr['noInfect'],
                    'localconfirmed_current':incr['localConfirmH5'],
                    'severe_current':incr['nowSevere'],
                    'imported_total':incr['importedCase']
                    },
                'current':{
                    'confirmed':total['nowConfirm'],
                    'symptomless':total['noInfect'],
                    'severe':total['nowSevere'],
                    'localconfirmed':total['localConfirmH5']
                    },
                'total':{
                    'confirmed':total['confirm'],
                    'death':total['dead'],
                    'cured':total['heal'],
                    'imported':total['importedCase']
                    }
                }
        return None
    else:
        return 'unloaded'

def query_text(area=None):
    data = query_data(area=area)
    if type(data) == dict:
        flag = data['type']
        if flag == 'domestic':
            total = data['total']
            increase = data['increase']
            current = data['current']
            return f'''国内疫情概况
更新时间：{data['time']}

累计确诊：{format(total['confirmed'],',')}（{format(increase['confirmed_total'],'+,')}）
累计死亡：{format(total['death'],',')}（{format(increase['death_total'],'+,')}）
累计治愈：{format(total['cured'],',')}（{format(increase['cured_total'],'+,')}）
累计境外输入：{format(total['imported'],',')}（{format(increase['imported_total'],'+,')}）
目前确诊：{format(current['confirmed'],',')}（{format(increase['confirmed_current'],'+,')}）
目前无症状：{format(current['symptomless'],',')}（{format(increase['symptomless_current'],'+,')}）
目前重症：{format(current['severe'],',')}（{format(increase['severe_current'],'+,')}）'''
        else:
            total = data['total']
            current = data['current']
            text = f'''{data['parent']} - {data['name']}
更新时间：{data['time']}

目前确诊：{format(current['confirmed'],',')}
累计确诊：{format(total['confirmed'],',')}
累计死亡：{format(total['death'],',')}
累计治愈：{format(total['cured'],',')}'''
            if flag == 'province':
                text += '\n今日新增：'+format(data['confirmed_today'],',')
            elif flag == 'foreign':
                text += '\n死亡率：{:.2%}\n死亡人数世界第{}\n死亡率世界第{}'.format(float(data['rate_death'])/10,data['rate_death_rank'],data['death_rank'])
            return text
    elif data == 'unloaded':
        return f'后台数据未加载'
    else:
        return f'没有名为 {area} 的地区，或该地区没有数据'
