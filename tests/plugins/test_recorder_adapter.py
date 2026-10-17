"""recorder 的 OneBot v11 适配: 段数据要原样保存实现端的扩展字段。"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGINS_ROOT = REPO_ROOT / "packages" / "plugins"
if str(PLUGINS_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGINS_ROOT))

from mbplugin_recorder.adapters.ob11 import _segment_raw_data
from melobot.protocols.onebot.v11.adapter.segment import Segment

# SnowLuma 上报商城表情的 image 段形态, 标识符为构造值
SNOWLUMA_MFACE = {
    "file": "ab-" + "ab" * 16 + ".gif",
    "url": "https://gxh.vip.qq.com/club/item/parcel/item/ab/"
    + "ab" * 16
    + "/raw300.gif",
    "type": None,
    "summary": "[喵喵消息]",
    "sub_type": 0,
    "emoji_id": "ab" * 16,
    "emoji_package_id": 248907,
    "key": "k" * 16,
}


def test_extension_fields_survive() -> None:
    seg = Segment.resolve("image", SNOWLUMA_MFACE)
    # 对照: melobot 的模型会丢掉扩展字段, 这正是不能用 to_dict() 的原因
    assert "emoji_id" not in seg.to_dict()["data"]

    data = _segment_raw_data(seg)
    assert data["emoji_id"] == "ab" * 16
    assert data["summary"] == "[喵喵消息]"
    assert data["emoji_package_id"] == 248907
    assert "type" not in data  # None 值去掉


def test_plain_segment_unchanged() -> None:
    seg = Segment.resolve("text", {"text": "hi"})
    assert _segment_raw_data(seg) == {"text": "hi"}
