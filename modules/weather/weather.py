from .. import requester
#import requester
import json
import time
import asyncio
from .cityid import cityid as cityid_sheet
#from cityid import cityid as cityid_sheet
from loguru import logger
import re

# https://www.sojson.com/blog/305.html
# 此接口每8小时更新一次
# 调用之间必须有一定间隔
api = 'http://t.weather.sojson.com/api/weather/city/{}'

cache = {} # cityid(str):请求数据
latest_query_time = 0 # 时间戳

def _single_day_handler(data):
    return {
        'aqi':data['aqi'],
        'day':int(data['date']), # 号数
        'wind_level':data['fl'], # e.g."1~2级"
        'wind_direction':data['fx'],# e.g."东北风"
        'temp_highest':int(data['high'][3:-1]), # 摄氏温标
        'temp_lowest':int(data['low'][3:-1]),
        'notice':data['notice'],
        'sunrise':data['sunrise'], # hh:mm
        'sunset':data['sunset'],
        'status':data['type'],
        'week':data['week'], # e.g."星期一"
        'date':data['ymd'], # yyyy-mm-dd
        }

def _data_handler(data):
    datelist = []
    datelist.append(_single_day_handler(data['yesterday']))
    for item in data['forecast']:
        datelist.append(_single_day_handler(item))
    return {
        'datelist':datelist,
        'current':{
            'flu':data['ganmao'],
            'pm10':data['pm10'],
            'pm25':data['pm25'],
            'air_quality':data['quality'],
            'temp':int(data['wendu']),
            'humi':data['shidu'] # str, e.g."30%"
            }
        }

async def aget_data(cityid):
    global latest_query_time
    wait_time = 3
    current_time = time.time()
    if current_time >= latest_query_time + wait_time:
        latest_query_time = current_time
        logger.info(f'Getting weather data(area={cityid}) from server...')
    else:
        wait_time = latest_query_time + wait_time - current_time
        latest_query_time = current_time + wait_time
        logger.info(f'Getting weather data(area={cityid}) from server, queuing time={wait_time}')
        await asyncio.sleep(wait_time)
        
    data = json.loads(await requester.aget_content_str(api.format(cityid)))
    assert data['status']==200, data['message']
    ci = data['cityInfo']
    return {
        'data':_data_handler(data['data']),
        'city':{
            'id':ci['citykey'],
            'name':ci['city'],
            'parent':ci['parent']
            },
        'date':data['date'], # yyyymmdd
        'msg':data['message'],
        'time':data['time'], # yyyy-mm-dd hh:mm:ss
        'update_time':ci['updateTime'], # hh:mm
        'request_time':time.time()
        }

def get_data(cityid): # 调试用
    data = json.loads(requester.get_content_str(api.format(cityid)))
    assert data['status']==200, data['message']
    ci = data['cityInfo']
    return {
        'data':_data_handler(data['data']),
        'city':{
            'id':ci['citykey'],
            'name':ci['city'],
            'parent':ci['parent']
            },
        'date':data['date'], # yyyymmdd
        'msg':data['message'],
        'time':data['time'], # yyyy-mm-dd hh:mm:ss
        'update_time':ci['updateTime'], # hh:mm
        'request_time':time.time()
        }

async def query_weather_backend(cityid):
    # 先找缓存, 没有或超过4小时再去请求api
    logger.info(f'Querying weather data (area={cityid})...')
    expire_time = 4*60*60
    cityid = str(cityid).strip()
    if cityid in cityid_sheet.keys():
        if cityid in cache.keys():
            item = cache[cityid]
            if item['request_time']+expire_time > time.time():
                logger.info('Data loaded from local cache.')
            else:
                cache[cityid] = await aget_data(cityid)
        else:
            cache[cityid] = await aget_data(cityid)
        return cache[cityid]
    else:
        return None

def make_message(data,date):
    outer_data = data
    data = data['data']
    date = int(date)
    if date not in range(-1,31+1):
        return '不存在的号数：'+str(date)
    current_date = time.localtime(time.time())[2]
    if date == 0 or date == current_date:
        current = data['current']
        for item in data['datelist']:
            if item['day'] == current_date:
                return f'''{outer_data['city']['parent']} - {outer_data['city']['name']}
{item['date']} 天气情况
数据更新：{outer_data['update_time']}
{item['status']}
当前温度：{current['temp']}℃
当前湿度：{current['humi']}
AQI：{item['aqi']}，{current['air_quality']}
PM2.5：{current['pm25']}
PM10：{current['pm10']}
{item['temp_lowest']}~{item['temp_highest']}℃
{item['wind_direction']} {item['wind_level']}
日出：{item['sunrise']}
日落：{item['sunset']}
{item['notice']}'''
        return f'''{outer_data['city']['parent']} - {outer_data['city']['name']} 没有 {current_date}号 的天气数据'''
    elif date == -1:
        text = f'''{outer_data['city']['parent']} - {outer_data['city']['name']} 逐日天气预报'''
        text += f'''\n数据更新：{outer_data['update_time']}'''
        for item in data['datelist']:
            if item['day'] == current_date:
                text += f'''\n{item['day']}号，{item['week']}（今天）：'''
            else:
                text += f'''\n{item['day']}号，{item['week']}：'''
            text += f'''{item['status']}，{item['temp_lowest']}~{item['temp_highest']}℃'''
        return text
    else:
        for item in data['datelist']:
            if item['day'] == date:
                return f'''{outer_data['city']['parent']} - {outer_data['city']['name']}
{item['date']}（{item['week']}） 天气情况
数据更新：{outer_data['update_time']}
{item['status']} {item['temp_lowest']}~{item['temp_highest']}℃
{item['wind_direction']} {item['wind_level']}
日出：{item['sunrise']}
日落：{item['sunset']}
{item['notice']}
'''
        return f'''{data['city']['parent']} - {data['city']['name']} 没有 {date}号 的天气数据'''

async def query_weather(city,date=0): # date为0时返回今天和当前数据, -1时返回完整预报
    try:
        city_pure = re.sub(r'[县省市区]','',city)
        for cid,cname in cityid_sheet.items():
            if city_pure in cname:
                return make_message(await query_weather_backend(cid),date)
        return f'地区 {city} 在支持的城市库中无匹配'
    except Exception as e:
        return '获取天气数据时出错：'+str(e)
        #raise e
