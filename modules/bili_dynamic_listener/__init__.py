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
from . import bilidynamic
from .. import requester
import time
import atexit

channel = Channel.current()

channel.name("Bilibili Dynamic Listener")
channel.description("B站动态播报姬")
channel.author("NingmengLemon")

config_file = './config/bili_dynamic_listener_config.json'
config = {
   'edit_permit':[MemberPerm.Owner.value,MemberPerm.Administrator.value],
   'auto_announce':{}, # 群号(str):{(要监听的B站用户uid(str)):(上一次fetch到的动态id(int))}
   #要不是json保存时会自动把不是字符串的键改成字符串......
   'update_sleep':300 #second
   }

@atexit.register
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
            args = re.findall(r'^BiliDynamicListener\s+((add|remove)\s+([0-9]+)|(list|help))\s*$',msg,re.I) #提取指令信息
            if args:
               _,opt,uid,anzopt = args[0]
               if opt == 'add':
                  uid = str(uid)
                  if add_target(gid,uid):
                     await app.sendMessage(
                        group,
                        MessageChain.create(f'目标 {uid} 已经被添加过了')
                        )
                  else:
                     try:
                        user = await bilidynamic.get_user_info(uid)
                        nd = await bilidynamic.get_newest(uid)
                        if nd:
                           config['auto_announce'][gid][uid] = nd['dynamic_id']
                     except AssertionError as e:
                        config['auto_announce'][gid].pop(uid)
                        if int(str(e)) in [400,404]:
                           await app.sendMessage(
                              group,
                              MessageChain.create(f'目标 {uid} 不可用')
                              )
                        else:
                           raise
                     else:
                        uname = user['name']
                        await app.sendMessage(
                           group,
                           MessageChain.create(f'目标 {uid}（{uname}） 已添加')
                           )
               elif opt == 'remove':
                  uid = int(uid)
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
               elif anzopt == 'list':
                  if gid in config['auto_announce']:
                     if config['auto_announce'][gid]:
                        await app.sendMessage(
                           group,
                           MessageChain.create(f'当前群聊正在被蹲动态的用户如下：\n'+'\n'.join(list(config['auto_announce'][gid].keys())))
                           )
                     else:
                        await app.sendMessage(
                           group,
                           MessageChain.create('当前群聊还没有任何用户被蹲动态')
                           )
                  else: 
                     await app.sendMessage(
                        group,
                        MessageChain.create('当前群聊还没有任何用户被蹲动态')
                        )
               elif anzopt == 'help':
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

def second_to_time(sec):
    h = sec // 3600
    sec = sec % 3600
    m = sec // 60
    s = sec % 60
    return '%d:%02d:%02d'%(h,m,s)

async def make_msgchain(data):
   card = data['card']
   dtype = card['type']
   
   msgchain = MessageChain([
      Plain(data['user']['uname'] + ''' 发布了新动态
时间：{pt}
地址：https://t.bilibili.com/{did}
{cnt}
'''.format(pt=timestamp_to_time(card['timestamp']),
           did=data['dynamic_id'],cnt=card['content']))
      ])
   for url in card['images']:
      img = await requester.aget_content_bytes(url)
      msgchain += [Image(data_bytes=img)]
      
   if dtype == 'forward':
      msgchain += [Plain('''
原动态：https://t.bilibili.com/{dynamic_id}
发布者：{user[uname]}
{card[content]}'''.format(**card['origin']))]
   elif dtype == 'video':
      msgchain += [Plain('''
包含视频：{shortlink}
《{title}》（{length}秒）'''.format(**card['video']))]
   elif dtype == 'article':
      msgchain += [Plain('''
包含专栏：https://www.bilibili.com/read/cv{cvid}
《{title}》（{words}字）'''.format(**card['article']))]
   elif dtype == 'audio':
      msgchain += [Plain('''
包含音频：https://www.bilibili.com/audio/au{auid}
{author} - 《{title}》'''.format(**card['audio']))]
   else:
      pass
   return msgchain

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
                    msgchain = await make_msgchain(data[uid])
                    await app.sendGroupMessage(
                       int(group),
                       msgchain
                       )
                    config['auto_announce'][group][uid] = data[uid]['dynamic_id']
            else:
                pass
            await asyncio.sleep(1)
