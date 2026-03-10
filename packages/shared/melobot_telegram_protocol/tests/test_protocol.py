"""melobot_telegram_protocol 单元测试"""

from datetime import datetime

import pytest
from aiogram.methods import (
    AnswerCallbackQuery,
    SendAudio,
    SendDocument,
    SendMessage,
    SendPhoto,
    SendVideo,
    SendVoice,
)
from aiogram.types import (
    CallbackQuery,
    Chat,
    Message,
    Update,
    User,
)

# ============================================================
# 辅助工厂函数：构造 aiogram 测试数据
# ============================================================


def _make_user(user_id: int = 111, first_name: str = "TestUser") -> User:
    return User(id=user_id, is_bot=False, first_name=first_name)


def _make_chat(chat_id: int = 222, chat_type: str = "private") -> Chat:
    return Chat(id=chat_id, type=chat_type)


def _make_message(
    message_id: int = 1,
    text: str = "hello",
    chat_id: int = 222,
    chat_type: str = "private",
    user_id: int = 111,
) -> Message:
    return Message(
        message_id=message_id,
        date=datetime.now(),
        chat=_make_chat(chat_id, chat_type),
        from_user=_make_user(user_id),
        text=text,
    )


def _make_update_with_message(
    update_id: int = 1,
    text: str = "hello",
    chat_type: str = "private",
) -> Update:
    msg = _make_message(text=text, chat_type=chat_type)
    return Update(update_id=update_id, message=msg)


def _make_update_with_edited_message(update_id: int = 2) -> Update:
    msg = _make_message(text="edited")
    return Update(update_id=update_id, edited_message=msg)


def _make_update_with_callback_query(update_id: int = 3) -> Update:
    user = _make_user()
    msg = _make_message()
    cq = CallbackQuery(
        id="cq_123",
        chat_instance="inst",
        from_user=user,
        data="button_data",
        message=msg,
    )
    return Update(update_id=update_id, callback_query=cq)


def _make_update_with_channel_post(update_id: int = 4) -> Update:
    msg = _make_message(chat_type="channel")
    return Update(update_id=update_id, channel_post=msg)


# ============================================================
# Test: 基本导入
# ============================================================


class TestImports:
    def test_top_level_import(self):
        import melobot_telegram_protocol

        assert hasattr(melobot_telegram_protocol, "TelegramBotProtocol")
        assert hasattr(melobot_telegram_protocol, "Adapter")
        assert hasattr(melobot_telegram_protocol, "TelegramPollingIO")
        assert hasattr(melobot_telegram_protocol, "PROTOCOL_IDENTIFIER")

    def test_protocol_identifier(self):
        from melobot_telegram_protocol import PROTOCOL_IDENTIFIER

        assert "TelegramBot" in PROTOCOL_IDENTIFIER
        assert "Lemoneko" in PROTOCOL_IDENTIFIER

    def test_adapter_imports(self):
        from importlib import import_module

        mod = import_module("melobot_telegram_protocol.adapter")
        for name in [
            "Action",
            "Adapter",
            "CallbackQueryEvent",
            "Echo",
            "Event",
            "GroupMessageEvent",
            "MessageEvent",
            "PrivateMessageEvent",
        ]:
            assert hasattr(mod, name), f"adapter 缺少导出: {name}"

    def test_handle_imports(self):
        from importlib import import_module

        mod = import_module("melobot_telegram_protocol.handle")
        for name in [
            "on_callback_query",
            "on_channel_post",
            "on_chat_member",
            "on_edited_message",
            "on_event",
            "on_group_message",
            "on_message",
            "on_private_message",
        ]:
            assert hasattr(mod, name), f"handle 缺少导出: {name}"

    def test_io_imports(self):
        from importlib import import_module

        mod = import_module("melobot_telegram_protocol.io")
        for name in [
            "EchoPacket",
            "InPacket",
            "OutPacket",
            "TelegramPollingIO",
        ]:
            assert hasattr(mod, name), f"io 缺少导出: {name}"


# ============================================================
# Test: 常量
# ============================================================


