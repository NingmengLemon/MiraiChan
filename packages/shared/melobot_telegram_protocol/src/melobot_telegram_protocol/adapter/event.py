from __future__ import annotations

from aiogram.types import (
    CallbackQuery,
    ChatMemberUpdated,
    Message,
    Update,
)
from melobot.adapter import Event as RootEvent
from melobot.adapter import TextEvent as RootTextEvent
from melobot.adapter import content as mc

from ..const import PROTOCOL_IDENTIFIER


class Event(RootEvent):
    """Telegram 事件基类"""

    def __init__(self, update: Update) -> None:
        super().__init__(PROTOCOL_IDENTIFIER)
        self.raw = update
        self.update_id = update.update_id

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(update_id={self.update_id})"

    @classmethod
    def resolve(cls, update: Update) -> Event:
        """根据 Update 类型创建对应的事件"""
        if update.message is not None:
            return MessageEvent._resolve_by_chat_type(update, update.message)
        if update.edited_message is not None:
            return EditedMessageEvent(update, update.edited_message)
        if update.callback_query is not None:
            return CallbackQueryEvent(update, update.callback_query)
        if update.channel_post is not None:
            return ChannelPostEvent(update, update.channel_post)
        if update.edited_channel_post is not None:
            return EditedChannelPostEvent(update, update.edited_channel_post)
        if update.my_chat_member is not None:
            return ChatMemberEvent(update, update.my_chat_member)
        if update.chat_member is not None:
            return ChatMemberEvent(update, update.chat_member)
        # 其他未细化的 update 类型
        return cls(update)


class MessageEvent(RootTextEvent, Event):
    """Telegram 消息事件"""

    def __init__(self, update: Update, message: Message) -> None:
        Event.__init__(self, update)
        self.message = message
        self.chat_id = message.chat.id
        self.chat_type = message.chat.type
        self.message_id = message.message_id
        self.from_user = message.from_user
        self.text = message.text or message.caption or ""
        self.textlines = self.text.split("\n")
        self.contents: tuple[mc.Content, ...] = self._build_contents()
        self.scope = self.chat_id

    def _build_contents(self) -> tuple[mc.Content, ...]:
        contents: list[mc.Content] = []
        if self.message.text:
            contents.append(mc.TextContent(self.message.text))
        if self.message.photo:
            # 取最大分辨率的图片
            photo = self.message.photo[-1]
            contents.append(
                mc.ImageContent(
                    name=photo.file_unique_id,
                    url=None,
                    raw=None,
                )
            )
        if self.message.document:
            doc = self.message.document
            contents.append(
                mc.MediaContent(
                    name=doc.file_name or doc.file_unique_id,
                    url=None,
                    raw=None,
                    mimetype=doc.mime_type,
                )
            )
        if self.message.voice:
            voice = self.message.voice
            contents.append(
                mc.VoiceContent(
                    name=voice.file_unique_id,
                    url=None,
                    raw=None,
                    mimetype=voice.mime_type,
                )
            )
        if self.message.audio:
            audio = self.message.audio
            contents.append(
                mc.AudioContent(
                    name=audio.file_name or audio.file_unique_id,
                    url=None,
                    raw=None,
                    mimetype=audio.mime_type,
                )
            )
        if self.message.video:
            video = self.message.video
            contents.append(
                mc.VideoContent(
                    name=video.file_name or video.file_unique_id,
                    url=None,
                    raw=None,
                    mimetype=video.mime_type,
                )
            )
        if self.message.sticker:
            sticker = self.message.sticker
            contents.append(
                mc.ImageContent(
                    name=sticker.file_unique_id,
                    url=None,
                    raw=None,
                )
            )
        return tuple(contents) if contents else (mc.TextContent(""),)

    def __repr__(self) -> str:
        user = self.from_user
        user_repr = f"{user.full_name}({user.id})" if user else "unknown"
        return (
            f"MessageEvent(chat_id={self.chat_id}, "
            f"from={user_repr}, text={self.text!r:.30})"
        )

    @classmethod
    def _resolve_by_chat_type(cls, update: Update, message: Message) -> MessageEvent:
        """根据 chat type 返回更具体的消息事件"""
        chat_type = message.chat.type
        if chat_type == "private":
            return PrivateMessageEvent(update, message)
        if chat_type in ("group", "supergroup"):
            return GroupMessageEvent(update, message)
        return cls(update, message)


class PrivateMessageEvent(MessageEvent):
    """私聊消息事件"""

    pass


class GroupMessageEvent(MessageEvent):
    """群组消息事件"""

    def __init__(self, update: Update, message: Message) -> None:
        super().__init__(update, message)
        self.group_id = message.chat.id


class EditedMessageEvent(MessageEvent):
    """消息编辑事件"""

    pass


class ChannelPostEvent(MessageEvent):
    """频道帖子事件"""

    pass


class EditedChannelPostEvent(MessageEvent):
    """编辑后的频道帖子事件"""

    pass


class CallbackQueryEvent(Event):
    """回调查询事件（按钮点击）"""

    def __init__(self, update: Update, callback_query: CallbackQuery) -> None:
        super().__init__(update)
        self.callback_query = callback_query
        self.callback_data = callback_query.data
        self.from_user = callback_query.from_user
        self.message = callback_query.message
        if self.message and hasattr(self.message, "chat"):
            self.chat_id = self.message.chat.id
            self.scope = self.chat_id
        else:
            self.chat_id = None

    def __repr__(self) -> str:
        return (
            f"CallbackQueryEvent(data={self.callback_data!r}, "
            f"from={self.from_user.full_name}({self.from_user.id}))"
        )


class ChatMemberEvent(Event):
    """聊天成员变动事件"""

    def __init__(self, update: Update, member_update: ChatMemberUpdated) -> None:
        super().__init__(update)
        self.chat = member_update.chat
        self.from_user = member_update.from_user
        self.old_member = member_update.old_chat_member
        self.new_member = member_update.new_chat_member
        self.scope = member_update.chat.id

    def __repr__(self) -> str:
        return f"ChatMemberEvent(chat={self.chat.id}, from={self.from_user.full_name})"
