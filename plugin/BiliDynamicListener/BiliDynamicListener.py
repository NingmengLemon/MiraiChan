from pycqBot import cqBot, cqHttpApi, cqCode
from pycqBot import object as pcbobj
import json
import yaml
import os
import re
import logging
import time
import asyncio
import traceback
import atexit
from ruamel import yaml as ruayml
import threading
from . import bilidynamic

timestamp_to_time = lambda ts:time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
nickname_map = {}

config_path = './plugin_configs/'
config_filename = 'bilidynamiclistener_config.yml'

config_file_lock = threading.Lock()

def load_config(path=config_path):
    with config_file_lock:
        file = os.path.join(path,config_filename)
        if os.path.isfile(file):
            config = yaml.load(open(file,'r',encoding='utf-8'),Loader=yaml.FullLoader)
        else:
            config = {}
            with open(file,'w+',encoding='utf-8') as f:
                f.write('{}')
    return config

def dump_config(config,path=config_path):
    with config_file_lock:
        file = os.path.join(path,config_filename)
        with open(file,'w+',encoding='utf-8') as f:
            ruayml.dump(config,f,Dumper=ruayml.RoundTripDumper)

def load_nickname_map(file='./data/biliuser_nickname_map.json'):
    global nickname_map
    if os.path.isfile(file):
        nickname_map = json.load(open(file,'r',encoding='utf-8'))
    else:
        nickname_map = {}
        with open(file,'w+',encoding='utf-8') as f:
            f.write('{}')
load_nickname_map()

async def query_nickname(uid,reqer=None):
    global nickname_map
    uid = str(uid)
    if uid in nickname_map:
        nickname = nickname_map[uid]
    else:
        nickname = (await bilidynamic.get_user_info(reqer,uid))['name']
        nickname_map[uid] = nickname
        logging.debug(f'Uid{uid} 不在缓存中, 已重新请求')
    return nickname

def query_nickname_nowait(uid):
    global nickname_map
    uid = str(uid)
    if uid in nickname_map:
        return nickname_map[uid]
    else:
        return None

@atexit.register
def save_nickname_map(file='./data/biliuser_nickname_map.json'):
    json.dump(nickname_map,open(file,'w+',encoding='utf-8'))

def format_img_url(url,w=None,h=None,f='jpg'):
    '''For *.hdslb.com/bfs* only.'''
    if '.hdslb.com/bfs' not in url:
        raise RuntimeError('Not-supported URL Type:%s'%url)
    tmp = []
    if w:
        tmp += [str(w)+'w']
    if h:
        tmp += [str(h)+'h']
    tmp = '_'.join(tmp)
    if f and f in ['png','jpg','webp']:
        tmp += '.'+f
    if tmp:
        return url+'@'+tmp
    else:
        return url

def generate_msg(data):
    card = data['card']
    dtype = card['type']
    #正文
    msg = data['user']['uname'] + ''' 发布了新动态
时间：{pt}
地址：https://t.bilibili.com/{did}
{cnt}
'''.format(pt=timestamp_to_time(data['timestamp']),
            did=data['dynamic_id'],cnt=card['content'])
    #图片
    for i in range(len(card['images'])):
        url = card['images'][i]
        msg += cqCode.image(url.split('/')[-1],url)
    #附加内容
    if dtype == 'forward':
        msg += '''
原动态：https://t.bilibili.com/{dynamic_id}
发布者：{user[uname]}
{card[content]}'''.format(**card['origin'])
    elif dtype == 'video':
        msg += '''
包含视频：https://www.bilibili.com/video/av{avid}
《{title}》（{length}秒）'''.format(**card['video'])
    elif dtype == 'article':
        msg += '''
包含专栏：https://www.bilibili.com/read/cv{cvid}
《{title}》（{words}字）'''.format(**card['article'])
    elif dtype == 'audio':
        msg += '''
包含音频：https://www.bilibili.com/audio/au{auid}
{author} - 《{title}》'''.format(**card['audio'])
    else:
        pass
    return msg

class CommandNotSatisfyingError(Exception):
    def __init__(self,msg):
        self.msg = msg
    def __str__(self):
        return self.msg

