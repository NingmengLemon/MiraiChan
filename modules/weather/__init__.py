from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import GroupMessage
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import At,Plain
from graia.ariadne.model import Group, Friend, MiraiSession

from graia.saya import Channel
from graia.saya.builtins.broadcast.schema import ListenerSchema

from graia.scheduler import timers
from graia.scheduler.saya import GraiaSchedulerBehaviour, SchedulerSchema

from graia.ariadne.event.lifecycle import ApplicationLaunched, ApplicationShutdowned

from . import weather
from .hanzi2number import hanzi2number as h2n

from loguru import logger

import re
import time

channel = Channel.current()

channel.name("Weather Info Reply")
channel.description("天气播报姬")
channel.author("NingmengLemon")

match_pattern = re.compile(r'^([\u4e00-\u9fa5]+?)\s*((\d+|[一二三四五六七八九十]+)[日号]|逐[天日]|([昨今明后])[天日]|(星期|周|礼拜)(\d+|[一二三四五六七日]+))\s*天气(预报)?$')

@channel.use(ListenerSchema(listening_events=[GroupMessage]))
async def weather_reply(app: Ariadne, group: Group, message: MessageChain):
    if At(app.account) in message:
        msg = str(message.include(Plain)).strip().lower()
        mobj = match_pattern.match(msg)
        if mobj:
            area,dbd,date,rd,_,week,_ = mobj.groups()
            if dbd.startswith('逐'):
                await app.sendMessage(
                    group,
                    MessageChain.create(await weather.query_weather(area,-1))
                    )
            elif date:
                if date.isdigit():
                    date = int(date)
                else:
                    try:
                        date = h2n(date)
                    except:
                        await app.sendMessage(
                            group,
                            MessageChain.create(f'未识别的数字序列：{date}')
                            )
                        return
                    else:
                        pass
                await app.sendMessage(
                    group,
                    MessageChain.create(await weather.query_weather(area,date))
                    )
            elif rd:
                date = time.localtime(time.time()+60*60*24*{'今':0,'明':1,'昨':-1,'后':2}[rd])[2]
                await app.sendMessage(
                group,
                MessageChain.create(await weather.query_weather(area,date))
                )
            elif week:
                await app.sendMessage(
                    group,
                    MessageChain.create('暂不支持按星期索引awa')
                    )
            

          
