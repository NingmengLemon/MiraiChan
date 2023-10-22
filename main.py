from pycqBot import cqHttpApi, cqLog
import logging
import sys
import os
import colorama

colorama.init(autoreset=True)

if not os.path.exists('./plugin_configs/'):
    os.mkdir('./plugin_configs/')
#不是很想使用pycqBot官方提供的plugin_config.yml

# 启用日志 默认日志等级 DEBUG
cqLog()
sys.stdout.reconfigure(encoding='utf-8')

cqapi = cqHttpApi()
bot = cqapi.create_bot()

bot.plugin_load([
    "MoeAttriLottery",
    "BiliDynamicListener",
    "EroPicSender"
    ])

bot.admin = []
bot.start(start_go_cqhttp=False)

# 成功启动可以使用 指令标识符+help 使用内置指令 help
