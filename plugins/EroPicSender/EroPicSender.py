from pycqBot import cqBot, cqHttpApi, cqCode
from pycqBot import object as pcbobj

import yaml
import json
from ruamel import yaml as ruayml
import atexit
import asyncio
import aiofiles
import os
import random
import traceback
import time
import logging
import re

from . import setuapi

setu_save_path = './data/setu_history/imgs/'
stat_file = './data/setu_stat.yml'
stat = {}
#group_id: {qq_num: setu_count}
cold_time = 10
cold_down = {}
#qq_num: last_req_time
match_pattern = re.compile(r'^#?[发来整][点张份][涩色瑟]图$')
enabled = True
shielded_words = [
    'r18','r-18',
    '裸体','骆驼趾',
    '丁字裤','伪娘',
    '即将脱掉的胸罩','骑乘位','射精','精液','插入',
    '中出','援助交配'
    ]

if not os.path.exists(setu_save_path):
    os.makedirs(setu_save_path,exist_ok=True)

if os.path.isfile(stat_file):
    with open(stat_file,'r',encoding='utf-8') as f:
        stat = yaml.load(f,Loader=yaml.FullLoader)

@atexit.register
def save_stat():
    with open(stat_file,'w+',encoding='utf-8') as f:
        ruayml.dump(stat,f,Dumper=ruayml.RoundTripDumper)

class HttpStatusNotSatisfyingError(Exception):
    def __init__(self,url,file,httpcode):
        self.url = url
        self.file = file
        self.httpcode = httpcode
        self._msg = f'Http Status Not Satisfying: from {url} to {file} with code {httpcode}'

    def __str__(self):
        return self._msg

class ContentTooShortError(Exception):
    def __init__(self,size,expected_min_size):
        self.size = size
        self.expected_min_size = expected_min_size
        self._msg = 'Content too short: expect >=%s instead of %s'%(size,expected_min_size)
    def __str__(self):
        return self._msg

async def download(session,url,file,chunk_size=1024):
    # 重写自 pycqBot.socketApp.asyncHttp
    async with session.get(url) as req:
        if req.status != 200:
            raise HttpStatusNotSatisfyingError(url,file,req.status)

        async with aiofiles.open(file, "wb") as f:
            async for chunk in req.content.iter_chunked(chunk_size):
                await f.write(chunk)

class EroPicSender(pcbobj.Plugin):
    def __init__(self, bot: cqBot, cqapi: cqHttpApi, plugin_config):
        super().__init__(bot, cqapi, plugin_config)

        self.bot.command(
            self.request_eropic,'setu',
            {
                'help':['#setu - 向Mirai酱要涩图，有5秒的冷却时间，等价于单独发送“来点涩图”等'],
                'user':'nall',
                'admin':False
                })
        self.bot.command(
            self.switch_enable_status,'setuswitch',
            {
                'help':['#setuswitch - 启用/禁用涩图模块'],
                'user':'nall',
                'admin':True
                })
        self.cqapi.add_task(self.init_setulib())

    def switch_enable_status(self,cmd_data,msg):
        global enabled
        if enabled:
            enabled = False
        else:
            enabled = True
        msg.reply('涩图模块启用状态已全局设定为 '+str(enabled))

    def on_group_msg(self,msg):
        if re.match(match_pattern,msg.text):
            self.request_eropic([],msg)

    async def check_setuassets(self):
        try:
            if len(setuapi.cache) < 20:
                logging.debug('涩图库内容<20个, 正在获取...')
                await setuapi.fetch(self.cqapi)
            else:
                logging.debug('涩图库余量充足 ( %s 个)'%len(setuapi.cache))
        except Exception as e:
            logging.error('检查涩图库时出错:\n'+traceback.format_exc())

    async def init_setulib(self):
        logging.debug('将在5秒后初始化涩图库')
        await asyncio.sleep(5)
        logging.debug('开始初始化涩图库')
        await self.check_setuassets()
        logging.debug('涩图库初始化完成')

    def request_eropic(self,cmd_data,msg):
        global cold_down
        global stat
        # 冷却判断
        uid = msg.user_id
        gid = msg.group_id
        if uid in cold_down:
            delta = time.time() - cold_down[uid]
            if delta < cold_time:
                msg.reply('涩图冷却ing，剩余 %.2f 秒'%(cold_time-delta))
                return
        cold_down[uid] = time.time()
        # 统计
        if str(gid) in stat:
            if str(uid) in stat[str(gid)]:
                stat[str(gid)][str(uid)] += 1
            else:
                stat[str(gid)][str(uid)] = 0
        else:
            stat[str(gid)] = {}
            stat[str(gid)][str(uid)] = 0
        # 开始
        self.cqapi.add_task(self._request_eropic(cmd_data,msg))

    async def _request_eropic(self,cmd_data,message):
        if not enabled:
            message.reply('涩图模块被管理员禁用')
            return
        try:
            url,msg_to_send = setuapi.get_msg()
        except Exception as e:
            message.reply('请求涩图数据时发生错误: '+str(e))
            logging.error('涩图数据请求错误:\n'+traceback.format_exc())
            return
        if url:
            message.reply(random.choice([
                '咱找找，等一下嗷...','让咱找找...','少女翻找中...','在找了在找了...','Ero loading～です'
                ])+'')
            # 尝试下载
            logging.debug('正在尝试下载: '+url)
            try:
                file = os.path.join(setu_save_path,url.split('/')[-1])
                await download(self.cqapi._session,url,file)
                if os.path.getsize(file) <= 10*1024:
                    raise ContentTooShortError(os.path.getsize(file),10*1024)
            except Exception as e:
                message.reply('您的涩图在路上出事了...！\n'+str(e)+'\n以下是原始信息：\n'+msg_to_send)
                logging.error('涩图下载错误:\n'+traceback.format_exc())
                return
            # 主动过滤
            if sum([(i in msg_to_send.lower()) for i in shielded_words]) != 0:
                message.reply('你要的涩图被咱吃掉叻！剩余的信息如下：\n'+msg_to_send)
                return
            # 尝试发送
            # 调用底层, 目的是检测是否发送成功
            msg_text = msg_to_send
            msg_to_send = cqCode.reply(msg_id=message.id)+\
                          cqCode.image('file:///'+os.path.abspath(file))+\
                          '\n'+msg_to_send
            data = {
                'group_id':message.group_id,
                'message':msg_to_send,
                'auto_escape':False
                }
            rv = await self.cqapi._asynclink('/send_msg',data)
            if rv['retcode'] != 0:
                logging.error('涩图发送失败！服务器消息: '+str(rv))
                message.reply('涩图被tx服务器击落！\n服务器消息: '+rv['wording']+\
                              '\n原始消息如下: \n'+msg_text
                              )
        else:
            message.reply(msg_to_send)
        await self.check_setuassets()
