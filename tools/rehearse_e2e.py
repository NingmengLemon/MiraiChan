"""在隔离目录里用假 OneBot 服务端跑一遍真实 bot, 检查上线插件组合的关键路径。

不读写仓库的 data/ 与 configs/: 项目根经 MIRAICHAN_PROJECT_ROOT 指到临时目录,
字体从仓库 data/fonts 复制过去。场景里的 QQ 号、群号与消息都是构造值。

用法: uv run python tools/rehearse_e2e.py [--keep] [--port 18765]
退出码: 0 全部检查通过, 1 有检查失败, 2 运行失败 (bot 或假服务端异常退出)。
"""

import argparse
import contextlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGINS = [
    "mbplugin_checker_manager",
    "mbplugin_recorder",
    "mbplugin_deeeer",
    "mbplugin_moelottery",
    "mbplugin_rebootable",
    "mbplugin_quote",
    "mbplugin_toolbox",
]
TOKEN = "rehearsal-token"
SELF, OWNER, ALICE, BOB, GROUP = 10000, 39999, 30001, 30002, 20000
EMOJI_ID = "ab" + "0" * 30


def group_msg(mid: int, uid: int, nick: str, segments: list, card: str = "") -> dict:
    return {
        "post_type": "message",
        "message_type": "group",
        "sub_type": "normal",
        "message_id": mid,
        "group_id": GROUP,
        "user_id": uid,
        "message": segments,
        "raw_message": "",
        "font": 0,
        "sender": {"user_id": uid, "nickname": nick, "card": card, "role": "member"},
    }


def text(s: str) -> list:
    return [{"type": "text", "data": {"text": s}}]


def reply(mid: int | str, s: str) -> list:
    return [{"type": "reply", "data": {"id": str(mid)}}, *text(s)]


def scenario() -> dict:
    mface = [
        {
            "type": "image",
            "data": {
                "file": f"ab-{EMOJI_ID}.gif",
                "url": f"https://gxh.vip.qq.com/club/item/parcel/item/ab/{EMOJI_ID}/raw300.gif",
                "summary": "[喵喵消息]",
                "emoji_id": EMOJI_ID,
                "emoji_package_id": 248907,
                "key": "k" * 16,
                "sub_type": 0,
            },
        },
        *text("[喵喵消息]"),
    ]
    events = [
        group_msg(3001, ALICE, "甲", text("今天天气不错"), card="甲名片"),
        group_msg(3002, BOB, "乙", mface),
        group_msg(3003, ALICE, "甲", text("鹿"), card="甲名片"),
        group_msg(3004, BOB, "乙", text(".今日人设")),
        group_msg(3005, OWNER, "主人", reply(3001, ".mq 0..1")),
        group_msg(3006, OWNER, "主人", reply(3001, ".q")),
        group_msg(3007, OWNER, "主人", text(".checker status")),
        group_msg(3008, OWNER, "主人", text(".ping")),
        group_msg(3009, BOB, "乙", text(".ping")),
        group_msg(3010, OWNER, "主人", reply(3001, ".getmsg")),
    ]
    stored = {
        "3001": {
            "time": 1,
            "message_type": "group",
            "message_id": 3001,
            "real_id": 3001,
            "sender": {"user_id": ALICE, "nickname": "甲", "card": "甲名片"},
            "message": text("今天天气不错"),
        }
    }
    # .qdel 需要 bot 发出的消息 id; 假服务端按 900000 起递增分配, 前两张图是 .mq 与 .q
    return {
        "self_id": SELF,
        "event_interval": 1.5,
        "events": events,
        "messages": stored,
    }


def qdel_scenario(sent_id: int) -> dict:
    return {
        "self_id": SELF,
        "event_interval": 1.5,
        "events": [
            group_msg(3101, BOB, "乙", reply(sent_id, ".qdel")),
            group_msg(3102, OWNER, "主人", reply(sent_id, ".qdel")),
        ],
        "messages": {},
    }


