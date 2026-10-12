import pytest
from mbplugin_quote.request import (
    ChatRequest,
    LimitExceeded,
    QuoteRequestError,
    check_limits,
    parse_chat_args,
)


@pytest.mark.parametrize(
    ("tokens", "expected"),
    [
        ([], ChatRequest()),
        (["-3..2"], ChatRequest(start=-3, end=2)),
        (["2..-3"], ChatRequest(start=-3, end=2)),
        (["-5..-2"], ChatRequest(start=-5, end=-2)),
        (["+1..3"], ChatRequest(start=1, end=3)),
        (["-5"], ChatRequest(start=-5, end=0)),
        (["3"], ChatRequest(start=0, end=3)),
        (["-s"], ChatRequest(sender_only=True)),
        (["2x", "-2..0", "-s"], ChatRequest(start=-2, end=0, sender_only=True, scale=2)),
        (["1.5X"], ChatRequest(scale=1.5)),
        (["", "  "], ChatRequest()),
    ],
)
def test_parse(tokens: list[str], expected: ChatRequest) -> None:
    assert parse_chat_args(tokens) == expected


@pytest.mark.parametrize(
    "tokens",
    [
        ["[-1,2]"],
        ["a2x"],
        ["-1..2", "3"],
        ["2x", "3x"],
        ["0x"],
        ["1..2..3"],
    ],
)
def test_parse_rejects(tokens: list[str]) -> None:
    with pytest.raises(QuoteRequestError):
        parse_chat_args(tokens)


def test_limits() -> None:
    check_limits(ChatRequest(start=-25, end=25, scale=3), max_offset=25, max_scale=3)
    with pytest.raises(LimitExceeded, match="区间"):
        check_limits(ChatRequest(start=-26), max_offset=25, max_scale=3)
    with pytest.raises(LimitExceeded, match="倍率"):
        check_limits(ChatRequest(scale=3.5), max_offset=25, max_scale=3)


def test_count_upper_bound() -> None:
    assert ChatRequest(start=-5, end=-2).message_count_upper_bound == 4
    assert ChatRequest().is_single
