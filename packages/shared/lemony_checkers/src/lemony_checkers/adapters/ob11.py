from typing import Final, Literal

from melobot.protocols.onebot.v11 import (
    PROTOCOL_IDENTIFIER as _PROTOCOL_IDENTIFIER,
)
from melobot.protocols.onebot.v11 import (
    Event,
    GroupMessageEvent,
    MessageEvent,
    PrivateMessageEvent,
)

from ..models import UniqueUserBase, UniqueUserDataclassBase
from .register import registry

_OB11_PROTOCOL_ID_LITERAL = Literal["OneBot-v11@Meloland"]
OB11_PROTOCOL_ID: Final[_OB11_PROTOCOL_ID_LITERAL] = _PROTOCOL_IDENTIFIER


class Ob11UniqueUser(UniqueUserBase[_OB11_PROTOCOL_ID_LITERAL]):
    user_id: int
    # TOML 无法表示 null, 写入时会丢掉这个字段, 必须给默认值, 否则重新加载会校验失败
    group_id: int | None = None


Ob11UniqueUserDataclass = Ob11UniqueUser.get_dataclass()


@registry.register_uniid_extractor(OB11_PROTOCOL_ID)
def builtin_ob11_uniid_extractor(
    event: MessageEvent,
) -> UniqueUserDataclassBase | None:
    if not isinstance(event, Event):
        return None
    if not isinstance(event, MessageEvent):
        return None
    if event.sub_type == "anonymous":
        return None  # 匿名消息已经过时了, 不适用
    if isinstance(event, GroupMessageEvent):
        return Ob11UniqueUserDataclass.from_kwargs(
            user_id=event.user_id,
            group_id=event.group_id,
            protocol=OB11_PROTOCOL_ID,
        )
    if isinstance(event, PrivateMessageEvent):
        return Ob11UniqueUserDataclass.from_kwargs(
            user_id=event.user_id,
            group_id=None,
            protocol=OB11_PROTOCOL_ID,
        )
    return None