def build_root(root: Path) -> None:
    (root / "data" / "fonts").mkdir(parents=True)
    (root / "data" / "record").mkdir(parents=True)
    (root / "configs" / "lemony_checkers").mkdir(parents=True)
    for font in ("NotoSansSC-Medium.ttf", "sarasa-mono-sc-semibold.ttf"):
        src = REPO / "data" / "fonts" / font
        if not src.is_file():
            raise SystemExit(f"missing font {src}")
        shutil.copy2(src, root / "data" / "fonts" / font)
    (root / "miracle_entrance.py").write_text(
        "from miraichan.main import miraichan_cli_app\n\n"
        "if __name__ == '__main__':\n    miraichan_cli_app()\n",
        encoding="utf-8",
    )
    config = {
        "debug": False,
        "websocket": {"type": "forward", "url": ""},
        "load_depth": 3,
        "plugins": [str(REPO / "packages" / "plugins" / p) for p in PLUGINS],
    }
    (root / "config.json").write_text(json.dumps(config), encoding="utf-8")
    # 凭据走独立文件 (和线上一样), 权限照 0600 建
    credentials = root / "credentials.json"
    credentials.write_text(
        json.dumps({"websocket.access_token": TOKEN}), encoding="utf-8"
    )
    with contextlib.suppress(OSError):
        credentials.chmod(0o600)
    owner = {
        "mode": "blacklist",
        "owner": [
            {"protocol": "OneBot-v11@Meloland", "user_id": OWNER, "group_id": None}
        ],
        "admins": [],
        "rules": [],
    }
    (root / "configs" / "lemony_checkers" / "global.json").write_text(
        json.dumps(owner), encoding="utf-8"
    )
    # 旧版 deeeer 库的形态 (表名 deerrecord), 两行构造数据
    conn = sqlite3.connect(root / "data" / "record" / "deers.db")
    conn.executescript(
        """
        CREATE TABLE deerrecord (
            id CHAR(32) NOT NULL, timestamp FLOAT NOT NULL, user_id INTEGER NOT NULL,
            group_id INTEGER NOT NULL, combo INTEGER NOT NULL, PRIMARY KEY (id));
        """
    )
    now = time.time()
    conn.executemany(
        "insert into deerrecord values (?, ?, ?, ?, ?)",
        [
            ("0" * 31 + "1", now - 86400, ALICE, GROUP, 2),
            ("0" * 31 + "2", now - 3600, BOB, GROUP, 1),
        ],
    )
    conn.commit()
    conn.close()


def run_round(root: Path, scen: dict, port: int, tag: str) -> list[dict]:
    scen_path = root / f"scenario_{tag}.json"
    record = root / f"actions_{tag}.jsonl"
    scen_path.write_text(json.dumps(scen, ensure_ascii=False), encoding="utf-8")
    cfg = json.loads((root / "config.json").read_text(encoding="utf-8"))
    cfg["websocket"]["url"] = f"ws://127.0.0.1:{port}"
    (root / "config.json").write_text(json.dumps(cfg), encoding="utf-8")

    env = {
        **os.environ,
        "MIRAICHAN_PROJECT_ROOT": str(root),
        "PYTHONIOENCODING": "utf-8",
    }
    with (
        open(root / f"server_{tag}.log", "wb") as slog,
        open(root / f"bot_{tag}.log", "wb") as blog,
    ):
        server = subprocess.Popen(
            [
                sys.executable,
                str(REPO / "tools" / "fake_onebot_server.py"),
                "--scenario",
                str(scen_path),
                "--record",
                str(record),
                "--port",
                str(port),
                "--token",
                TOKEN,
                "--linger",
                "12",
                "--timeout",
                "150",
            ],
            stdout=slog,
            stderr=subprocess.STDOUT,
        )
        time.sleep(1.5)
        bot = subprocess.Popen(
            [sys.executable, str(root / "miracle_entrance.py")],
            cwd=root,
            env=env,
            stdout=blog,
            stderr=subprocess.STDOUT,
        )
        try:
            code = server.wait(timeout=180)
        finally:
            bot.terminate()
            try:
                bot.wait(timeout=15)
            except subprocess.TimeoutExpired:
                bot.kill()
    if code != 0:
        raise RuntimeError(f"fake server exited with {code}, see server_{tag}.log")
    return [
        json.loads(line) for line in record.read_text(encoding="utf-8").splitlines()
    ]


def query(db: Path, sql: str) -> list[tuple]:
    """只读查询; bot 被结束后 Windows 上文件句柄可能还要片刻才释放, 短暂重试"""
    last: Exception | None = None
    for _ in range(20):
        try:
            conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
            try:
                return conn.execute(sql).fetchall()
            finally:
                conn.close()
        except sqlite3.OperationalError as e:
            last = e
            time.sleep(0.5)
    raise RuntimeError(f"cannot read {db}: {last!r}")


def replies(actions: list[dict]) -> dict[str, list[dict]]:
    """被回复的消息 id -> bot 发出的段"""
    out: dict[str, list[dict]] = {}
    for a in actions:
        msg = (a.get("params") or {}).get("message")
        if a.get("action") != "send_msg" or not isinstance(msg, list):
            continue
        rid = next((s["data"]["id"] for s in msg if s["type"] == "reply"), None)
        if rid is not None:
            out.setdefault(str(rid), []).extend(s for s in msg if s["type"] != "reply")
    return out


