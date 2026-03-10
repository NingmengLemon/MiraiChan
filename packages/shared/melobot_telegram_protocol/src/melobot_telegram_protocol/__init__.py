"""melobot Telegram Bot 协议支持

基于 aiogram 实现的 Telegram Bot 协议适配器，
为 melobot 框架提供 Telegram Bot API 支持。

使用示例::

    from melobot import Bot
    from melobot_telegram_protocol import TelegramBotProtocol

    bot = Bot(__name__)
    bot.add_protocol(TelegramBotProtocol("YOUR_BOT_TOKEN"))
    bot.run()
"""

from melobot.protocols import ProtocolStack

from .adapter import (
    Action,
    Adapter,
    AnswerCallbackQueryAction,
    CallbackQueryEvent,
    ChannelPostEvent,
    ChatMemberEvent,
    Echo,
    EditedChannelPostEvent,
    EditedMessageEvent,
    Event,
    GroupMessageEvent,
    MessageEvent,
    PrivateMessageEvent,
    RawAction,
    SendAnimationAction,
    SendAudioAction,
    SendDocumentAction,
    SendMessageAction,
    SendPhotoAction,
    SendVideoAction,
    SendVoiceAction,
)
from .const import (
    PROTOCOL_IDENTIFIER,
    PROTOCOL_NAME,
    PROTOCOL_SUPPORT_AUTHOR,
    PROTOCOL_VERSION,
)
from .handle import (
    on_callback_query,
    on_channel_post,
    on_chat_member,
    on_edited_message,
    on_event,
    on_group_message,
    on_message,
    on_private_message,
)
from .io import EchoPacket, InPacket, OutPacket, TelegramPollingIO

__all__ = [
    # Protocol Stack
    "TelegramBotProtocol",
    # IO
    "TelegramPollingIO",
    "InPacket",
    "OutPacket",
    "EchoPacket",
    # Adapter
    "Adapter",
    "Action",
    "Echo",
    "Event",
    "MessageEvent",
    "PrivateMessageEvent",
    "GroupMessageEvent",
    "EditedMessageEvent",
    "ChannelPostEvent",
    "EditedChannelPostEvent",
    "CallbackQueryEvent",
    "ChatMemberEvent",
    "SendMessageAction",
    "SendPhotoAction",
    "SendDocumentAction",
    "SendVoiceAction",
    "SendAudioAction",
    "SendVideoAction",
    "SendAnimationAction",
    "AnswerCallbackQueryAction",
    "RawAction",
    # Constants
    "PROTOCOL_IDENTIFIER",
    "PROTOCOL_NAME",
    "PROTOCOL_SUPPORT_AUTHOR",
    "PROTOCOL_VERSION",
    # Handle decorators
    "on_callback_query",
    "on_channel_post",
    "on_chat_member",
    "on_edited_message",
    "on_event",
    "on_group_message",
    "on_message",
    "on_private_message",
]


class TelegramBotProtocol(ProtocolStack):
    """Telegram Bot 协议栈

    :param token: Telegram Bot Token（从 @BotFather 获取）
    :param polling_timeout: 长轮询超时（秒），默认 10
    :param bot_properties: 传给 aiogram DefaultBotProperties 的参数
    :param dp_kwargs: 传给 aiogram Dispatcher 构造的额外参数
    """

    def __init__(
        self,
        token: str,
        *,
        polling_timeout: int = 10,
        bot_properties: dict | None = None,
        dp_kwargs: dict | None = None,
    ) -> None:
        super().__init__()
        src = TelegramPollingIO(
            token,
            polling_timeout=polling_timeout,
            bot_properties=bot_properties,
            dp_kwargs=dp_kwargs,
        )
        self.adapter = Adapter()
        self.inputs = {src}
        self.outputs = {src}