class BiliDynamicListener(pcbobj.Plugin):
    """
    插件配置
    --------------------------
    listenTargets: 动态监听目标列表
    结构:
        [
            {
                group: 要发送到的群uid,
                targets: [要监听的用户id们],
                whitekws: [(当包含这些关键词时, 消息一定会被发出来, 优先级>blackkws)],
                blackkws: [(当包含这些关键词时, 消息不会被发出来)]
                },
            {...}
            ]
    listenSleep: 监听间隔(s)
    ------------------------------
    不要在程序运行时改配置文件, 因为大概率会被覆盖
    """
    def __init__(self, bot: cqBot, cqapi: cqHttpApi, plugin_config):
        super().__init__(bot, cqapi, plugin_config)
        # 不要pycqBot提供的plugin_config入口, 自己做加载
        plugin_config = load_config()
        # 两个基本配置
        self._listen_targets = plugin_config['listenTargets'] if 'listenTargets' in plugin_config else []
        self._listen_sleep = plugin_config['listenSleep'] if 'listenSleep' in plugin_config else 60
        # 供快速查询
        self._generate_fast_querying_map()
        
        self.cache = {} # 存放用户的动态列表以供比对

        self._config_lock = threading.Lock() #被同时修改时会报错, 故加锁
        # 加锁实际上保护的是self._listen_targets
        #cache:
        #{
        #   uid : [dynamic_data_obj, ...]
        #   ...
        #   }
        # 初始化动态列表
        self.cqapi.add_task(self.init_dynamic_list())
        # 绑定指令
        self.bot.command(
            self.modify_config,'bilidynamiclistener',
            {
                'help':[
                    'B站动态转发的根指令: bilidynamiclistener',
                    '#(根指令) target add/remove (B站用户uid) -> 增/减监听的用户',
                    '#(根指令) kwlist white/black add/remove (关键词) -> 增/减 黑/白关键词',
                    '#(根指令) target/kwlist show -> 展示当前正在监听的用户/黑白关键词表',
                    '(根指令区分大小写，包含白关键词的消息会被保留，其优先级>黑关键词表)'
                    ],
                'type':'group',
                #'admin':True,
                #'user':'admin'
                'user':'nall'
                })
        
        # 暂不启动计划事件, 由init_dynamic_list启动

    def _generate_fast_querying_map(self):
        # 群号 -> 目标信息在self._listen_targets中的索引
        self._gid_to_index_map = {self._listen_targets[i]['group']:i for i in range(len(self._listen_targets))}
        # 群号 -> 此群监听的目标们
        self._subscribe_map = {i['group']:i['targets'] for i in self._listen_targets}

    def save_config(self,path=config_path):
        file = os.path.join(path,config_filename)
        with self._config_lock:
            new_config = {
                'listenTargets':self._listen_targets.copy(),
                'listenSleep':self._listen_sleep
                }
        dump_config(new_config,path)

    def modify_config(self,cmd_data, msg:pcbobj.Message):
        # 无所谓, 我会自己做鉴权
        if not msg.user_id in self.bot.admin and not msg.sender['role'] in ['owner','admin']:
            # sender字典的键表参见 https://docs.go-cqhttp.org/reference/data_struct.html
            msg.reply('您没有足够的权限')
            return
        if not msg.group_id in [i['group'] for i in self._listen_targets]: #对没有配置文件的群创建配置文件
            with self._config_lock: # 注意, save_config也有加锁, 不要搞成死锁了
                self._listen_targets.append({
                    'group':msg.group_id,
                    'targets':[],
                    'whitekws':[],
                    'blackkws':[]
                    })
            self._generate_fast_querying_map()
            self.save_config()
        try: #尝试解析指令
            c2nd = cmd_data[0].lower() # 二级指令
            cmd_data = cmd_data[1:]
            c3rd = cmd_data[0].lower() # 三级指令
            cmd_data = cmd_data[1:]
            if c2nd == 'target': # target指令分支
                self._operate_targets(c3rd, cmd_data, msg)
            elif c2nd == 'kwlist': # kwlist指令分支
                if c3rd in ['black','white']:
                    self._operate_kws(c3rd, cmd_data, msg)
                elif c3rd == 'show':
                    tobj = self._listen_targets[self._gid_to_index_map[msg.group_id]]
                    msg.reply(
                        '当前的白关键词有:\n'+'; '.join(tobj['whitekws'])+\
                        '\n当前的黑关键词有:\n'+'; '.join(tobj['blackkws'])
                        )
                else:
                    raise CommandNotSatisfyingError('未识别的三级指令')
            else:
                raise CommandNotSatisfyingError('未识别的二级指令')
        except Exception as e:
            msg.reply('处理指令失败: '+str(e))
            logging.error('处理指令时发生错误（可能是指令发出者的错）:\n'+traceback.format_exc())

    def _operate_targets(self, c3rd, cmd_data, msg:pcbobj.Message):
        current_index = self._gid_to_index_map[msg.group_id]
        if c3rd == 'show':
            text = '当前正在监听的用户如下: \n'
            for uid in self._listen_targets[current_index]['targets']:
                nickname = query_nickname_nowait(uid)
                text += str(uid)
                if nickname:
                    text += f' ({nickname})'
                text += '\n'
            msg.reply(text)
        elif c3rd == 'remove':
            rmtarget = int(cmd_data[0])
            if rmtarget in self._listen_targets[current_index]['targets']:
                with self._config_lock:
                    self._listen_targets[current_index]['targets'].remove(rmtarget)
                self.save_config()
                msg.reply(f'Uid{rmtarget} 已被移除')
            else:
                msg.reply(f'Uid{rmtarget} 本来就不在监听列表中')
        elif c3rd == 'add':
            addtarget = int(cmd_data[0])
            if addtarget in self._listen_targets[current_index]['targets']:
                msg.reply(f'Uid{addtarget} 已经在监听列表中了')
            else:
                with self._config_lock:
                    self._listen_targets[current_index]['targets'].append(addtarget)
                self.save_config()
                self.cqapi.add_task(query_nickname(addtarget,reqer=self.cqapi))
                msg.reply(f'Uid{addtarget} 已被添加')
        else:
            raise CommandNotSatisfyingError('未识别的三级指令')

    def _operate_kws(self, c3rd, cmd_data, msg:pcbobj.Message):
        # c3rd = 'black'/'white'
        c4th = cmd_data[0].lower()
        c5th = cmd_data[1].lower()
        current_index = self._gid_to_index_map[msg.group_id]
        if c4th == 'add':
            if c5th in self._listen_targets[current_index][c3rd+'kws']:
                msg.reply(f'已存在{c3rd}关键词: {c5th}')
            else:
                with self._config_lock:
                    self._listen_targets[current_index][c3rd+'kws'].append(c5th)
                self.save_config()
                msg.reply(f'已添加{c3rd}关键词: {c5th}')
        elif c4th == 'remove':
            if c5th in self._listen_targets[current_index][c3rd+'kws']:
                with self._config_lock:
                    self._listen_targets[current_index][c3rd+'kws'].remove(c5th)
                self.save_config()
                msg.reply(f'已移除{c3rd}关键词: {c5th}')
            else:
                msg.reply(f'本来就没有{c3rd}关键词: {c5th}')
        else:
            raise CommandNotSatisfyingError('未识别的四级指令')

    async def _fetch_dynamic_list(self):
        res = {}
        for target in self._listen_targets:
            for uid in target['targets']:
                if uid not in res:
                    try:
                        logging.debug('正在获取动态数据: uid%s'%uid)
                        res[uid] = await bilidynamic.get_recent(self.cqapi,uid)
                    except Exception as e:
                        logging.error('用户 uid%s 的动态获取出错: %s'%(uid,str(e)))
                        logging.error('Error:\n'+traceback.format_exc())
                    await asyncio.sleep(0.1)
        return res

    async def init_dynamic_list(self):
        logging.debug('将在5秒后初始化动态列表')
        await asyncio.sleep(5)
        try:
            self.cache = {}
            logging.debug('开始初始化动态列表')
            self.cache = await self._fetch_dynamic_list()
            
            for uid in self.cache.keys(): #额外获得用户昵称
                logging.debug(f'Uid{uid} = '+(await query_nickname(uid,reqer=self.cqapi)))
                await asyncio.sleep(0.1)
        except Exception as e:
            logging.error('Error:\n'+traceback.format_exc())
        finally:
            logging.info('动态列表初始化完成')
            await asyncio.sleep(self._listen_sleep)
            #self.cqapi.add_task(self.acheck_dynamic_update())
            self.bot.timing(self.check_dynamic_update,'update_dynamic_list',{'timeSleep':self._listen_sleep}) #计划事件
    
    async def acheck_dynamic_update(self):
        try:
            logging.debug('开始拉取动态列表')
            need_to_be_sent = {} # group_id: [generated_text, ...]
            cache_new = await self._fetch_dynamic_list()
            logging.debug('动态列表已拉取')
            cache = self.cache
            # 分析新旧差别, 有参考pycqBot.plugin.bilibili
            # logging.debug('开始进行比对')
            for uid,new in cache_new.items():
                if uid not in cache:
                    continue
                old = cache[uid]
                # 比对最新一条动态
                if new[0]["timestamp"] == old[0]["timestamp"]:
                    continue
                elif new[0]['timestamp'] < old[0]["timestamp"]:
                    # 可能有动态删除
                    if new[0]['card']['type'] == 'video':
                        # 可能存在的视频修改行为
                        if new[0]['dynamic_id'] == old[0]['dynamic_id']:
                            # 进一步比对动态id
                            continue
                    logging.debug(f'侦测到 uid{uid} 有动态被删除')
                    continue
                else:
                    old_newest_time = old[0]['timestamp']
                    # 向后寻找可能漏掉的动态
                    for offset in range(1,len(new)): # 从1开始是因为0已经检查过了
                        if new[offset]['timestamp'] <= old_newest_time or\ # 动态时间必须晚于上次检查时的最新动态的发送时间
                           new[offset]['timestamp'] <= time.time()-60*60*1: # 备用, 阻止过于久远的动态被发出
                            break
                    need_to_be_sent[uid] = [generate_msg(i) for i in new[:offset]]
            self.send_msgs(need_to_be_sent)
        except Exception as e:
            logging.error('Error:\n'+traceback.format_exc())
        finally:
            self.cache.update(cache_new)
            #await asyncio.sleep(self._listen_sleep)
            #self.cqapi.add_task(self.acheck_dynamic_update())

    def send_msgs(self,tosend_dict):
        for gid,subed_uids in self._subscribe_map.items():
            for uid,msgs in tosend_dict.items():
                if uid in subed_uids:
                    for msg in msgs:
                        i = self._gid_to_index_map[gid]
                        # 关键词过滤
                        white = self._listen_targets[i]['whitekws']
                        black = self._listen_targets[i]['blackkws']
                        flag = True
                        if sum([b in msg for b in black]):
                            flag = False
                        if sum([w in msg for w in white]):
                            flag = True
                        if flag:
                            self.cqapi.add_task(self.send_msg(gid,msg))
                            #self.cqapi.send_group_msg(gid,msg)
                            logging.debug('已尝试发送 '+'消息'+' 到'+str(gid))
                        else:
                            logging.debug(f'已忽略 Uid{uid} 的一条动态, 由于设定的屏蔽词')
                            continue

    async def send_msg(self,group_id,msg):
        data = {
            'group_id':group_id,
            'message':msg,
            'auto_escape':False
            }
        rv = await self.cqapi._asynclink('/send_msg',data)
        if rv['retcode'] != 0:
            logging.error('动态转发失败！服务器消息: '+str(rv))
            # 移除图片
            msg = re.sub(r'\[CQ\:image.+?\]','',msg)
            # 重新发送
            self.cqapi.send_group_msg(
                group_id,
                msg+'\n\n!由于tx服务器的拦截，此条动态为无图版本'
                )

    def check_dynamic_update(self):
        self.cqapi.add_task(self.acheck_dynamic_update())

    def timing_jobs_start(self,job,run_count): #芝士内置事件
        if job['name'] == 'update_dynamic_list':
            self.check_dynamic_update()
        
