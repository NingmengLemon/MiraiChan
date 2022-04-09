from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import GroupMessage
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import At,Plain,Image
from graia.ariadne.model import Group, MemberPerm, Friend, MiraiSession, Member, AriadneStatus
from graia.ariadne.event.lifecycle import ApplicationLaunched
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
from . import bilidynamic,requester
import time

channel = Channel.current()

channel.name("Bilibili Dynamic Announcer")
channel.description("B站动态播报姬")
channel.author("NingmengLemon")

config_file = './config/bilibili_dynamic_config.json'
config = {
   'edit_permit':[MemberPerm.Owner.value,MemberPerm.Administrator.value],
   'auto_announce':{}, # 群号(str):{(要监听的B站用户uid(str)):(上一次fetch到的动态id)}
   'update_sleep':600 #second
   }

def save_config():
   json.dump(config,open(config_file,'w+',encoding='utf-8'))

def load_config():
   global config
   if os.path.exists(config_file):
      config = json.load(open(config_file,'r',encoding='utf-8'))
   else:
      save_config()

load_config()

def add_target(groupid,uid):
   global config
   groupid = str(groupid)
   uid = str(uid)
   if groupid in config['auto_announce']:
      pass
   else:
      config['auto_announce'][groupid] = {}
   if uid in config['auto_announce'][groupid]:
      return 1
   else:
      config['auto_announce'][groupid][uid] = None
      return 0

def remove_target(groupid,uid):
   global config
   groupid = str(groupid)
   uid = str(uid)
   if groupid in config['auto_announce']:
      if uid in config['auto_announce'][groupid]:
         config['auto_announce'][groupid].pop(uid)
         return 0
      else:
         return 1
   else:
      return 1

@channel.use(ListenerSchema(listening_events=[GroupMessage]))
async def add_and_remove_target(app: Ariadne, group: Group, message: MessageChain, member: Member):
   global config
   gid = str(group.id)
   if At(app.account) in message:
      msg = str(message.include(Plain)).strip().lower()
      if msg.startswith('bilidynamiclistener'): #指令前缀警觉
         if member.permission.value in config['edit_permit']: #权限判断
            args = re.findall(r'^BiliDynamicListener\s+(add|remove|list|help)\s+([0-9]+)$',msg,re.I) #提取指令信息
            if args:
               opt,uid = args[0]
               uid = int(uid)
               if opt == 'add':
                  if add_target(gid,uid):
                     await app.sendMessage(
                        group,
                        MessageChain.create(f'目标 {uid} 已经被添加过了')
                        )
                  else:
                     await app.sendMessage(
                        group,
                        MessageChain.create(f'目标 {uid} 已添加')
                        )
                     nd = await bilidynamic.get_newest(uid)
                     if nd:
                        config['auto_announce'][gid][uid] = nd['dynamic_id']
               elif opt == 'remove':
                  if remove_target(gid,uid):
                     await app.sendMessage(
                        group,
                        MessageChain.create(f'目标 {uid} 还未被添加')
                        )
                  else:
                     await app.sendMessage(
                        group,
                        MessageChain.create(f'目标 {uid} 已移除')
                        )
               elif opt == 'list':
                  if gid in config['auto_announce']:
                     if config['auto_announce'][gid]:
                        await app.sendMessage(
                           group,
                           MessageChain.create(f'当前群聊正在监听的用户如下：\n'+'\n'.join([str(i) for i in config['auto_announce'][gid].keys()]))
                           )
                     else:
                        await app.sendMessage(
                           group,
                           MessageChain.create('当前群聊还没有监听任何用户')
                           )
                  else: 
                     await app.sendMessage(
                        group,
                        MessageChain.create('当前群聊还没有监听任何用户')
                        )
               elif opt == 'help':
                  await app.sendMessage(
                     group,
                     MessageChain.create('指令说明：\n操作：bilidynamiclistener add/remove <uid>'\
                                         '\n查看：bilidynamiclistener list'\
                                         '\n显示此条信息：bilidynamiclistener help'\
                                         '\n权限修改请手动修改配置文件')
                     )
               save_config()
            else:
               await app.sendMessage(
                  group,
                  MessageChain.create('指令格式不正确')
                  )
         else:
            await app.sendMessage(
               group,
               MessageChain.create('您的权限不足')
               )

timestamp_to_time = lambda ts:time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))

async def make_msgchain(data):
   pass #哼哼哼啊啊啊啊啊啊啊啊

@channel.use(SchedulerSchema(timer=timers.every_custom_seconds(config['update_sleep'])))
async def background_task(app: Ariadne):
    global config
    data = {}
    for group in config['auto_announce'].keys():
        for uid in config['auto_announce'][group].keys():
            if uid in data:
                pass
            else:
                data[uid] = await bilidynamic.get_newest(uid)
            if data[uid]:
                if data[uid]['dynamic_id'] in config['auto_announce'][group].values():
                    pass
                else:
                    msgchain = await make_msgchain(datap[uid])
                    config['auto_announce'][group][uid] = data[uid]['dynamic_id']
                    await app.sendGroupMessage(
                       int(group),
                       msgchain
                       )
            else:
                pass
            asyncio.sleep(1)
