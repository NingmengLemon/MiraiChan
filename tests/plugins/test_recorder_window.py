"""recorder 的 get_message_window 查询。

通过真实的 record_message 写入路径灌数据, 再按偏移区间取回, 断言偏移、顺序、
sender_only 过滤与媒体路径。数据库放在 tmp_path 下。
"""

import sys
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGINS_ROOT = REPO_ROOT / "packages" / "plugins"
if str(PLUGINS_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGINS_ROOT))

from lemony_storage_helper.database.sqlite import SqliteDatabaseHelper
from mbplugin_recorder.db.dto import (
    AccountInput,
    ConversationInput,
    IdentityInput,
    MediaSourceInput,
    MessageSegmentInput,
    RecordedMessageInput,
)
from mbplugin_recorder.db.enums import MediaDownloadStatus
from mbplugin_recorder.db.models import recorder_metadata
from mbplugin_recorder.db.operations import record_message
from mbplugin_recorder.db.views import MessageWindowQuery
from mbplugin_recorder.service import RecorderService

PROTOCOL = "onebot-v11"
SELF_ID = "10000"
GROUP = "20000"
T0 = datetime(2026, 1, 1, tzinfo=UTC)
ALICE, BOB = "30001", "30002"

# (消息 id, 发送者); 按时间先后排列, 基准取 m4
TIMELINE = [
    ("m0", ALICE),
    ("m1", BOB),
    ("m2", ALICE),
    ("m3", BOB),
    ("m4", ALICE),
    ("m5", BOB),
    ("m6", ALICE),
    ("m7", BOB),
]
BASE = "m4"


def _payload(
    mid: str, sender: str, at: datetime, segments: list[MessageSegmentInput]
) -> RecordedMessageInput:
    account = AccountInput(protocol=PROTOCOL, self_id=SELF_ID)
    return RecordedMessageInput(
        account=account,
        conversation=ConversationInput(type="group", external_id=GROUP),
        sender=IdentityInput(
            protocol=PROTOCOL,
            namespace="user",
            external_id=sender,
            display_name=f"nick-{sender}",
            account=account,
        ),
        external_message_id=mid,
        sent_at=at,
        sender_conversation_name=f"card-{sender}",
        segments=segments,
    )


def _text(text: str) -> MessageSegmentInput:
    return MessageSegmentInput(type="text", data={"text": text}, text=text)


@pytest_asyncio.fixture
async def service(tmp_path: Path) -> AsyncIterator[RecorderService]:
    db = SqliteDatabaseHelper(
        "recorder.db", metadata=recorder_metadata, relative_path_base=tmp_path
    )
    await db.startup()
    async with db.get_session(style="sqlalchemy") as session:
        for i, (mid, sender) in enumerate(TIMELINE):
            await record_message(
                session,
                _payload(mid, sender, T0 + timedelta(seconds=i), [_text(mid)]),
            )
    try:
        yield RecorderService(db)
    finally:
        await db.close()


def _query(start: int, end: int, *, sender_only: bool = False, base: str = BASE):
    return MessageWindowQuery(
        account_protocol=PROTOCOL,
        account_self_id=SELF_ID,
        conversation_type="group",
        conversation_external_id=GROUP,
        base_external_message_id=base,
        start=start,
        end=end,
        sender_only=sender_only,
    )


async def _ids(service: RecorderService, *args, **kwargs) -> list[tuple[int, str]]:
    views = await service.get_message_window(_query(*args, **kwargs))
    assert views is not None
    return [(v.offset, v.external_message_id) for v in views]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (0, 0, [(0, "m4")]),
        (-2, 1, [(-2, "m2"), (-1, "m3"), (0, "m4"), (1, "m5")]),
        # 端点顺序无关
        (1, -2, [(-2, "m2"), (-1, "m3"), (0, "m4"), (1, "m5")]),
        # 全负区间: 不含基准
        (-3, -2, [(-3, "m1"), (-2, "m2")]),
        # 全正区间
        (2, 3, [(2, "m6"), (3, "m7")]),
        # 超出记录范围时截断, 不报错
        (-10, 10, [(i - 4, f"m{i}") for i in range(8)]),
        (5, 9, []),
    ],
)
async def test_window_offsets(
    service: RecorderService, start: int, end: int, expected: list[tuple[int, str]]
) -> None:
    assert await _ids(service, start, end) == expected


