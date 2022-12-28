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
from .. import requester
from . import setuapi
import time
import atexit
from loguru import logger
import random
import traceback
import asyncio

channel = Channel.current()

channel.name("Setu Sender")
channel.description("涩图（并不）发送姬")
channel.author("NingmengLemon")

owner = 1435439745

cd = {}
cd_time = 5
# 涩图冷却
# uid(str):timestamp(float)(上次请求涩图的时间)

stat = {}
stat_file = './data/setu_stat.json'
# 统计信息
# group_id(str):{uid(str):(int)}
def load_stat():
    global stat
    if os.path.exists(stat_file):
        stat = json.load(open(stat_file,'r',encoding='utf-8'))
    else:
        pass
load_stat()

img_save_path = './data/setu_history/images/'
if not os.path.exists(img_save_path):
    os.makedirs(img_save_path,exist_ok=True)

match_pattern = re.compile(r'^#?[发来整][点张单份][涩色瑟]图$')

shielded_words = ['r18','r-18','r-15','r15','裸体','骆驼趾',
                  '丁字裤','伪娘',
                  '即将脱掉的胸罩','骑乘位','射精','精液','插入',
                  '中出','创可贴','援助交配']

@atexit.register
def save_stat():
    json.dump(stat,open(stat_file,'w+',encoding='utf-8'))

def add_stat(gid,uid):
    global stat
    gid = str(gid)
    uid = str(uid)
    if gid in stat:
        if uid in stat[gid]:
            stat[gid][uid] += 1
        else:
            stat[gid][uid] = 1
    else:
        stat[gid] = {}
        stat[gid][uid] = 1

async def get_and_save(url):
    filename = url.split('/')[-1]
    path = os.path.normpath(os.path.abspath(os.path.join(img_save_path,filename)))
    logger.debug('Saving url {} to file {}.'.format(url,path))
    if os.path.exists(path):
        return path
    else:
        with open(path,'wb+') as f:
            f.write(await requester.aget_content_bytes(url))
        return path

@channel.use(ListenerSchema(listening_events=[ApplicationLaunched]))
async def initialize(app: Ariadne):
    if len(setuapi.cache) < 10:
        await setuapi.fetch()
    logger.debug('Setu Sender Initialized.')

stat_pattern = re.compile(r'^#setusender\s+stat\s+(show|reload)$',re.I)

@channel.use(ListenerSchema(listening_events=[GroupMessage]))
async def stat_announcer(app: Ariadne, group: Group, message: MessageChain, member: Member):
    msg = str(message.include(Plain)).strip().lower()
    match_obj = re.match(stat_pattern,msg)
    if match_obj:
        if member.permission.value in [MemberPerm.Owner.value,MemberPerm.Administrator.value] or member.id == owner:
            cmd = match_obj.groups()[0]
            if cmd == 'show':
                gid = str(group.id)
                if gid in stat:
                    if stat[gid]:
                        data = stat[gid]
                        msgchain = MessageChain.create('本群的涩图统计信息如下：\n')
                        for uid in stat[gid]:
                            msgchain += MessageChain.create(At(int(uid)),f" {data[uid]} 次\n")
                        await app.sendMessage(
                            group,
                            msgchain
                            )
                    else:
                        await app.sendMessage(
                            group,
                            MessageChain.create('SetuSender: 本群的统计信息是空的')
                            )
                else:
                    await app.sendMessage(
                        group,
                        MessageChain.create('SetuSender: 本群的统计信息是空的')
                        )
            elif cmd == 'reload':
                load_stat()
                await app.sendMessage(
                    group,
                    MessageChain.create('SetuSender: 重新加载了统计信息')
                    )
        else:
            await app.sendMessage(
                group,
                MessageChain.create('您没有权限')
                )

@channel.use(ListenerSchema(listening_events=[GroupMessage]))
async def command_listener(app: Ariadne, group: Group, message: MessageChain, member: Member):
    msg = str(message.include(Plain)).strip().lower()
    if re.match(match_pattern,msg):
        if str(member.id) in cd:
            delta = time.time()-cd[str(member.id)]
            if delta <= cd_time:
                await app.sendMessage(
                    group,
                    MessageChain.create(At(member.id),' 涩图冷却ing，剩余 {} 秒'.format(cd_time-delta))
                    )
                return
        cd[str(member.id)] = time.time()
        add_stat(group.id,member.id)
        await app.sendMessage(
            group,
            MessageChain.create(random.choice([
                '咱找找，等一下嗷...','让咱找找...','少女翻找中...','在找了在找了...','Ero loading～です'
                ]),'\nTips：若Mirai酱太久没回复，则消息可能被tx吞了')
            )
        url,text = await setuapi.get()
        if url:
            if sum([i in text.lower() for i in shielded_words]) == 0:
                try:
                    file = await get_and_save(url)
                    await app.sendMessage(
                        group,
                        MessageChain.create(Image(path=file),text)
                        )
                except asyncio.exceptions.TimeoutError:
                    logger.error('Unable to send setu: Read timeout.')
                    await app.sendMessage(
                        group,
                        MessageChain.create('由于网络环境不佳，您的涩图加载超时了(´;ω;`)\n',text)
                        )
                except Exception as e:
                    logger.error('Unable to send setu: '+str(e))
                    await app.sendMessage(
                        group,
                        MessageChain.create('您的涩图在路上出事叻(｡í _ ì｡)\n以下是错误信息：\n'+traceback.format_exc())
                        )
                    #raise e
            else:
                try:
                    file = await get_and_save(url)
                except Exception as e:
                    logger.error('Failed to save file: '+url)
                await app.sendMessage(
                    group,
                    MessageChain.create('您的涩图被咱吃掉叻！(ゝ∀･)b\n可以透露的消息：\n'+text)
                    )
        else:
            await app.sendMessage(
                group,
                MessageChain.create(text)
                )
            await setuapi.fetch()
    if len(setuapi.cache) < 10:
        await setuapi.fetch()
            
