"""onebot_ext 的收录表、action 形状、回应组装与事件解析"""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from lemony_onebot_utils.onebot_ext import (
    EXTENSIONS,
    SPECS,
    ExtensionError,
    FetchCustomFace,
    GetEssenceMsgList,
    GetEssenceMsgListEcho,
    GetGroupMsgHistory,
    GroupMsgEmojiLike,
    GroupPoke,
    HistoryEcho,
    SendPoke,
    SetGroupReaction,
    SetMsgEmojiLike,
    UploadGroupFile,
    call_extension,
    find,
    for_impl,
    is_message_sent,
    parse_payload,
    try_extension,
)
from lemony_onebot_utils.onebot_ext.catalog import load_entries
from melobot.exceptions import ActionHandleError
from melobot.protocols.onebot.v11.adapter.echo import Echo
from melobot.protocols.onebot.v11.adapter.segment import TextSegment


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
    def __init__(
        self, echo: Echo | None = None, error: Exception | None = None
    ) -> None:
        self._echo = echo
        self._error = error

    async def unwrap(self, index: int) -> Echo | None:
        assert index == 0
        if self._error is not None:
            raise self._error
        return self._echo


class _Adapter:
    def __init__(self, group: _Group) -> None:
        self.group = group
        self.calls: list[Any] = []

    async def call_output(self, action: Any) -> _Group:
        self.calls.append(action)
        return self.group


def _adapter(echo: Echo | None = None, error: Exception | None = None) -> _Adapter:
    return _Adapter(_Group(echo, error))


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
    # group_id 可省略 (SnowLuma 的 group_id 是可选参数)
    assert SetGroupReaction(message_id=2, code="424").params == {
        "message_id": 2,
        "code": "424",
        "is_set": True,
    }
    assert GroupPoke(group_id=1, user_id=2).params == {"group_id": 1, "user_id": 2}
    # 只有 target_id 时不能把 user_id 写成 null
    assert GroupPoke(group_id=1, target_id=2).params == {"group_id": 1, "target_id": 2}
    assert SendPoke(user_id=2).params == {"user_id": 2}
    # 可选参数不传就不出现在 payload 里
    assert "folder" not in UploadGroupFile(group_id=1, file="a", name="a").params
    assert "folder_id" not in UploadGroupFile(group_id=1, file="a", name="a").params
    # 两种起始游标互斥地出现: SnowLuma 用 message_id, NapCat 用 message_seq
    by_id = GetGroupMsgHistory(group_id=1, message_id=2)
    by_seq = GetGroupMsgHistory(group_id=1, message_seq=2)
    assert "message_id" in by_id.params and "message_seq" not in by_id.params
    assert "message_seq" in by_seq.params and "message_id" not in by_seq.params
    # reverse_order 不传就不发, 传 False 也明确发出去
    assert "reverse_order" not in by_id.params
    assert (
        GetGroupMsgHistory(group_id=1, reverse_order=False).params["reverse_order"]
        is False
    )


@pytest.mark.asyncio
async def test_call_extension_returns_echo() -> None:
    adapter = _adapter(_echo())
    echo = await call_extension(adapter, SetMsgEmojiLike(message_id=1, emoji_id="1"))
    assert echo.is_ok()
    assert adapter.calls[0].extract()["action"] == "set_msg_emoji_like"


@pytest.mark.asyncio
async def test_call_extension_wraps_missing_echo() -> None:
    # unwrap 无回应时抛 ActionHandleError, call_extension 要转成 ExtensionError
    error = ActionHandleError("no echo", handle=cast(Any, None))
    with pytest.raises(ExtensionError) as exc_info:
        await call_extension(_adapter(error=error), FetchCustomFace())
    assert exc_info.value.action == "fetch_custom_face"
    assert exc_info.value.retcode is None
    assert await try_extension(_adapter(error=error), FetchCustomFace()) is None


@pytest.mark.asyncio
async def test_call_extension_raises_and_try_returns_none() -> None:
    echo = _echo(status="failed", retcode=1404)
    with pytest.raises(ExtensionError) as exc_info:
        await call_extension(
            _adapter(echo), SetMsgEmojiLike(message_id=1, emoji_id="1")
        )
    assert (exc_info.value.action, exc_info.value.retcode) == (
        "set_msg_emoji_like",
        1404,
    )
    assert (
        await try_extension(_adapter(echo), SetMsgEmojiLike(message_id=1, emoji_id="1"))
        is None
    )


@pytest.mark.asyncio
async def test_call_extension_assembles_typed_echo() -> None:
    # adapter 对未知 action 只给通用 Echo, 专用回应由 echo_cls 重新组装
    raw = _echo(data={"messages": [{"message_id": 1}]})
    echo = await call_extension(_adapter(raw), GetGroupMsgHistory(group_id=1))
    assert isinstance(echo, HistoryEcho)
    assert echo.messages == [{"message_id": 1}]