class TestConst:
    def test_protocol_identifier_format(self):
        from melobot_telegram_protocol.const import (
            PROTOCOL_IDENTIFIER,
            PROTOCOL_NAME,
            PROTOCOL_SUPPORT_AUTHOR,
            PROTOCOL_VERSION,
        )

        expected = f"{PROTOCOL_NAME}-v{PROTOCOL_VERSION}@{PROTOCOL_SUPPORT_AUTHOR}"
        assert PROTOCOL_IDENTIFIER == expected


# ============================================================
# Test: IO Packet
# ============================================================


class TestPacket:
    def test_in_packet(self):
        from melobot_telegram_protocol.const import PROTOCOL_IDENTIFIER
        from melobot_telegram_protocol.io.packet import InPacket

        pkt = InPacket(data={"key": "value"})
        assert pkt.protocol == PROTOCOL_IDENTIFIER
        assert pkt.data == {"key": "value"}

    def test_out_packet(self):
        from melobot_telegram_protocol.io.packet import OutPacket

        pkt = OutPacket(data="some_method_obj")
        assert pkt.data == "some_method_obj"

    def test_echo_packet(self):
        from melobot_telegram_protocol.io.packet import EchoPacket

        pkt = EchoPacket(data={"msg_id": 42}, ok=True)
        assert pkt.ok is True
        assert pkt.data == {"msg_id": 42}

    def test_echo_packet_noecho(self):
        from melobot_telegram_protocol.io.packet import EchoPacket

        pkt = EchoPacket(noecho=True)
        assert pkt.noecho is True


# ============================================================
# Test: IO Source
# ============================================================


class TestTelegramPollingIO:
    def test_init(self):
        from melobot_telegram_protocol.const import PROTOCOL_IDENTIFIER
        from melobot_telegram_protocol.io.source import TelegramPollingIO

        io = TelegramPollingIO("fake_token:123")
        assert io.protocol == PROTOCOL_IDENTIFIER
        assert io.opened() is False

    def test_bot_property_raises_before_open(self):
        from melobot_telegram_protocol.io.source import TelegramPollingIO

        io = TelegramPollingIO("fake_token:123")
        with pytest.raises(RuntimeError, match="尚未打开"):
            _ = io.bot


# ============================================================
# Test: Event 解析
# ============================================================


class TestEventResolve:
    def test_resolve_private_message(self):
        from melobot_telegram_protocol.adapter.event import (
            Event,
            MessageEvent,
            PrivateMessageEvent,
        )

        update = _make_update_with_message(chat_type="private")
        event = Event.resolve(update)
        assert isinstance(event, PrivateMessageEvent)
        assert isinstance(event, MessageEvent)
        assert event.text == "hello"
        assert event.chat_type == "private"
        assert event.chat_id == 222

    def test_resolve_group_message(self):
        from melobot_telegram_protocol.adapter.event import (
            Event,
            GroupMessageEvent,
            MessageEvent,
        )

        update = _make_update_with_message(chat_type="group")
        event = Event.resolve(update)
        assert isinstance(event, GroupMessageEvent)
        assert isinstance(event, MessageEvent)
        assert event.chat_type == "group"
        assert event.group_id == 222

    def test_resolve_supergroup_message(self):
        from melobot_telegram_protocol.adapter.event import Event, GroupMessageEvent

        update = _make_update_with_message(chat_type="supergroup")
        event = Event.resolve(update)
        assert isinstance(event, GroupMessageEvent)

    def test_resolve_edited_message(self):
        from melobot_telegram_protocol.adapter.event import EditedMessageEvent, Event

        update = _make_update_with_edited_message()
        event = Event.resolve(update)
        assert isinstance(event, EditedMessageEvent)
        assert event.text == "edited"

    def test_resolve_callback_query(self):
        from melobot_telegram_protocol.adapter.event import CallbackQueryEvent, Event

        update = _make_update_with_callback_query()
        event = Event.resolve(update)
        assert isinstance(event, CallbackQueryEvent)
        assert event.callback_data == "button_data"
        assert event.from_user.id == 111
        assert event.chat_id == 222

    def test_resolve_channel_post(self):
        from melobot_telegram_protocol.adapter.event import ChannelPostEvent, Event

        update = _make_update_with_channel_post()
        event = Event.resolve(update)
        assert isinstance(event, ChannelPostEvent)

    def test_resolve_unknown_update(self):
        from melobot_telegram_protocol.adapter.event import Event

        update = Update(update_id=999)
        event = Event.resolve(update)
        # 未匹配的类型应回退为基类 Event
        assert type(event) is Event
        assert event.update_id == 999


