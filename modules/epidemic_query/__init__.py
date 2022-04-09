from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import GroupMessage
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import At,Plain
from graia.ariadne.model import Group, Friend, MiraiSession

from graia.saya import Channel
from graia.saya.builtins.broadcast.schema import ListenerSchema

from . import epidemic

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
