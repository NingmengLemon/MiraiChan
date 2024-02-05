from pycqBot import cqBot, cqHttpApi
from pycqBot.object import *
#from pycqBot.data import *
from . import extractor

import traceback
import json
import time

cache = {}
# qq_number: data_pack(from extractor.generator)

class MoeAttriLottery(Plugin):
    # : xxx 是为了让你的IDE有语法提示
    def __init__(self, bot: cqBot, cqapi: cqHttpApi, plugin_config):
        super().__init__(bot, cqapi, plugin_config)

        self.bot.command(
            self.reload_moefile,'reloadmoefile',
            {
                'help':['#reloadmoefile - 重载萌属性数据文件'],
                'user':'nall',
                'admin':True
                })
        self.bot.command(
            self.draw_lot,'draw',
            {
                'help':['#draw - 抽取当日的萌属性, 等价于单独发送“抽签”二字'],
                'user':'nall',
                'admin':False
                })

    def on_group_msg(self,msg):
        if msg.text == '抽签':
            self.draw_lot([],msg)

    def reload_moefile(self,cmd_data,msg):
        try:
            extractor.load_attrs()
        except Exception as e:
            msg.reply('无法重载数据: '+str(e))
            logging.error('数据文件重载错误:\n'+traceback.format_exc())
        else:
            msg.reply('已重载萌属性数据文件')

    def draw_lot(self,cmd_data,msg):
        global cache
        if msg.user_id in cache:
            last_draw_date = time.strftime("%Y-%m-%d", time.localtime(cache[msg.user_id]['time']))
            if last_draw_date == time.strftime("%Y-%m-%d", time.localtime()):
                msg.reply('您今天已经抽过签了~！')
                return
        data = extractor.generate()
        cache[msg.user_id] = data.copy()
        draw_time = data.pop('time')
        msg.reply(
            '您今天的设定如下(๑´ڡ`๑)\n'+'\n'.join([f'{i}：{o}' for i,o in data.items()])+\
            '\n生成时间：'+time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(draw_time))
            )
        
