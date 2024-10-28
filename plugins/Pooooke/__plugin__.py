from melobot.plugin import Plugin
from melobot.protocols.onebot.v11 import on_notice, Adapter
from melobot.protocols.onebot.v11.adapter.segment import PokeSegment, Segment
from melobot.protocols.onebot.v11.adapter.event import MessageEvent, PokeNotifyEvent


@on_notice(checker=lambda e: e.is_notify() and e.is_poke())
async def poke_back(event: PokeNotifyEvent, adapter: Adapter):
    await adapter.send_custom(
        Segment("poke", type=1), user_id=event.user_id, group_id=event.group_id
    )


class Pooooke(Plugin):
    author = "LemonyNingmeng"
    version = "0.1.0"
    flows = (poke_back,)
