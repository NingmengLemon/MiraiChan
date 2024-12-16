from melobot import get_bot, get_logger
from melobot.plugin import PluginPlanner
from melobot.protocols.onebot.v11 import on_notice, Adapter
from melobot.protocols.onebot.v11.adapter.segment import PokeSegment, Segment
from melobot.protocols.onebot.v11.adapter.event import MessageEvent, PokeNotifyEvent

from extended_actions.lagrange import GroupPokeAction, FriendPokeAction


Pooooke = PluginPlanner("0.1.0")


@Pooooke.use
@on_notice()
async def poke_back(event: PokeNotifyEvent, adapter: Adapter):
    if event.self_id == event.target_id:
        if event.group_id:
            await adapter.call_output(
                GroupPokeAction(user_id=event.user_id, group_id=event.group_id)
            )
        else:
            await adapter.call_output(FriendPokeAction(user_id=event.user_id))
