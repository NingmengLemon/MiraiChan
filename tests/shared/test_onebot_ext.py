"""lemony_onebot_utils.onebot_ext 的收录表、action 形状与回应解析"""

from __future__ import annotations

from typing import Any

import pytest
from lemony_onebot_utils.onebot_ext import (
    EXTENSIONS,
    ExtensionError,
    GetGroupMsgHistory,
    GroupMsgEmojiLike,
    GroupPoke,
    HistoryEcho,
    SetGroupReaction,
    SetMsgEmojiLike,
    UploadGroupFile,
    call_extension,
    find,
    for_impl,
    is_message_sent,
    try_extension,
)
from melobot.protocols.onebot.v11.adapter.echo import Echo


def _echo(**over: Any) -> Echo:
    data: dict[str, Any] = {
        "status": "ok",
        "retcode": 0,
        "data": None,
        "action_type": "x",
    }
    data.update(over)
    return Echo(**data)


class _Group:
    def __init__(self, echo: Echo | None) -> None:
        self._echo = echo

    async def unwrap(self, index: int) -> Echo | None:
        assert index == 0
        return self._echo


class _Adapter:
    def __init__(self, echo: Echo | None) -> None:
        self.echo = echo
        self.calls: list[Any] = []

    async def call_output(self, action: Any) -> _Group:
        self.calls.append(action)
        return _Group(self.echo)


def test_action_params() -> None:
    assert SetMsgEmojiLike(message_id=7, emoji_id="128308").params == {
        "message_id": 7,
        "emoji_id": "128308",
        "set": True,
    }
    assert SetGroupReaction(
        group_id=1, message_id=2, code="424", is_set=False
    ).params == {
        "group_id": 1,
        "message_id": 2,
        "code": "424",
        "is_set": False,
    }
    assert GroupPoke(group_id=1, user_id=2).params == {"group_id": 1, "user_id": 2}
    # folder 不传就不出现在参数里
    assert "folder" not in UploadGroupFile(group_id=1, file="a", name="a").params
    assert GetGroupMsgHistory(group_id=1, message_id=2, count=3).action_name == (
        "get_group_msg_history"
    )


@pytest.mark.asyncio
async def test_call_extension_returns_echo() -> None:
    adapter = _Adapter(_echo())
    echo = await call_extension(adapter, SetMsgEmojiLike(message_id=1, emoji_id="1"))
    assert echo.is_ok()
    assert adapter.calls[0].extract()["action"] == "set_msg_emoji_like"


@pytest.mark.asyncio
async def test_call_extension_raises_and_try_returns_none() -> None:
    echo = _echo(status="failed", retcode=1404)
    with pytest.raises(ExtensionError) as exc_info:
        await call_extension(
            _Adapter(echo), SetMsgEmojiLike(message_id=1, emoji_id="1")
        )
    assert (exc_info.value.action, exc_info.value.retcode) == (
        "set_msg_emoji_like",
        1404,
    )
    assert (
        await try_extension(_Adapter(echo), SetMsgEmojiLike(message_id=1, emoji_id="1"))
        is None
    )


@pytest.mark.asyncio
async def test_try_extension_returns_none_without_echo() -> None:
    assert (
        await try_extension(_Adapter(None), SetMsgEmojiLike(message_id=1, emoji_id="1"))
        is None
    )


def test_catalog() -> None:
    spec = find("set_msg_emoji_like")
    assert spec is not None and spec.kind == "action"
    assert spec.supported_by("snowluma")
    event = find("group_msg_emoji_like")
    assert event is not None and event.kind == "event"
    assert find("nope") is None
    assert EXTENSIONS["set_group_reaction"].kind == "action"
    snowluma_names = {item.name for item in for_impl("snowluma")}
    assert {"set_msg_emoji_like", "message_sent"} <= snowluma_names


def test_history_echo_messages() -> None:
    class _History(HistoryEcho):
        pass

    echo = _History(
        status="ok", retcode=0, data={"messages": [{"message_id": 1}]}, action_type="x"
    )
    assert echo.messages == [{"message_id": 1}]
    empty = _History(status="ok", retcode=0, data=None, action_type="x")
    assert empty.messages == []


def test_group_msg_emoji_like() -> None:
    raw = {
        "notice_type": "group_msg_emoji_like",
        "sub_type": "add",
        "group_id": 1,
        "user_id": 2,
        "operator_id": 2,
        "message_id": 3,
        "message_seq": 4,
        "likes": [{"emoji_id": "424", "count": 2}],
    }
    parsed = GroupMsgEmojiLike.from_raw(raw)
    assert parsed is not None
    assert (parsed.group_id, parsed.message_id, parsed.sub_type) == (1, 3, "add")
    assert [(like.emoji_id, like.count) for like in parsed.likes] == [("424", 2)]
    assert GroupMsgEmojiLike.from_raw({"notice_type": "group_upload"}) is None


def test_message_sent() -> None:
    assert is_message_sent({"post_type": "message_sent"})
    assert not is_message_sent({"post_type": "message"})
