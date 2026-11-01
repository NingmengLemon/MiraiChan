"""quote 的 IO 层: 来源回退、存档、资源获取 (不联网, 不碰 data/)。"""

import asyncio
import json
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote

import pytest
from lemony_storage_helper.database.sqlite import SqliteDatabaseHelper
from mbplugin_quote.archive import ArchiveRecord, QuoteArchive, quote_metadata
from mbplugin_quote.model import ImageRef, SourceMessage
from mbplugin_quote.request import ChatRequest
from mbplugin_quote.resources import FetchLimits, ResourceResolver
from mbplugin_quote.sources import fetch_messages, source_from_onebot
from PIL import Image, ImageFont
from sqlalchemy.ext.asyncio import AsyncSession

# ---------- sources ----------


@dataclass
class Seg:
    type: str
    data: dict
    media_paths: tuple[str, ...] = ()


@dataclass
class View:
    external_message_id: str
    sender_external_id: str
    sender_display_name: str | None = "nick"
    sender_conversation_name: str | None = "card"
    segments: list[Seg] = field(default_factory=list)


class FakeRecorder:
    def __init__(self, views):
        self.views = views
        self.queries: list[dict] = []

    async def query_message_window(self, **query):
        self.queries.append(query)
        return self.views


ONE = SourceMessage("b", 2, None, "二", ())


async def fetch_one(mid: str):
    return ONE if mid == "b" else None


def make_query(req, mid):
    return {
        "start": req.start,
        "end": req.end,
        "sender_only": req.sender_only,
        "base_external_message_id": mid,
    }