@pytest.mark.asyncio
async def test_essence_echo_resolves_segments() -> None:
    raw = _echo(
        data=[
            {
                "sender_id": 1,
                "sender_nick": "a",
                "sender_time": 1,
                "operator_id": 2,
                "operator_nick": "b",
                "operator_time": 2,
                "message_id": 3,
                "content": [{"type": "text", "data": {"text": "hi"}}],
            }
        ]
    )
    echo = await call_extension(_adapter(raw), GetEssenceMsgList(group_id=1))
    assert isinstance(echo, GetEssenceMsgListEcho)
    assert echo.data is not None
    assert isinstance(echo.data[0]["content"][0], TextSegment)


def test_catalog_data_matches_schema() -> None:
    base = files("lemony_onebot_utils.onebot_ext").joinpath("resources")
    schema = json.loads(base.joinpath("extensions.schema.json").read_text("utf-8"))
    data = json.loads(base.joinpath("extensions.json").read_text("utf-8"))
    Draft202012Validator(schema).validate(data)
    # 数据里的名字都应该被加载成条目, 不多不少
    assert len(data) == len(SPECS)
    assert {item["name"] for item in data} == set(EXTENSIONS)


def test_schema_rejects_bad_entries() -> None:
    base = files("lemony_onebot_utils.onebot_ext").joinpath("resources")
    schema = json.loads(base.joinpath("extensions.schema.json").read_text("utf-8"))
    validator = Draft202012Validator(schema)
    with pytest.raises(ValidationError):
        validator.validate([{"name": "x", "kind": "action"}])  # 缺 summary
    with pytest.raises(ValidationError):
        validator.validate(
            [{"name": "x", "kind": "action", "summary": "a", "impls": ["unknown"]}]
        )


def test_loader_rejects_bad_payloads() -> None:
    with pytest.raises(TypeError):
        parse_payload({"name": "x"})
    with pytest.raises(ValueError):
        parse_payload([{"name": "x", "kind": "action"}])
    with pytest.raises(ValueError):
        parse_payload([{"name": "x", "kind": "unknown", "summary": "a"}])
    with pytest.raises(ValueError):
        parse_payload(
            [{"name": "x", "kind": "action", "summary": "a", "impls": ["nope"]}]
        )
    with pytest.raises(ValueError):
        load_entries(
            [
                {"name": "x", "kind": "action", "summary": "a"},
                {"name": "x", "kind": "event", "summary": "b"},
            ]
        )


def test_catalog() -> None:
    spec = find("set_msg_emoji_like")
    assert spec is not None and spec.kind == "action"
    assert spec.supported_by("snowluma")
    event = find("group_msg_emoji_like")
    assert event is not None and event.kind == "event"
    assert find("nope") is None
    assert EXTENSIONS["set_group_reaction"].kind == "action"
    # essence 也是扩展, 已收录
    assert find("get_essence_msg_list") is not None
    snowluma_names = {item.name for item in for_impl("snowluma")}
    assert {"set_msg_emoji_like", "message_sent"} <= snowluma_names
    # Lagrange 的 OneBot 线已冻结, 不作为活跃实现端收录
    assert for_impl("lagrange") == ()
    with pytest.raises(ValueError):
        for_impl("SnowLuma")


def test_history_echo_messages() -> None:
    echo = HistoryEcho(
        status="ok", retcode=0, data={"messages": [{"message_id": 1}]}, action_type="x"
    )
    assert echo.messages == [{"message_id": 1}]
    empty = HistoryEcho(status="ok", retcode=0, data=None, action_type="x")
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
    # 字段缺失或类型畸形时退回 0/None, 不应抛异常
    empty = GroupMsgEmojiLike.from_raw({"notice_type": "group_msg_emoji_like"})
    assert empty is not None
    assert (empty.group_id, empty.message_id, empty.message_seq) == (0, 0, None)
    assert empty.likes == ()


def test_napcat_emoji_like_uses_is_add() -> None:
    base = {
        "notice_type": "group_msg_emoji_like",
        "group_id": 1,
        "user_id": 2,
        "message_id": 3,
        "likes": [{"emoji_id": "424", "count": 1}],
    }
    added = GroupMsgEmojiLike.from_raw({**base, "is_add": True})
    removed = GroupMsgEmojiLike.from_raw({**base, "is_add": False})
    assert added is not None and added.sub_type == "add"
    assert removed is not None and removed.sub_type == "remove"


def test_message_sent() -> None:
    assert is_message_sent({"post_type": "message_sent"})
    assert not is_message_sent({"post_type": "message"})
