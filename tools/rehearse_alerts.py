"""在隔离目录里跑一遍真实 bot + 预警插件, 用 mock Wolfx 服务端触发推送并检查结果.

流程: 启动 mock Wolfx 与假 OneBot 服务端 -> 启动 bot -> 假服务端推送订阅指令 ->
等指令全部得到回复后, 经 mock 的 /_mock/push 推几条报文 -> 检查 bot 发出的消息.

不读写仓库的 data/ 与 configs/; 场景里的 QQ 号、群号都是构造值。
用法: uv run python tools/rehearse_alerts.py [--keep] [--port 18766] [--wolfx-port 18767]
退出码: 0 全部检查通过, 1 有检查失败, 2 运行失败。
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
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGINS = ["mbplugin_checker_manager", "mbplugin_emergency_alerts", "mbplugin_helper"]
TOKEN = "rehearsal-token"
SELF, OWNER, MEMBER, GADMIN, GROUP = 10000, 39999, 30001, 30002, 20000
CST = timezone(timedelta(hours=8))


def text(s: str) -> list:
    return [{"type": "text", "data": {"text": s}}]


def group_msg(mid: int, uid: int, role: str, s: str) -> dict:
    return {
        "post_type": "message",
        "message_type": "group",
        "sub_type": "normal",
        "message_id": mid,
        "group_id": GROUP,
        "user_id": uid,
        "message": text(s),
        "raw_message": s,
        "font": 0,
        "sender": {"user_id": uid, "nickname": f"u{uid}", "card": "", "role": role},
    }


def private_msg(mid: int, uid: int, s: str) -> dict:
    return {
        "post_type": "message",
        "message_type": "private",
        "sub_type": "friend",
        "message_id": mid,
        "user_id": uid,
        "message": text(s),
        "raw_message": s,
        "font": 0,
        "sender": {"user_id": uid, "nickname": f"u{uid}"},
    }


COMMANDS = [
    group_msg(4001, MEMBER, "member", ".预警 订阅"),
    group_msg(4002, GADMIN, "admin", ".预警 设置 地区 四川"),
    private_msg(4003, OWNER, ".预警 订阅"),
    private_msg(4004, OWNER, ".预警 设置 种类 速报"),
    group_msg(4005, GADMIN, "admin", ".预警 状态"),
    group_msg(4006, MEMBER, "member", ".help"),
    private_msg(4007, OWNER, ".help 预警"),
]
FORWARD_ACTIONS = ("send_group_forward_msg", "send_private_forward_msg")


def build_root(root: Path, wolfx_port: int) -> None:
    (root / "data" / "fonts").mkdir(parents=True)
    font = REPO / "data" / "fonts" / "sarasa-mono-sc-semibold.ttf"
    if font.is_file():
        shutil.copy2(font, root / "data" / "fonts" / font.name)
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
    checkers = root / "configs" / "lemony_checkers"
    checkers.mkdir(parents=True)
    owner = {
        "mode": "blacklist",
        "owner": [
            {"protocol": "OneBot-v11@Meloland", "user_id": OWNER, "group_id": None}
        ],
        "admins": [],
        "rules": [],
    }
    (checkers / "global.json").write_text(json.dumps(owner), encoding="utf-8")
    alerts = root / "configs" / "emergency_alerts"
    alerts.mkdir(parents=True)
    (alerts / "default.json").write_text(
        json.dumps(
            {
                "ws_base_url": f"ws://127.0.0.1:{wolfx_port}",
                "endpoints": ["all_eew", "cenc_eqlist", "jma_eqlist"],
                "send_interval": 0,
            }
        ),
        encoding="utf-8",
    )


def push(wolfx_port: int, payload: dict) -> int:
    req = urllib.request.Request(
        f"http://127.0.0.1:{wolfx_port}/_mock/push",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return int(json.loads(resp.read())["sent_to"])


def query(db: Path, sql: str) -> list[tuple]:
    """只读查询; bot 结束后 Windows 上文件句柄可能还要片刻才释放, 短暂重试"""
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


def wait_http(port: int, timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2):
                return
        except OSError:
            time.sleep(0.3)
    raise RuntimeError(f"mock wolfx on {port} did not come up")


def read_actions(record: Path) -> list[dict]:
    if not record.exists():
        return []
    lines = record.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def is_reply(action: dict) -> bool:
    msg = (action.get("params") or {}).get("message")
    return isinstance(msg, list) and any(s.get("type") == "reply" for s in msg)


def is_response(action: dict) -> bool:
    """对指令的响应: 回复消息, 或 .help 发出的合并转发"""
    return is_reply(action) or action.get("action") in FORWARD_ACTIONS


def node_texts(action: dict) -> list[str]:
    nodes = (action.get("params") or {}).get("messages") or []
    return [
        "".join(
            s["data"].get("text", "")
            for s in n["data"].get("content", [])
            if s.get("type") == "text"
        )
        for n in nodes
    ]


def plain(action: dict) -> str:
    msg = (action.get("params") or {}).get("message") or []
    return "".join(s["data"].get("text", "") for s in msg if s.get("type") == "text")


def low_eew() -> dict:
    now = datetime.now(CST)
    fmt = "%Y-%m-%d %H:%M:%S"
    return {
        "type": "sc_eew",
        "ID": 1,
        "EventID": "REHEARSAL-LOW",
        "ReportTime": now.strftime(fmt),
        "ReportNum": 1,
        "OriginTime": (now - timedelta(seconds=10)).strftime(fmt),
        "HypoCenter": "四川雅安市宝兴县",
        "Latitude": 30.2,
        "Longitude": 102.8,
        "Magnitude": 3.0,
        "Depth": 10,
        "MaxIntensity": 3.0,
    }


def run(root: Path, port: int, wolfx_port: int) -> tuple[list[dict], dict[str, int]]:
    scen = root / "scenario.json"
    record = root / "actions.jsonl"
    scen.write_text(
        json.dumps(
            {"self_id": SELF, "event_interval": 1.0, "events": COMMANDS},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    cfg = json.loads((root / "config.json").read_text(encoding="utf-8"))
    cfg["websocket"]["url"] = f"ws://127.0.0.1:{port}"
    (root / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    env = {
        **os.environ,
        "MIRAICHAN_PROJECT_ROOT": str(root),
        "PYTHONIOENCODING": "utf-8",
    }
    sent_to: dict[str, int] = {}
    procs: list[subprocess.Popen] = []
    with (
        open(root / "wolfx.log", "wb") as wlog,
        open(root / "server.log", "wb") as slog,
        open(root / "bot.log", "wb") as blog,
    ):
        try:
            procs.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        str(REPO / "tools" / "mock_wolfx_server.py"),
                        "--port",
                        str(wolfx_port),
                        "--heartbeat-interval",
                        "5",
                    ],
                    stdout=wlog,
                    stderr=subprocess.STDOUT,
                )
            )
            wait_http(wolfx_port)
            server = subprocess.Popen(
                [
                    sys.executable,
                    str(REPO / "tools" / "fake_onebot_server.py"),
                    "--scenario",
                    str(scen),
                    "--record",
                    str(record),
                    "--port",
                    str(port),
                    "--token",
                    TOKEN,
                    "--linger",
                    "10",
                    "--timeout",
                    "150",
                ],
                stdout=slog,
                stderr=subprocess.STDOUT,
            )
            procs.append(server)
            time.sleep(1.5)
            procs.append(
                subprocess.Popen(
                    [sys.executable, str(root / "miracle_entrance.py")],
                    cwd=root,
                    env=env,
                    stdout=blog,
                    stderr=subprocess.STDOUT,
                )
            )
            # 每条指令恰好一条回复; 全部回复后订阅已落定, 再触发推送
            deadline = time.monotonic() + 90
            while sum(map(is_response, read_actions(record))) < len(COMMANDS):
                if time.monotonic() > deadline or server.poll() is not None:
                    raise RuntimeError("bot did not answer every command in time")
                time.sleep(0.3)
            for name, payload in [
                ("sc_eew", {"type": "sc_eew"}),
                ("sc_eew_again", {"type": "sc_eew"}),
                ("cenc_eqlist", {"type": "cenc_eqlist"}),
                ("low", low_eew()),
            ]:
                sent_to[name] = push(wolfx_port, payload)
                time.sleep(1.0)
            code = server.wait(timeout=120)
            if code != 0:
                raise RuntimeError(f"fake onebot exited with {code}, see server.log")
        finally:
            for p in reversed(procs):
                if p.poll() is None:
                    p.terminate()
                    try:
                        p.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        p.kill()
    return read_actions(record), sent_to


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true", help="保留隔离目录便于检查")
    ap.add_argument("--port", type=int, default=18766)
    ap.add_argument("--wolfx-port", type=int, default=18767)
    args = ap.parse_args()

    root = Path(tempfile.mkdtemp(prefix="miraichan-alerts-"))
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, ok, detail))

    try:
        build_root(root, args.wolfx_port)
        actions, sent_to = run(root, args.port, args.wolfx_port)
        bot_log = (root / "bot.log").read_text(encoding="utf-8", errors="replace")
        sends = [a for a in actions if a.get("action") == "send_msg"]
        replies = [a for a in sends if is_reply(a)]
        pushes = [a for a in sends if not is_reply(a)]
        group_pushes = [a for a in pushes if a["params"].get("group_id") == GROUP]
        private_pushes = [a for a in pushes if a["params"].get("user_id") == OWNER]

        forwards = [a for a in actions if a.get("action") in FORWARD_ACTIONS]
        group_fwd = [a for a in forwards if a["params"].get("group_id") == GROUP]
        private_fwd = [a for a in forwards if a["params"].get("user_id") == OWNER]

        for plugin in PLUGINS:
            check(f"loaded {plugin}", f"成功加载插件：{plugin}" in bot_log)
        overview = node_texts(group_fwd[0]) if group_fwd else []
        check(
            ".help sent a merged forward with an index and one node per plugin",
            len(group_fwd) == 1
            and len(overview) == 1 + len(PLUGINS)
            and all(t in overview[0] for t in ("权限管理", "地震预警", "帮助")),
            str([t[:30] for t in overview]),
        )
        detail = node_texts(private_fwd[0]) if private_fwd else []
        check(
            ".help 预警 splits one plugin per command",
            len(private_fwd) == 1
            and detail[0].startswith("【地震预警】")
            and any(t.startswith(".预警 设置") for t in detail),
            str([t[:30] for t in detail]),
        )
        check("no ERROR in bot log", " | ERROR " not in bot_log)
        check(
            "plugin connected to all endpoints",
            all(v >= 1 for v in sent_to.values()),
            str(sent_to),
        )
        check(
            "member cannot subscribe the group",
            "只有群管理员" in plain(replies[0]) if replies else False,
            plain(replies[0]) if replies else "no reply",
        )
        check(
            "status shows the region",
            any("四川" in plain(r) and "数据源连接: 3/3" in plain(r) for r in replies),
            " | ".join(plain(r)[:60] for r in replies),
        )
        check(
            "group got the Sichuan EEW exactly once",
            len(group_pushes) == 1 and "四川省阿坝州汶川县" in plain(group_pushes[0]),
            str([plain(a)[:40] for a in group_pushes]),
        )
        check(
            "private got only the report",
            len(private_pushes) == 1 and "地震速报" in plain(private_pushes[0]),
            str([plain(a)[:40] for a in private_pushes]),
        )
        check(
            "no push for the low-magnitude EEW",
            not any("宝兴" in plain(a) for a in pushes),
        )
        db = root / "data" / "emergency_alerts" / "alerts.db"
        reports = query(db, "select source, event_id, seq from alert_report")
        deliveries = query(
            db,
            "select target_type, target_id, ok from alert_delivery order by sent_at",
        )
        # sc_eew 重复推了一次但只留一份; 低震级那报不推送但也要留档
        check(
            "every distinct report archived once",
            sorted(r[0] for r in reports) == ["cenc_eqlist", "sc_eew", "sc_eew"]
            and len(set(reports)) == len(reports),
            str(reports),
        )
        check(
            "deliveries archived",
            sorted(deliveries) == [("group", GROUP, 1), ("private", OWNER, 1)],
            str(deliveries),
        )
        subs_file = root / "configs" / "emergency_alerts" / "subscriptions.json"
        subs = json.loads(subs_file.read_text(encoding="utf-8"))["subscriptions"]
        check(
            "subscriptions persisted",
            sorted((s["target_type"], s["regions"], s["kinds"]) for s in subs)
            == sorted(
                [("group", ["四川"], ["eew", "report"]), ("private", [], ["report"])]
            ),
            json.dumps(subs, ensure_ascii=False),
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
        for _ in range(20):
            shutil.rmtree(root, ignore_errors=True)
            if not root.exists():
                break
            time.sleep(0.5)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
