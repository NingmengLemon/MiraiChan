from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import GroupMessage
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import At,Plain,Image
from graia.ariadne.model import Group, MemberPerm, Friend, MiraiSession, Member, AriadneStatus
from graia.ariadne.event.lifecycle import ApplicationLaunched, ApplicationShutdowned
from graia.ariadne.message.parser.base import MentionMe

from graia.scheduler import timers
from graia.scheduler.saya import GraiaSchedulerBehaviour, SchedulerSchema

from graia.saya import Channel
from graia.saya.builtins.broadcast.schema import ListenerSchema

import asyncio
import json
import re
import os
from io import BytesIO
from loguru import logger
import time
import atexit
from . import moe_attrs

channel = Channel.current()

channel.name("MoeAttribute Drawer")
channel.description("萌属性抽签姬")
channel.author("NingmengLemon")

owner = 1435439745
match_pattern = re.compile(r'^#?抽(签|萌?属性|设定|人设)$')
cache = {} # 用户QQ号(str):数据包(obj)
cache_path = './cache/moedrawer_cache.json'
if os.path.exists(cache_path):
    cache = json.load(open(cache_path,'r',encoding='utf-8',errors='ignore'))
else:
    if not os.path.exists('./cache/'):
        os.mkdir('./cache/')

def get_time(ts):
    lt = time.localtime(ts)
    return lt.tm_year,lt.tm_yday

def generate_text(data):
    data = data.copy()
    attrs = []
    data.pop('time')
    for k,v in data.items():
        if v != '/':
            attrs += [v]
    return ''' 您今天的设定如下(๑´ڡ`๑)\n'''+'，'.join(attrs)

@atexit.register
def save_cache():
    json.dump(cache,open(cache_path,'w+',encoding='utf-8',errors='ignore'))

@channel.use(ListenerSchema(listening_events=[GroupMessage]))
async def reply(app: Ariadne, group: Group, message: MessageChain, member: Member):
    global cache
    msg = str(message.include(Plain)).strip().lower()
    uid = str(member.id)
    if re.match(match_pattern,msg):
        if uid in cache:
            if get_time(cache[uid]['time'])==get_time(time.time()):
                await app.sendMessage(
                    group,
                    MessageChain.create(At(member.id),' 您今天已经抽过签了~')
                    )
                return
        data = moe_attrs.generate()
        await app.sendMessage(
            group,
            MessageChain.create(At(member.id),generate_text(data))
            )
        cache[uid] = data
        return
    if msg == '#moeattrs reload':
        if member.permission.value in [MemberPerm.Owner.value,MemberPerm.Administrator.value] or\
           member.id == owner:
            moe_attrs.load_attrs()
            await app.sendMessage(
                group,
                MessageChain.create('重新加载了MoeAttrs资料库')
                )
        else:
            await app.sendMessage(
                group,
                MessageChain.create('您没有权限')
                )
