from __future__ import annotations

from typing import Any

from aiogram.types import BufferedInputFile, URLInputFile
from melobot.adapter import (
    AbstractEchoFactory,
    AbstractEventFactory,
    AbstractOutputFactory,
    ActionHandleGroup,
)
from melobot.adapter import Adapter as RootAdapter
from melobot.handle import try_get_event

from ..const import PROTOCOL_IDENTIFIER
from ..io.packet import EchoPacket, InPacket, OutPacket
from ..io.source import TelegramPollingIO
from . import action as ac
from . import echo as ec
from . import event as ev


class EventFactory(AbstractEventFactory[InPacket, ev.Event]):
    async def create(self, packet: InPacket) -> ev.Event:
        return ev.Event.resolve(packet.data)


class OutputFactory(AbstractOutputFactory[OutPacket, ac.Action]):
    async def create(self, action: ac.Action) -> OutPacket:
        return OutPacket(data=action.method)


class EchoFactory(AbstractEchoFactory[EchoPacket, ec.Echo]):
    async def create(self, packet: EchoPacket) -> ec.Echo | None:
        if packet.noecho:
            return None
        return ec.Echo(
            data=packet.data,
            ok=packet.ok,
            prompt=packet.prompt,
        )


class Adapter(
    RootAdapter[
        EventFactory,
        OutputFactory,
        EchoFactory,
        ac.Action,
        TelegramPollingIO,
        TelegramPollingIO,
    ]
):
    """Telegram Bot 适配器"""

    def __init__(self) -> None:
        super().__init__(
            PROTOCOL_IDENTIFIER,
            EventFactory(),
            OutputFactory(),
            EchoFactory(),
        )

    def _get_chat_id(self) -> int:
        """从当前事件上下文获取 chat_id"""
        event = try_get_event()
        if event is None:
            raise RuntimeError("无法获取当前事件上下文中的 chat_id")
        if isinstance(event, ev.MessageEvent):
            return event.chat_id
        if isinstance(event, ev.CallbackQueryEvent) and event.chat_id is not None:
            return event.chat_id
        raise RuntimeError(f"无法从事件 {event} 中获取 chat_id")

    # === melobot 通用输出方法 ===

    async def __send_text__(self, text: str) -> ActionHandleGroup[ec.Echo]:
        chat_id = self._get_chat_id()
        return await self.call_output(ac.SendMessageAction(chat_id, text))

    async def __send_image__(
        self,
        name: str,
        raw: bytes | None = None,
        url: str | None = None,
        mimetype: str | None = None,
    ) -> ActionHandleGroup[ec.Echo]:
        chat_id = self._get_chat_id()
        if raw is not None:
            photo = BufferedInputFile(raw, filename=name)
        elif url is not None:
            photo = URLInputFile(url, filename=name)
        else:
            raise ValueError("发送图片需要提供 raw 或 url 参数")
        return await self.call_output(ac.SendPhotoAction(chat_id, photo))

    async def __send_voice__(
        self,
        name: str,
        raw: bytes | None = None,
        url: str | None = None,
        mimetype: str | None = None,
    ) -> ActionHandleGroup[ec.Echo]:
        chat_id = self._get_chat_id()
        if raw is not None:
            voice = BufferedInputFile(raw, filename=name)
        elif url is not None:
            voice = URLInputFile(url, filename=name)
        else:
            raise ValueError("发送语音需要提供 raw 或 url 参数")
        return await self.call_output(ac.SendVoiceAction(chat_id, voice))

    async def __send_audio__(
        self,
        name: str,
        raw: bytes | None = None,
        url: str | None = None,
        mimetype: str | None = None,
    ) -> ActionHandleGroup[ec.Echo]:
        chat_id = self._get_chat_id()
        if raw is not None:
            audio = BufferedInputFile(raw, filename=name)
        elif url is not None:
            audio = URLInputFile(url, filename=name)
        else:
            raise ValueError("发送音频需要提供 raw 或 url 参数")
        return await self.call_output(ac.SendAudioAction(chat_id, audio))

    async def __send_video__(
        self,
        name: str,
        raw: bytes | None = None,
        url: str | None = None,
        mimetype: str | None = None,
    ) -> ActionHandleGroup[ec.Echo]:
        chat_id = self._get_chat_id()
        if raw is not None:
            video = BufferedInputFile(raw, filename=name)
        elif url is not None:
            video = URLInputFile(url, filename=name)
        else:
            raise ValueError("发送视频需要提供 raw 或 url 参数")
        return await self.call_output(ac.SendVideoAction(chat_id, video))

    async def __send_media__(
        self,
        name: str,
        raw: bytes | None = None,
        url: str | None = None,
        mimetype: str | None = None,
    ) -> ActionHandleGroup[ec.Echo]:
        chat_id = self._get_chat_id()
        if raw is not None:
            doc = BufferedInputFile(raw, filename=name)
        elif url is not None:
            doc = URLInputFile(url, filename=name)
        else:
            raise ValueError("发送媒体需要提供 raw 或 url 参数")
        return await self.call_output(ac.SendDocumentAction(chat_id, doc))

    # === Telegram 特有方法 ===

    async def send_message(
        self,
        chat_id: int | str,
        text: str,
        *,
        parse_mode: str | None = None,
        **kwargs: Any,
    ) -> ActionHandleGroup[ec.Echo]:
        """发送文本消息到指定 chat"""
        return await self.call_output(
            ac.SendMessageAction(chat_id, text, parse_mode=parse_mode, **kwargs)
        )

    async def send_photo(
        self,
        chat_id: int | str,
        photo: Any,
        *,
        caption: str | None = None,
        **kwargs: Any,
    ) -> ActionHandleGroup[ec.Echo]:
        """发送图片到指定 chat"""
        return await self.call_output(
            ac.SendPhotoAction(chat_id, photo, caption=caption, **kwargs)
        )

    async def send_document(
        self,
        chat_id: int | str,
        document: Any,
        *,
        caption: str | None = None,
        **kwargs: Any,
    ) -> ActionHandleGroup[ec.Echo]:
        """发送文件到指定 chat"""
        return await self.call_output(
            ac.SendDocumentAction(chat_id, document, caption=caption, **kwargs)
        )

    async def send_voice(
        self,
        chat_id: int | str,
        voice: Any,
        *,
        caption: str | None = None,
        **kwargs: Any,
    ) -> ActionHandleGroup[ec.Echo]:
        """发送语音到指定 chat"""
        return await self.call_output(
            ac.SendVoiceAction(chat_id, voice, caption=caption, **kwargs)
        )

    async def send_audio(
        self,
        chat_id: int | str,
        audio: Any,
        *,
        caption: str | None = None,
        **kwargs: Any,
    ) -> ActionHandleGroup[ec.Echo]:
        """发送音频文件到指定 chat"""
        return await self.call_output(
            ac.SendAudioAction(chat_id, audio, caption=caption, **kwargs)
        )

    async def send_video(
        self,
        chat_id: int | str,
        video: Any,
        *,
        caption: str | None = None,
        **kwargs: Any,
    ) -> ActionHandleGroup[ec.Echo]:
        """发送视频到指定 chat"""
        return await self.call_output(
            ac.SendVideoAction(chat_id, video, caption=caption, **kwargs)
        )

    async def answer_callback_query(
        self,
        callback_query_id: str,
        *,
        text: str | None = None,
        show_alert: bool = False,
        **kwargs: Any,
    ) -> ActionHandleGroup[ec.Echo]:
        """回应回调查询"""
        return await self.call_output(
            ac.AnswerCallbackQueryAction(
                callback_query_id, text=text, show_alert=show_alert, **kwargs
            )
        )

    async def call_api(self, method: Any) -> ActionHandleGroup[ec.Echo]:
        """直接调用任意 aiogram method 对象"""
        return await self.call_output(ac.RawAction(method))