def kinds(segs: list[dict]) -> list[str]:
    return [s["type"] for s in segs]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true", help="保留隔离目录便于检查")
    ap.add_argument("--port", type=int, default=18765)
    args = ap.parse_args()

    root = Path(tempfile.mkdtemp(prefix="miraichan-rehearsal-"))
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, ok, detail))

    try:
        build_root(root)
        actions = run_round(root, scenario(), args.port, "main")
        by_reply = replies(actions)
        bot_log = (root / "bot_main.log").read_text(encoding="utf-8", errors="replace")

        for plugin in PLUGINS:
            check(f"loaded {plugin}", f"成功加载插件：{plugin}" in bot_log)
        check("no ERROR in bot log", " | ERROR " not in bot_log)
        check(
            "deer reply has image",
            "image" in kinds(by_reply.get("3003", [])),
            str(kinds(by_reply.get("3003", []))),
        )
        check("moelottery replied text", "text" in kinds(by_reply.get("3004", [])))
        check(
            ".mq produced image",
            kinds(by_reply.get("3005", [])) == ["image"],
            str(kinds(by_reply.get("3005", []))),
        )
        check(
            ".q produced image",
            kinds(by_reply.get("3006", [])) == ["image"],
            str(kinds(by_reply.get("3006", []))),
        )
        check("checker status replied", bool(by_reply.get("3007")))
        ping = by_reply.get("3008", [])
        check(
            ".ping by owner replied pong",
            [s.get("data", {}).get("text") for s in ping] == ["pong"],
            str(ping),
        )
        check(".ping by non-admin is silent", "3009" not in by_reply)
        # .getmsg 以合并转发发出 JSON; 转发 action 不带 reply 段, 直接按内容找
        forwards = [
            a
            for a in actions
            if "forward" in str(a.get("action"))
            and "今天天气不错" in json.dumps(a.get("params"), ensure_ascii=False)
        ]
        check(
            ".getmsg sent a forward with the message json",
            len(forwards) == 1 and "3010" not in by_reply,
            f"forwards={len(forwards)} reply={kinds(by_reply.get('3010', []))}",
        )

        deers_db = root / "data" / "record" / "deers.db"
        tables = {
            r[0]
            for r in query(
                deers_db, "select name from sqlite_master where type='table'"
            )
        }
        rows = (
            query(deers_db, "select count(*) from deer_record")[0][0]
            if "deer_record" in tables
            else -1
        )
        # 旧库 2 行 + 本次 "鹿" 1 行
        check(
            "deers migrated",
            tables == {"deer_record"} and rows == 3,
            f"tables={tables} rows={rows}",
        )

        mface_keys = [
            sorted(json.loads(d))
            for (d,) in query(
                root / "data" / "record" / "recorder.db",
                "select data from recorder_message_segment where type='image'",
            )
        ]
        check(
            "recorder kept mface fields",
            any("emoji_id" in k for k in mface_keys),
            str(mface_keys),
        )

        quote_db = root / "data" / "quote" / "quote.db"
        arts = query(
            quote_db,
            "select style, sent_message_id, path from quote_artifact order by created_at",
        )
        check(
            "two archives with sent ids",
            len(arts) == 2 and all(a[1] for a in arts),
            str(arts),
        )

        if arts:
            sent_id = int(arts[0][1])
            path = root / "data" / "quote" / "artifacts" / arts[0][2]
            check("archive file exists", path.is_file())
            actions2 = run_round(root, qdel_scenario(sent_id), args.port, "qdel")
            by_reply2 = replies(actions2)
            check(".qdel by non-admin is silent", "3101" not in by_reply2)
            check(".qdel by owner replied", bool(by_reply2.get("3102")))
            left = query(quote_db, "select count(*) from quote_artifact")[0][0]
            check(
                ".qdel removed index and file",
                left == 1 and not path.exists(),
                f"left={left}",
            )
    except Exception as e:  # noqa: BLE001 - 演练脚本把任何失败都报成退出码 2
        print(f"rehearsal failed to run: {e!r}", file=sys.stderr)
        print(f"root kept at {root}", file=sys.stderr)
        return 2

    width = max(len(n) for n, _, _ in checks)
    for name, ok, detail in checks:
        print(
            f"[{'ok' if ok else 'FAIL'}] {name.ljust(width)} {detail if not ok else ''}"
        )
    failed = [c for c in checks if not c[1]]
    print(f"{len(checks) - len(failed)}/{len(checks)} checks passed")
    if args.keep or failed:
        print(f"root kept at {root}")
    else:
        _remove_tree(root)
    return 1 if failed else 0


def _remove_tree(root: Path) -> None:
    # bot 进程退出后 Windows 上字体等文件句柄可能还要片刻才释放
    for _ in range(20):
        shutil.rmtree(root, ignore_errors=True)
        if not root.exists():
            return
        time.sleep(0.5)
    print(f"could not fully remove {root}, delete it manually", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
