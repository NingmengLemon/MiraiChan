from lemony_mface import MFaceBlocklist, mface_image_url
from mbplugin_quote.model import (
    ImageElement,
    ImageRef,
    SourceMessage,
    SourceSegment,
    TextElement,
)
from mbplugin_quote.normalize import (
    display_name_of,
    name_resolver_from,
    normalize_message,
    normalize_segments,
    unresolved_at_targets,
)

EMOJI_ID = "ab" + "0" * 30
MFACE_IMAGE = SourceSegment(
    "image",
    {
        "url": mface_image_url(EMOJI_ID),
        "summary": "[喵喵消息]",
        "emoji_id": EMOJI_ID,
        "emoji_package_id": 248907,
    },
)
ECHO = SourceSegment("text", {"text": "[喵喵消息]"})


def seg(t: str, **data) -> SourceSegment:
    return SourceSegment(t, data)


def norm(*segments: SourceSegment, blocked=(), resolve=None):
    return normalize_segments(
        segments, blocklist=MFaceBlocklist(blocked), resolve_name=resolve
    )


def test_adjacent_text_is_joined_without_spaces() -> None:
    assert norm(seg("text", text="你"), seg("text", text="好")) == (
        TextElement("你好"),
    )


def test_at_uses_name_then_resolver_then_qq() -> None:
    names = {2: "二号"}.get
    assert norm(
        seg("at", qq="1", name="@一号"),
        seg("at", qq="2"),
        seg("at", qq="3"),
        seg("at", qq="all"),
        resolve=names,
    ) == (TextElement("@一号 @二号 @3 @全体成员"),)


def test_mface_drops_summary_echo() -> None:
    assert norm(MFACE_IMAGE, ECHO) == (
        ImageElement(ImageRef(url=mface_image_url(EMOJI_ID), is_mface=True)),
    )


def test_echo_only_dropped_when_directly_following() -> None:
    out = norm(MFACE_IMAGE, seg("text", text="hi"), ECHO)
    assert out[1:] == (TextElement("hi[喵喵消息]"),)


def test_blocked_mface_becomes_its_summary_text() -> None:
    assert norm(MFACE_IMAGE, ECHO, blocked=[248907]) == (TextElement("[喵喵消息]"),)


def test_image_keeps_local_paths() -> None:
    s = SourceSegment("image", {"url": "https://x.invalid/a"}, ("record/a.png",))
    (el,) = norm(s)
    assert isinstance(el, ImageElement)
    assert el.ref.key == "record/a.png"
    assert not el.ref.is_mface


def test_labels_and_dropped_segments() -> None:
    assert norm(
        seg("reply", id="1"),
        seg("face", id="1"),
        seg("record", file="x"),
        seg("whatever"),
    ) == (TextElement("[表情][语音][whatever]"),)


def test_whitespace_trimmed_and_empty_removed() -> None:
    assert norm(seg("text", text="  ")) == ()
    assert norm(seg("text", text=" a "), seg("image", url="u")) == (
        TextElement("a"),
        ImageElement(ImageRef(url="u")),
    )


def test_display_name_prefers_card() -> None:
    assert display_name_of("名片", "昵称", 1) == "名片"
    assert display_name_of(" ", "昵称", 1) == "昵称"
    assert display_name_of(None, None, 1) == "1"


def test_normalize_message_and_resolver() -> None:
    a = SourceMessage("m1", 1, None, "甲", (seg("at", qq="2"),))
    b = SourceMessage("m2", 2, "乙名片", "乙", (seg("text", text="嗯"),))
    resolve = name_resolver_from([a, b])
    qm = normalize_message(a, blocklist=MFaceBlocklist(), resolve_name=resolve)
    assert (qm.display_name, qm.text) == ("甲", "@乙名片")


def test_unresolved_at_targets_and_extra_names() -> None:
    # 实测线上 recorder 里的 at 段只有 qq 字段
    a = SourceMessage(
        "m1",
        1,
        None,
        "甲",
        (
            seg("at", qq="2"),  # 乙在这批消息里说过话, 不用查
            seg("at", qq="3"),  # 需要查
            seg("at", qq="4", name="@四号"),  # 自带名字, 不用查
            seg("at", qq="all"),
        ),
    )
    b = SourceMessage("m2", 2, None, "乙", (seg("text", text="嗯"),))
    assert unresolved_at_targets([a, b]) == {3}
    resolve = name_resolver_from([a, b], {3: "丙名片"})
    qm = normalize_message(a, blocklist=MFaceBlocklist(), resolve_name=resolve)
    assert qm.text == "@乙 @丙名片 @四号 @全体成员"
