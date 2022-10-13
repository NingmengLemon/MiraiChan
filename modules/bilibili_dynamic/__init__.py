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
from . import bilidynamic
from .. import requester
import time
import atexit
from loguru import logger

channel = Channel.current()

channel.name("Bilibili Dynamic Listener")
channel.description("B站动态播报姬")
channel.author("NingmengLemon")

config_file = './config/bili_dynamic_listener_config.json'
config = {
    'edit_permit':[MemberPerm.Owner.value,MemberPerm.Administrator.value],
    'auto_announce':{}, # 群号(str):{(要监听的B站用户uid(str)):(上一次fetch到的动态id们(list[int]))}
    # 要不是json保存时会自动把不是字符串的键改成字符串......
    'update_sleep':300, # second
    'shielded_words':[], # 列表套字符串
    'owner':None, #主人 
    'nicknames':{} # 用户uid(str):用户昵称(str)
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
        config['auto_announce'][groupid][uid] = []
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

async def init_target(target_uid:int,group_ids:list):
    global config
    try:
        user_data = await bilidynamic.get_user_info(target_uid)
        rd = await bilidynamic.get_recent(target_uid)
    except AssertionError as e:
        raise
    else:
        if rd:
            for gid in group_ids:
                config['auto_announce'][str(gid)][str(target_uid)] = [i['dynamic_id'] for i in rd]
        return user_data,rd

#match_pattern = re.compile('#(绑定uid|解绑uid|已绑uid|显示屏蔽词|重载配置文件|转发姬帮助)\s*([0-9]+)?$',re.I)

@channel.use(ListenerSchema(listening_events=[GroupMessage]))
async def add_and_remove_target(app: Ariadne, group: Group, message: MessageChain, member: Member):
    global config
    gid = str(group.id)
    if 1==1:#At(app.account) in message:
        msg = str(message.include(Plain)).strip().lower()
        if msg.startswith('#listener'): #指令前缀警觉
            if member.permission.value in config['edit_permit'] or member.id == int(config['owner']): #权限判断
                args = re.findall(r'^#Listener\s+((add|remove)\s+([0-9]+)|(list|help|showShieldedWords|reloadConfig))\s*$',msg,re.I) #提取指令信息
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
                                ud,rd = await init_target(uid,[gid])
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
                                uname = ud['name']
                                config['nicknames'][str(uid)] = uname
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
                            if str(uid) in config['nicknames']:
                                uname = config['nicknames'][str(uid)]
                                await app.sendMessage(
                                    group,
                                    MessageChain.create(f'目标 {uid}（{uname}）已移除')
                                    )
                            else:
                                await app.sendMessage(
                                    group,
                                    MessageChain.create(f'目标 {uid} 已移除')
                                    )
                    elif anzopt == 'list':
                        if gid in config['auto_announce']:
                            if config['auto_announce'][gid]:
                                text = ''
                                for tgt in config['auto_announce'][gid].keys():
                                    if tgt in config['nicknames']:
                                        text += '{}（{}）\n'.format(tgt,config['nicknames'][tgt])
                                    else:
                                        text += tgt+'\n'
                                await app.sendMessage(
                                    group,
                                    MessageChain.create(f'当前的目标如下：\n'+text)
                                    )
                            else:
                                await app.sendMessage(
                                    group,
                                    MessageChain.create('还没有目标')
                                    )
                        else:
                            await app.sendMessage(
                                group,
                                MessageChain.create('还没有目标')
                                )
                    elif anzopt == 'help':
                        await app.sendMessage(
                            group,
                            MessageChain.create('指令说明：\n根指令：#listener\n操作：add/remove <uid>'\
                                                    '\n查看正在追踪：list'\
                                                    '\n显示此条信息：help'\
                                                    '\n查看当前屏蔽词：showshieldedwords'\
                                                    '\n重新加载设置文件：reloadconfig'\
                                                    '\n权限/屏蔽词修改去配置文件'\
                                                    '\n举例：#listener add 114514 （添加114514这个uid）')
                            )
                    elif anzopt == 'showshieldedwords':
                        await app.sendMessage(
                            group,
                            MessageChain.create('当前屏蔽关键词：\n'+'; '.join(config['shielded_words'])))
                    elif anzopt == 'reloadconfig':
                        load_config()
                        await app.sendMessage(
                            group,
                            MessageChain.create('BiliDynamicListener: Config file reloaded.')
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
    #正文
    msgchain = MessageChain([
        Plain(data['user']['uname'] + ''' 发布了新动态
时间：{pt}
地址：https://t.bilibili.com/{did}
{cnt}
'''.format(pt=timestamp_to_time(data['timestamp']),
            did=data['dynamic_id'],cnt=card['content']))
        ])
    #图片
    for url in card['images']:
        img = await requester.aget_content_bytes(url)
        msgchain += [Image(data_bytes=img)]
    #附加内容
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

def check_update(fetched_data:list,group_id,target_uid):
    pre_data = []
    for dy in fetched_data:
        if dy['dynamic_id'] not in config['auto_announce'][str(group_id)][str(target_uid)]:
            pre_data.append(dy)
    return pre_data

def remove_repeat(l):
    tl = []
    for i in l:
        if i not in tl:
            tl.append(i)
    return tl

@channel.use(SchedulerSchema(timer=timers.every_custom_seconds(config['update_sleep'])))
async def background_task(app: Ariadne):
    global config
    #logger.info('Start fetching dynamic info...')
    data = {}#uid:[a lot of dynamic_data]
    for group in config['auto_announce'].keys():
        for uid in config['auto_announce'][group].keys():
            if uid in data:
                pass
            else:
                try:
                    data[uid] = await bilidynamic.get_recent(uid)
                except Exception as e:
                    #logger.error(f'Unable to fetch dynamic info of user {uid}: '+str(e))
                    continue
                else:
                    pass
                    #logger.debug(f'Successfully fetched dynamic info of user {uid}.')
            if data[uid]:
                for dyn in check_update(data[uid],group,uid):
                    if time.time() - dyn['timestamp'] <= config['update_sleep']:
                        msgchain = await make_msgchain(dyn)
                        if sum([i in str(msgchain) for i in config['shielded_words']]) == 0:
                            await app.sendGroupMessage(
                                int(group),
                                msgchain
                                )
                            logger.info('Sent dynamic {did} of user {uid} to group {gid}'.format(did=dyn['dynamic_id'],gid=group,uid=uid))
                        else:
                            logger.info('Skip dynamic {did} of user {uid} (due to shielded words)'.format(did=dyn['dynamic_id'],uid=uid))
                    else:
                        logger.info('Skip dynamic {did} of user {uid} (due to expiration)'.format(did=dyn['dynamic_id'],uid=uid))
                config['auto_announce'][group][uid] = remove_repeat(config['auto_announce'][group][uid]+[i['dynamic_id'] for i in data[uid]])
            else:
                pass
            await asyncio.sleep(1)
    save_config()
    #logger.info('End fetching dynamic info. The next time is after {}s'.format(config['update_sleep']))

@channel.use(ListenerSchema(listening_events=[ApplicationLaunched]))
async def init_fetched_list(app: Ariadne):
    global config
    data = {}#uid:[a lot of dynamic_data]
    logger.info('Start initializing dynamic listener...')
    for group in config['auto_announce'].keys():
        for uid in config['auto_announce'][group].keys():
            if uid in data:
                pass
            else:
                try:
                    data[uid] = await bilidynamic.get_recent(uid)
                except Exception as e:
                    logger.error(f'Unable to fetch dynamic info of user {uid}: '+str(e))
                    continue
                else:
                    logger.debug(f'Successfully fetched dynamic info of user {uid}.')
            if data[uid]:
                config['auto_announce'][group][uid] = [i['dynamic_id'] for i in data[uid]]
            else:
                pass
            await asyncio.sleep(1)
    save_config()
    logger.info('End initializing dynamic listener.')