@pytest.mark.asyncio
async def test_sender_only_counts_offsets_among_same_sender(
    service: RecorderService,
) -> None:
    # 基准 m4 是 ALICE; ALICE 的消息依次为 m0 m2 m4 m6
    assert await _ids(service, -2, 1, sender_only=True) == [
        (-2, "m0"),
        (-1, "m2"),
        (0, "m4"),
        (1, "m6"),
    ]


@pytest.mark.asyncio
async def test_excluded_senders_are_skipped_and_not_counted(
    service: RecorderService,
) -> None:
    q = _query(-2, 2)
    q.exclude_sender_external_ids = (BOB,)
    views = await service.get_message_window(q)
    assert views is not None
    # 去掉 BOB 后 ALICE 的序列是 m0 m2 m4 m6, 偏移按这个序列数
    assert [(v.offset, v.external_message_id) for v in views] == [
        (-2, "m0"),
        (-1, "m2"),
        (0, "m4"),
        (1, "m6"),
    ]


@pytest.mark.asyncio
async def test_excluded_base_gives_empty_window(service: RecorderService) -> None:
    q = _query(-1, 1, base="m3")
    q.exclude_sender_external_ids = (BOB,)
    assert await service.get_message_window(q) == []


@pytest.mark.asyncio
async def test_unknown_base_returns_none(service: RecorderService) -> None:
    assert await service.get_message_window(_query(0, 0, base="nope")) is None


@pytest.mark.asyncio
async def test_view_carries_names_and_segments(service: RecorderService) -> None:
    views = await service.get_message_window(_query(0, 0))
    assert views is not None
    (view,) = views
    assert view.sender_external_id == ALICE
    assert view.sender_conversation_name == f"card-{ALICE}"
    assert view.sender_display_name == f"nick-{ALICE}"
    assert [(s.type, dict(s.data)) for s in view.segments] == [
        ("text", {"text": "m4"})
    ]


@pytest.mark.asyncio
async def test_same_timestamp_is_ordered_by_insertion(tmp_path: Path) -> None:
    db = SqliteDatabaseHelper(
        "same.db", metadata=recorder_metadata, relative_path_base=tmp_path
    )
    await db.startup()
    try:
        async with db.get_session(style="sqlalchemy") as session:
            for mid in ("a", "b", "c"):
                await record_message(session, _payload(mid, ALICE, T0, [_text(mid)]))
        service = RecorderService(db)
        views = await service.get_message_window(_query(-1, 1, base="b"))
        assert views is not None
        assert [v.external_message_id for v in views] == ["a", "b", "c"]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_downloaded_media_paths_are_exposed(tmp_path: Path) -> None:
    db = SqliteDatabaseHelper(
        "media.db", metadata=recorder_metadata, relative_path_base=tmp_path
    )
    await db.startup()
    try:
        image_done = MessageSegmentInput(
            type="image",
            data={"file": "done.png", "url": "https://example.invalid/done"},
            media_sources=(
                MediaSourceInput(
                    source_file_id="done.png",
                    media_type="image",
                    url="https://example.invalid/done",
                    download_status=MediaDownloadStatus.DOWNLOADED,
                    sha256="0" * 64,
                    size=1,
                    cache_path="record/media/image/done.png",
                ),
            ),
        )
        image_pending = MessageSegmentInput(
            type="image",
            data={"file": "todo.png", "url": "https://example.invalid/todo"},
            media_sources=(
                MediaSourceInput(
                    source_file_id="todo.png",
                    media_type="image",
                    url="https://example.invalid/todo",
                ),
            ),
        )
        async with db.get_session(style="sqlalchemy") as session:
            await record_message(
                session, _payload("img", ALICE, T0, [image_done, image_pending])
            )
        views = await RecorderService(db).get_message_window(_query(0, 0, base="img"))
        assert views is not None
        assert [s.media_paths for s in views[0].segments] == [
            ("record/media/image/done.png",),
            (),
        ]
    finally:
        await db.close()
