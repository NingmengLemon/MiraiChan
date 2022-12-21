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

channel = Channel.current()

channel.name("Setu Sender")
channel.description("涩图（并不）发送姬")
channel.author("NingmengLemon")


img_save_path = './data/setu_history/images/'
if not os.path.exists(img_save_path):
    os.makedirs(img_save_path,exist_ok=True)

match_pattern = re.compile(r'^#?[发来整]点[涩色瑟美]图$')

async def get_and_save(url):
    filename = url.split('/')[-1]
    path = os.path.normpath(os.path.abspath(os.path.join(img_save_path,filename)))
    if os.path.exists(path):
        return path
    else:
        with open(path,'wb+') as f:
            f.write(await requester.aget_content_bytes(url))
        return path

@channel.use(ListenerSchema(listening_events=[ApplicationLaunched]))
async def initialize(app: Ariadne):
    if len(setuapi.cache) < 8:
        await setuapi.fetch()
    logger.debug('Setu Sender Initialized.')
    

@channel.use(ListenerSchema(listening_events=[GroupMessage]))
async def add_and_remove_target(app: Ariadne, group: Group, message: MessageChain, member: Member):
    msg = str(message.include(Plain)).strip().lower()
    if re.match(match_pattern,msg):
        await app.sendMessage(
            group,
            MessageChain.create('咱找找，等一下嗷...')
            )
        url,text = await setuapi.get()
        if url:
            try:
                file = await get_and_save(url)
                await app.sendMessage(
                    group,
                    MessageChain.create(Image(path=file),text)
                    )
            except Exception as e:
                logger.error('Unable to send setu: '+str(e))
                await app.sendMessage(
                    group,
                    MessageChain.create('您的涩图在路上出事力（悲）\n原因是'+str(e))
                    )
                #raise e
        else:
            await app.sendMessage(
                group,
                MessageChain.create(text)
                )
            await setuapi.fetch()
    if len(setuapi.cache) < 8:
        await setuapi.fetch()
            