# ============================================================
# Test: Event 内容构建
# ============================================================


class TestEventContents:
    def test_text_message_contents(self):
        from melobot.adapter.content import TextContent
        from melobot_telegram_protocol.adapter.event import Event

        update = _make_update_with_message(text="test text")
        event = Event.resolve(update)
        assert len(event.contents) >= 1
        assert isinstance(event.contents[0], TextContent)
        assert event.contents[0].text == "test text"

    def test_empty_text_gives_empty_string(self):
        from melobot_telegram_protocol.adapter.event import Event

        msg = Message(
            message_id=1,
            date=datetime.now(),
            chat=_make_chat(),
            from_user=_make_user(),
            text=None,
        )
        update = Update(update_id=10, message=msg)
        event = Event.resolve(update)
        assert event.text == ""

    def test_scope_is_chat_id(self):
        from melobot_telegram_protocol.adapter.event import Event

        update = _make_update_with_message(chat_type="group")
        event = Event.resolve(update)
        assert event.scope == 222


# ============================================================
# Test: Event repr
# ============================================================


class TestEventRepr:
    def test_base_event_repr(self):
        from melobot_telegram_protocol.adapter.event import Event

        update = Update(update_id=42)
        event = Event(update)
        assert "42" in repr(event)

    def test_message_event_repr(self):
        from melobot_telegram_protocol.adapter.event import Event

        update = _make_update_with_message(text="foo")
        event = Event.resolve(update)
        r = repr(event)
        assert "MessageEvent" in r
        assert "222" in r

    def test_callback_query_event_repr(self):
        from melobot_telegram_protocol.adapter.event import Event

        update = _make_update_with_callback_query()
        event = Event.resolve(update)
        assert "CallbackQueryEvent" in repr(event)
        assert "button_data" in repr(event)


# ============================================================
# Test: Action
# ============================================================


class TestAction:
    def test_send_message_action(self):
        from melobot_telegram_protocol.adapter.action import SendMessageAction

        action = SendMessageAction(chat_id=123, text="hello world")
        assert isinstance(action.method, SendMessage)
        assert action.method.text == "hello world"
        assert action.method.chat_id == 123

    def test_send_photo_action(self):
        from melobot_telegram_protocol.adapter.action import SendPhotoAction

        action = SendPhotoAction(chat_id=123, photo="file_id_xxx")
        assert isinstance(action.method, SendPhoto)

    def test_send_document_action(self):
        from melobot_telegram_protocol.adapter.action import SendDocumentAction

        action = SendDocumentAction(chat_id=123, document="file_id_xxx")
        assert isinstance(action.method, SendDocument)

    def test_send_voice_action(self):
        from melobot_telegram_protocol.adapter.action import SendVoiceAction

        action = SendVoiceAction(chat_id=123, voice="file_id_xxx")
        assert isinstance(action.method, SendVoice)

    def test_send_audio_action(self):
        from melobot_telegram_protocol.adapter.action import SendAudioAction

        action = SendAudioAction(chat_id=123, audio="file_id_xxx")
        assert isinstance(action.method, SendAudio)

    def test_send_video_action(self):
        from melobot_telegram_protocol.adapter.action import SendVideoAction

        action = SendVideoAction(chat_id=123, video="file_id_xxx")
        assert isinstance(action.method, SendVideo)

    def test_answer_callback_query_action(self):
        from melobot_telegram_protocol.adapter.action import AnswerCallbackQueryAction

        action = AnswerCallbackQueryAction(
            callback_query_id="cq_123", text="done", show_alert=True
        )
        assert isinstance(action.method, AnswerCallbackQuery)
        assert action.method.callback_query_id == "cq_123"
        assert action.method.show_alert is True

    def test_raw_action(self):
        from melobot_telegram_protocol.adapter.action import RawAction

        method = SendMessage(chat_id=1, text="raw")
        action = RawAction(method)
        assert action.method is method

    def test_action_repr(self):
        from melobot_telegram_protocol.adapter.action import SendMessageAction

        action = SendMessageAction(chat_id=123, text="hi")
        assert "SendMessage" in repr(action)

    def test_action_protocol(self):
        from melobot_telegram_protocol.adapter.action import SendMessageAction
        from melobot_telegram_protocol.const import PROTOCOL_IDENTIFIER

        action = SendMessageAction(chat_id=123, text="hi")
        assert action.protocol == PROTOCOL_IDENTIFIER