@pytest.mark.asyncio
async def test_recorder_hit() -> None:
    rec = FakeRecorder([View("b", "2", segments=[Seg("image", {"url": "u"}, ("p",))])])
    r = await fetch_messages(
        ChatRequest(start=-1),
        "b",
        recorder=rec,
        make_query=make_query,
        fetch_one=fetch_one,
    )
    assert r is not None and r.from_recorder
    (m,) = r.messages
    assert (m.sender_id, m.sender_card, m.segments[0].local_paths) == (
        2,
        "card",
        ("p",),
    )
    assert rec.queries == [
        {
            "start": -1,
            "end": 0,
            "sender_only": False,
            "base_external_message_id": "b",
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("req", "count", "degraded"),
    [
        (ChatRequest(), 1, False),
        (ChatRequest(start=-3, end=1), 1, True),
        (ChatRequest(start=-3, end=-1), 0, True),
    ],
)
async def test_fallback_to_get_msg(
    req: ChatRequest, count: int, degraded: bool
) -> None:
    r = await fetch_messages(
        req,
        "b",
        recorder=FakeRecorder(None),
        make_query=make_query,
        fetch_one=fetch_one,
    )
    assert r is not None and not r.from_recorder
    assert (len(r.messages), r.degraded_to_single) == (count, degraded)


@pytest.mark.asyncio
async def test_nothing_found() -> None:
    r = await fetch_messages(
        ChatRequest(), "zz", recorder=None, make_query=make_query, fetch_one=fetch_one
    )
    assert r is None


def test_quote_does_not_import_recorder_internals() -> None:
    quote_dir = (
        Path(__file__).resolve().parents[3] / "packages" / "plugins" / "mbplugin_quote"
    )
    offenders = [
        path.name
        for path in quote_dir.glob("*.py")
        if "from mbplugin_recorder" in path.read_text(encoding="utf-8")
    ]
    assert not offenders, (
        "quote 只能通过 recorder_service share 的公开方法取窗口, 不能 import recorder 的 DB 视图: "
        f"{offenders}"
    )


def test_source_from_onebot_drops_card_equal_to_nickname() -> None:
    m = source_from_onebot(
        "1", 5, "同", "同", [{"type": "text", "data": {"text": "x"}}]
    )
    assert (m.sender_card, m.sender_nickname, m.segments[0].type) == (
        None,
        "同",
        "text",
    )


# ---------- archive ----------


def _record(**kw) -> ArchiveRecord:
    base = {
        "style": "chat",
        "group_id": 1,
        "requester_id": 2,
        "base_message_id": "m",
        "range_start": -1,
        "range_end": 0,
        "sender_only": False,
        "scale": 1.0,
        "sender_ids": [3, 4],
        "width": 10,
        "height": 20,
    }
    base.update(kw)
    return ArchiveRecord(**base)


@pytest.mark.asyncio
async def test_archive_roundtrip(tmp_path: Path) -> None:
    db = SqliteDatabaseHelper("quote.db", quote_metadata, relative_path_base=tmp_path)
    await db.startup()
    try:
        archive = QuoteArchive(db, tmp_path / "artifacts")
        seen = []

        async def hook(artifact, path):
            seen.append((artifact.id, path.read_bytes()))

        archive.add_hook(hook)
        art = await archive.save(_record(), b"jpegdata", "jpg")
        path = archive.root / art.path
        assert path.read_bytes() == b"jpegdata"
        assert (art.size, art.format, json.loads(art.sender_ids)) == (8, "jpg", [3, 4])
        assert seen == [(art.id, b"jpegdata")]
        assert not list(path.parent.glob("*.tmp"))

        assert await archive.find_by_sent_message("sent-1") is None
        await archive.attach_sent_message(art.id, "sent-1")
        found = await archive.find_by_sent_message("sent-1")
        assert found is not None and found.id == art.id

        assert await archive.delete(art.id)
        assert not path.exists()
        assert await archive.find_by_sent_message("sent-1") is None
        assert not await archive.delete(art.id)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_delete_keeps_index_when_file_cannot_be_moved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = SqliteDatabaseHelper("quote.db", quote_metadata, relative_path_base=tmp_path)
    await db.startup()
    try:
        archive = QuoteArchive(db, tmp_path / "artifacts")
        art = await archive.save(_record(), b"jpegdata", "jpg")
        await archive.attach_sent_message(art.id, "sent-locked")

        def deny_replace(self: Path, target: Path) -> Path:
            raise PermissionError("file is locked")

        monkeypatch.setattr(Path, "replace", deny_replace)
        with pytest.raises(OSError):
            await archive.delete(art.id)

        # 文件没移走, 索引不能先删
        assert (archive.root / art.path).exists()
        assert await archive.find_by_sent_message("sent-locked") is not None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_delete_restores_file_when_db_delete_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = SqliteDatabaseHelper("quote.db", quote_metadata, relative_path_base=tmp_path)
    await db.startup()
    try:
        archive = QuoteArchive(db, tmp_path / "artifacts")
        art = await archive.save(_record(), b"jpegdata", "jpg")
        await archive.attach_sent_message(art.id, "sent-db-fail")
        original_path = archive.root / art.path

        async def fail_delete(self: AsyncSession, instance: object) -> None:
            raise RuntimeError("db down")

        monkeypatch.setattr(AsyncSession, "delete", fail_delete)
        with pytest.raises(RuntimeError, match="db down"):
            await archive.delete(art.id)

        # 索引没删成, 文件必须从临时名恢复
        assert original_path.exists()
        assert await archive.find_by_sent_message("sent-db-fail") is not None
        assert not list(original_path.parent.glob("*.deleting-*"))
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_hook_failure_does_not_lose_artifact(tmp_path: Path) -> None:
    db = SqliteDatabaseHelper("quote.db", quote_metadata, relative_path_base=tmp_path)
    await db.startup()
    try:
        archive = QuoteArchive(db, tmp_path / "a")

        async def bad(artifact, path):
            raise RuntimeError("boom")

        archive.add_hook(bad)
        art = await archive.save(_record(), b"x", "png")
        assert (archive.root / art.path).exists()
    finally:
        await db.close()


# ---------- resources ----------


def _png(color=(1, 2, 3), size=(4000, 100)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


@pytest.mark.asyncio
async def test_resolver_local_first_and_failures_are_collected(tmp_path: Path) -> None:
    (tmp_path / "record").mkdir()
    (tmp_path / "record" / "a.png").write_bytes(_png())
    outside = tmp_path.parent / "outside.png"
    outside.write_bytes(_png())

    async def avatars(uid: int) -> bytes:
        if uid == 2:
            raise ConnectionError
        if uid == 3:
            await asyncio.sleep(10)
        return _png((9, 9, 9), (64, 64))

    r = ResourceResolver(
        data_root=tmp_path,
        avatar_source=avatars,
        emoji_cdn=None,
        limits=FetchLimits(timeout=0.2, max_image_side=512),
    )
    try:
        bundle = await r.resolve(
            images=[
                ImageRef(url=None, local_paths=("record/a.png",)),
                # 越出 data 根的路径不读
                ImageRef(url=None, local_paths=(str(outside),)),
            ],
            avatars=[1, 2, 3],
            emojis=["😀"],
        )
    finally:
        await r.close()
    assert bundle.images["record/a.png"].size == (512, 13)
    assert set(bundle.avatars) == {1}
    assert not bundle.emojis
    assert len(bundle.missing) == 3


def _font_file(tmp_path: Path) -> Path:
    """把 Pillow 自带的字体落到文件, 当作 emoji 字体用 (单色足以验证接线)

    字体里真有字形的 emoji 用 ©, 真缺的用 🫠 (Emoji 14, 这个字体没有)。
    """
    if (tmp_path / "emoji.otf").exists():
        return tmp_path / "emoji.otf"
    font = ImageFont.load_default(28)
    assert isinstance(font, ImageFont.FreeTypeFont)
    path = tmp_path / "emoji.otf"
    embedded = font.path
    if isinstance(embedded, BytesIO):
        path.write_bytes(embedded.getvalue())
    else:
        assert isinstance(embedded, str)
        path.write_bytes(Path(embedded).read_bytes())
    return path


def _png_bytes(size: tuple[int, int] = (24, 24)) -> bytes:
    buf = BytesIO()
    Image.new("RGBA", size, (0, 0, 255, 255)).save(buf, "PNG")
    return buf.getvalue()


@pytest.mark.asyncio
async def test_resolver_draws_emoji_from_font_without_cdn(tmp_path: Path) -> None:
    async def avatars(uid: int) -> bytes:
        raise ConnectionError

    r = ResourceResolver(
        data_root=tmp_path,
        avatar_source=avatars,
        emoji_cdn=None,
        emoji_font=_font_file(tmp_path),
        limits=FetchLimits(timeout=0.2),
    )
    try:
        bundle = await r.resolve(emojis=["©"])
    finally:
        await r.close()
    assert set(bundle.emojis) == {"©"}
    assert max(bundle.emojis["©"].size) <= 160
    # 没有配置 CDN, 字体里没有的字形不算资源缺失
    assert bundle.missing == []


@pytest.mark.asyncio
async def test_resolver_asks_cdn_only_for_glyphs_the_font_lacks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """字体里没有的字形 (画出来是 .notdef) 要退到 CDN, 不能贴个黑框了事"""
    fetched: list[str] = []

    async def fake_download(url: str) -> bytes:
        fetched.append(url)
        return _png_bytes()

    async def avatars(uid: int) -> bytes:
        raise ConnectionError

    r = ResourceResolver(
        data_root=tmp_path,
        avatar_source=avatars,
        emoji_cdn="https://emoji.example",
        emoji_font=_font_file(tmp_path),
        limits=FetchLimits(timeout=0.2),
    )
    monkeypatch.setattr(r, "_download", fake_download)
    try:
        bundle = await r.resolve(emojis=["©", "🫠"])
    finally:
        await r.close()
    # © 由字体画, 🫠 字体没有, 因此只有它去下载
    assert set(bundle.emojis) == {"©", "🫠"}
    assert len(fetched) == 1
    assert "🫠" in unquote(fetched[0])
    assert bundle.missing == []


@pytest.mark.asyncio
async def test_resolver_does_not_touch_cdn_when_the_font_covers_everything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(url: str) -> bytes:
        raise AssertionError("字体里有这个字形, 不该去下载")

    async def avatars(uid: int) -> bytes:
        raise ConnectionError

    r = ResourceResolver(
        data_root=tmp_path,
        avatar_source=avatars,
        emoji_cdn="https://emoji.example",
        emoji_font=_font_file(tmp_path),
        limits=FetchLimits(timeout=0.2),
    )
    monkeypatch.setattr(r, "_download", boom)
    try:
        bundle = await r.resolve(emojis=["©"])
    finally:
        await r.close()
    assert set(bundle.emojis) == {"©"}


@pytest.mark.asyncio
async def test_broken_emoji_font_degrades_to_the_cdn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """emoji_font 配错时不该让整个插件不可用, 只是没有字体这一级来源"""

    async def fake_download(url: str) -> bytes:
        return _png_bytes()

    async def avatars(uid: int) -> bytes:
        raise ConnectionError

    r = ResourceResolver(
        data_root=tmp_path,
        avatar_source=avatars,
        emoji_cdn="https://emoji.example",
        emoji_font=tmp_path / "no-such-font.ttf",
        limits=FetchLimits(timeout=0.2),
    )
    monkeypatch.setattr(r, "_download", fake_download)
    try:
        bundle = await r.resolve(emojis=["©"])
    finally:
        await r.close()
    assert set(bundle.emojis) == {"©"}
    assert bundle.missing == []
