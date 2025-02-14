from melobot.utils import singleton
from melobot.protocols.onebot.v11.adapter import Adapter
from melobot.protocols.onebot.v11.adapter.event import GroupMessageEvent
from melobot.protocols.onebot.v11.adapter.segment import ReplySegment

__all__ = ["get_reply"]


@singleton
class _GetReply:
    class GetReplyException(Exception):
        """raise when failed to get reply"""

    class TargetNotSpecifiedError(GetReplyException):
        pass

    class EmptyResponseError(GetReplyException):
        pass

    @classmethod
    async def _get_reply(cls, adapter: Adapter, event: GroupMessageEvent):
        if _ := event.get_segments(ReplySegment):
            msg_id = _[0].data["id"]
        else:
            raise cls.TargetNotSpecifiedError()
        msg = await (await adapter.with_echo(adapter.get_msg)(msg_id))[0]
        if not msg.data:
            raise cls.EmptyResponseError(msg)
        return msg

    def __call__(self, adapter: Adapter, event: GroupMessageEvent):
        return self._get_reply(adapter, event)


get_reply = _GetReply()
