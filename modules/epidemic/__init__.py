from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import GroupMessage
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import At,Plain
from graia.ariadne.model import Group, Friend, MiraiSession

from graia.saya import Channel
from graia.saya.builtins.broadcast.schema import ListenerSchema

from graia.scheduler import timers
from graia.scheduler.saya import GraiaSchedulerBehaviour, SchedulerSchema

from graia.ariadne.event.lifecycle import ApplicationLaunched, ApplicationShutdowned

from . import epidemic

from loguru import logger

channel = Channel.current()

channel.name("COVID-19 Epidemic Info Reply")
channel.description("新冠疫情播报姬")
channel.author("NingmengLemon")

@channel.use(ListenerSchema(listening_events=[GroupMessage]))
async def epidemic_info_reply(app: Ariadne, group: Group, message: MessageChain):
   if At(app.account) in message:
      msg = str(message.include(Plain)).strip().lower()
      if msg.endswith('疫情'):
         area = msg.replace('疫情','').strip()
         await app.sendMessage(
            group,
            MessageChain.create(epidemic.query_text(area=area))
            )

@channel.use(ListenerSchema(listening_events=[ApplicationLaunched]))
@channel.use(SchedulerSchema(timer=timers.every_custom_seconds(1800)))
async def background_task():
   try:
      await epidemic.afetch()
   except Exception as e:
      logger.error('Unable to fetch epidemic data: '+str(e))
   else:
      #logger.info('Fetched epidemic data')
      pass
