from __future__ import annotations

from typing import Any

from aiogram.methods import (
    AnswerCallbackQuery,
    SendAnimation,
    SendAudio,
    SendDocument,
    SendMessage,
    SendPhoto,
    SendVideo,
    SendVoice,
)
from aiogram.methods.base import TelegramMethod
from melobot.adapter import Action as RootAction
from melobot.adapter.content import TextContent
from melobot.handle import try_get_event

from ..const import PROTOCOL_IDENTIFIER


class Action(RootAction):
    """Telegram 行为基类"""

    def __init__(self, method: TelegramMethod[Any]) -> None:
        self.method = method
        super().__init__(
            protocol=PROTOCOL_IDENTIFIER,
            trigger=try_get_event(),
            contents=(TextContent(repr(method)),),
        )

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(method={self.method.__class__.__name__})"


class SendMessageAction(Action):
    """发送文本消息"""

    def __init__(
        self,
        chat_id: int | str,
        text: str,
        *,
        parse_mode: str | None = None,
        reply_to_message_id: int | None = None,
        **kwargs: Any,
    ) -> None:
        method = SendMessage(
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode,
            **kwargs,
        )
        super().__init__(method)


class SendPhotoAction(Action):
    """发送图片"""

    def __init__(
        self,
        chat_id: int | str,
        photo: Any,
        *,
        caption: str | None = None,
        parse_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        method = SendPhoto(
            chat_id=chat_id,
            photo=photo,
            caption=caption,
            parse_mode=parse_mode,
            **kwargs,
        )
        super().__init__(method)


class SendDocumentAction(Action):
    """发送文件"""

    def __init__(
        self,
        chat_id: int | str,
        document: Any,
        *,
        caption: str | None = None,
        **kwargs: Any,
    ) -> None:
        method = SendDocument(
            chat_id=chat_id,
            document=document,
            caption=caption,
            **kwargs,
        )
        super().__init__(method)


class SendVoiceAction(Action):
    """发送语音"""

    def __init__(
        self,
        chat_id: int | str,
        voice: Any,
        *,
        caption: str | None = None,
        **kwargs: Any,
    ) -> None:
        method = SendVoice(
            chat_id=chat_id,
            voice=voice,
            caption=caption,
            **kwargs,
        )
        super().__init__(method)


class SendAudioAction(Action):
    """发送音频文件"""

    def __init__(
        self,
        chat_id: int | str,
        audio: Any,
        *,
        caption: str | None = None,
        **kwargs: Any,
    ) -> None:
        method = SendAudio(
            chat_id=chat_id,
            audio=audio,
            caption=caption,
            **kwargs,
        )
        super().__init__(method)


class SendVideoAction(Action):
    """发送视频"""

    def __init__(
        self,
        chat_id: int | str,
        video: Any,
        *,
        caption: str | None = None,
        **kwargs: Any,
    ) -> None:
        method = SendVideo(
            chat_id=chat_id,
            video=video,
            caption=caption,
            **kwargs,
        )
        super().__init__(method)


class SendAnimationAction(Action):
    """发送 GIF 动图"""

    def __init__(
        self,
        chat_id: int | str,
        animation: Any,
        *,
        caption: str | None = None,
        **kwargs: Any,
    ) -> None:
        method = SendAnimation(
            chat_id=chat_id,
            animation=animation,
            caption=caption,
            **kwargs,
        )
        super().__init__(method)


class AnswerCallbackQueryAction(Action):
    """回应回调查询"""

    def __init__(
        self,
        callback_query_id: str,
        *,
        text: str | None = None,
        show_alert: bool = False,
        url: str | None = None,
        cache_time: int | None = None,
    ) -> None:
        method = AnswerCallbackQuery(
            callback_query_id=callback_query_id,
            text=text,
            show_alert=show_alert,
            url=url,
            cache_time=cache_time,
        )
        super().__init__(method)


class RawAction(Action):
    """原始行为：直接传入 aiogram method 对象"""

    def __init__(self, method: TelegramMethod[Any]) -> None:
        super().__init__(method)
