"""从 OneBot 消息里取图片的纯函数 (不依赖 bot 实例)。"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from lemony_storage_helper.files import set_data_root
from mbplugin_provenance.images import (
    image_payloads,
    local_candidates,
    mime_of,
    segment_dict,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _payload(*segments: object) -> dict:
    return {"message": list(segments)}


def test_image_payloads_keeps_image_segments_only() -> None:
    payload = _payload(
        {"type": "text", "data": {"text": "hi"}},
        {"type": "image", "data": {"file": "a.png", "url": "https://x/a.png"}},
        {"type": "at", "data": {"qq": "1"}},
        {"type": "image", "data": {"file": "b.png"}},
    )
    assert [p["file"] for p in image_payloads(payload)] == ["a.png", "b.png"]
    assert image_payloads({}) == []


def test_segment_dict_accepts_mapping_objects_and_duck_types() -> None:
    with_raw = SimpleNamespace(raw={"type": "image", "data": {"file": "c.png"}})
    with_to_dict = SimpleNamespace(
        to_dict=lambda: {"type": "text", "data": {"text": "x"}}
    )

    assert segment_dict({"type": "image"}) == {"type": "image"}
    assert segment_dict(with_raw)["type"] == "image"
    assert segment_dict(with_to_dict)["type"] == "text"
    assert segment_dict(object()) == {}


def test_local_candidates_resolves_relative_paths_under_the_data_root(
    tmp_path: Path,
) -> None:
    set_data_root(tmp_path)
    target = tmp_path / "media" / "a.png"
    target.parent.mkdir(parents=True)
    target.write_bytes(PNG)
    assert local_candidates({"file": "media/a.png"}) == [target]
    assert local_candidates({"file": str(target)}) == [target]
    assert local_candidates({"file": f"file://{target}"}) == [target]
    # 不存在的文件、空值、data root 没设置时都返回空列表
    assert local_candidates({"file": "media/missing.png"}) == []
    assert local_candidates({"file": None}) == []
    set_data_root(None)
    assert local_candidates({"file": str(target)}) == []


def test_mime_of_prefers_magic_bytes_and_falls_back_to_the_suffix() -> None:
    assert mime_of(PNG, {}, None) == "image/png"
    assert mime_of(b"not an image", {}, "https://x/a.jpeg?token=1") == "image/jpeg"
    assert mime_of(b"not an image", {"file": "b.webp"}, None) == "image/webp"
    assert mime_of(b"not an image", {}, None) == "application/octet-stream"


def test_unknown_segment_objects_are_ignored() -> None:
    assert image_payloads(_payload(object())) == []


@pytest.mark.parametrize("value", [None, 1, ["x"]])
def test_non_mapping_data_is_ignored(value: object) -> None:
    assert image_payloads(_payload({"type": "image", "data": value})) == []
