from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import GroupMessage
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.model import Group, Friend, MiraiSession
from graia.scheduler import GraiaScheduler

from graia.saya import Saya
from graia.saya.builtins.broadcast import BroadcastBehaviour
from graia.scheduler.saya.behaviour import GraiaSchedulerBehaviour, SchedulerSchema

import os
from modules import requester

config_path = './config/'
if not os.path.exists(config_path):
    os.mkdir(config_path)

app = Ariadne(
    MiraiSession(
        host="http://localhost:8080",
        verify_key="NeneAyachi",
        account=1956986009,
        # 此处的内容请按照你的 MAH 配置来填写
    ),
)
broadcast = app.broadcast
scheduler = GraiaScheduler(loop=broadcast.loop, broadcast=broadcast)

saya = app.create(Saya)
saya.install_behaviours(
    app.create(BroadcastBehaviour),
    GraiaSchedulerBehaviour(scheduler)
)

with saya.module_context():
    #saya.require("modules.epidemic")
    saya.require("modules.weather")
    saya.require('modules.bilibili_dynamic')
    saya.require('modules.random_setu')

app.launch_blocking()