# ============================================================
# Test: Echo
# ============================================================


class TestEcho:
    def test_echo_ok(self):
        from melobot_telegram_protocol.adapter.echo import Echo

        echo = Echo(data={"message_id": 42}, ok=True)
        assert echo.is_ok() is True
        assert echo.result() == {"message_id": 42}

    def test_echo_fail(self):
        from melobot_telegram_protocol.adapter.echo import Echo

        echo = Echo(data=None, ok=False, prompt="API error")
        assert echo.is_ok() is False
        with pytest.raises(ValueError, match="API error"):
            echo.result()

    def test_echo_repr(self):
        from melobot_telegram_protocol.adapter.echo import Echo

        echo = Echo(data=42, ok=True)
        assert "ok=True" in repr(echo)


# ============================================================
# Test: Factory
# ============================================================


class TestFactory:
    @pytest.mark.asyncio
    async def test_event_factory(self):
        from melobot_telegram_protocol.adapter.base import EventFactory
        from melobot_telegram_protocol.adapter.event import PrivateMessageEvent
        from melobot_telegram_protocol.io.packet import InPacket

        update = _make_update_with_message(text="factory test")
        packet = InPacket(data=update)
        factory = EventFactory()
        event = await factory.create(packet)
        assert isinstance(event, PrivateMessageEvent)
        assert event.text == "factory test"

    @pytest.mark.asyncio
    async def test_output_factory(self):
        from melobot_telegram_protocol.adapter.action import SendMessageAction
        from melobot_telegram_protocol.adapter.base import OutputFactory

        action = SendMessageAction(chat_id=1, text="test")
        factory = OutputFactory()
        packet = await factory.create(action)
        assert packet.data is action.method

    @pytest.mark.asyncio
    async def test_echo_factory_noecho(self):
        from melobot_telegram_protocol.adapter.base import EchoFactory
        from melobot_telegram_protocol.io.packet import EchoPacket

        factory = EchoFactory()
        result = await factory.create(EchoPacket(noecho=True))
        assert result is None

    @pytest.mark.asyncio
    async def test_echo_factory_normal(self):
        from melobot_telegram_protocol.adapter.base import EchoFactory
        from melobot_telegram_protocol.io.packet import EchoPacket

        factory = EchoFactory()
        result = await factory.create(
            EchoPacket(data={"msg_id": 1}, ok=True, prompt="")
        )
        assert result is not None
        assert result.is_ok() is True
        assert result.data == {"msg_id": 1}


# ============================================================
# Test: Adapter 初始化
# ============================================================


class TestAdapter:
    def test_adapter_init(self):
        from melobot_telegram_protocol.adapter.base import Adapter
        from melobot_telegram_protocol.const import PROTOCOL_IDENTIFIER

        adapter = Adapter()
        assert adapter.protocol == PROTOCOL_IDENTIFIER


# ============================================================
# Test: ProtocolStack
# ============================================================


class TestProtocolStack:
    def test_telegram_bot_protocol(self):
        from melobot_telegram_protocol import TelegramBotProtocol

        proto = TelegramBotProtocol("fake_token:123")
        assert proto.adapter is not None
        assert len(proto.inputs) == 1
        assert len(proto.outputs) == 1
        # input 和 output 应该是同一个 IO source
        assert proto.inputs == proto.outputs
