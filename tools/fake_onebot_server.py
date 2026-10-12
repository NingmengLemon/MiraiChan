# /// script
# requires-python = ">=3.12"
# dependencies = ["websockets>=14"]
# ///
"""最小的 OneBot v11 正向 ws 服务端, 用来在本地端到端冒烟测试 bot。

从 JSON 场景文件读取: 预置消息 (供 get_msg 返回) 与要依次推送的事件; 记录 bot 发来的
全部 action 到输出文件 (JSON Lines), 方便事后断言。不实现真实 QQ 行为, 只覆盖
send_*_msg 与 get_msg, 其余 action 一律回 ok + 空数据。

用法:
    python tools/fake_onebot_server.py --scenario s.json --record out.jsonl \
        --host 127.0.0.1 --port 18765 [--token TOKEN] [--linger 20]

场景文件:
    {"self_id": 10000,
     "messages": {"<message_id>": {get_msg 的 data}},
     "events": [{OneBot 事件}, ...],
     "event_interval": 1.0}

所有事件推送完、并且最后一个 action 之后 linger 秒内没有新 action 时退出 (退出码 0)。
"""

import argparse
import asyncio
import itertools
import json
import sys
import time
from pathlib import Path

from websockets.asyncio.server import ServerConnection, serve


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", required=True, type=Path)
    ap.add_argument("--record", required=True, type=Path)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=18765)
    ap.add_argument("--token", default=None)
    ap.add_argument("--linger", type=float, default=20.0)
    ap.add_argument("--timeout", type=float, default=180.0)
    args = ap.parse_args()
    return asyncio.run(run(args))


async def run(args: argparse.Namespace) -> int:
    scenario = json.loads(args.scenario.read_text(encoding="utf-8"))
    self_id = int(scenario["self_id"])
    stored: dict[str, dict] = scenario.get("messages", {})
    events: list[dict] = scenario.get("events", [])
    interval = float(scenario.get("event_interval", 1.0))
    sent_ids = itertools.count(900000)
    record = args.record.open("w", encoding="utf-8")
    last_action = time.monotonic()
    done = asyncio.Event()

    def reply(action: dict) -> dict:
        name = action.get("action")
        params = action.get("params") or {}
        data: object = None
        status, retcode = "ok", 0
        if name in ("send_msg", "send_group_msg", "send_private_msg"):
            data = {"message_id": next(sent_ids)}
        elif name == "get_msg":
            data = stored.get(str(params.get("message_id")))
            if data is None:
                status, retcode = "failed", 100
        elif name == "get_login_info":
            data = {"user_id": self_id, "nickname": "bot"}
        return {"status": status, "retcode": retcode, "data": data, "echo": action.get("echo")}

    async def handler(conn: ServerConnection) -> None:
        nonlocal last_action
        if args.token:
            auth = conn.request.headers.get("Authorization", "") if conn.request else ""
            if auth != f"Bearer {args.token}":
                await conn.close(1008, "bad token")
                return
        await conn.send(
            json.dumps(
                {
                    "time": int(time.time()),
                    "self_id": self_id,
                    "post_type": "meta_event",
                    "meta_event_type": "lifecycle",
                    "sub_type": "connect",
                }
            )
        )

        async def pump() -> None:
            await asyncio.sleep(interval * 3)
            for ev in events:
                ev = {"time": int(time.time()), "self_id": self_id, **ev}
                await conn.send(json.dumps(ev, ensure_ascii=False))
                await asyncio.sleep(interval)

        pumper = asyncio.create_task(pump())
        try:
            async for raw in conn:
                action = json.loads(raw)
                last_action = time.monotonic()
                record.write(json.dumps(action, ensure_ascii=False) + "\n")
                record.flush()
                await conn.send(json.dumps(reply(action), ensure_ascii=False))
        finally:
            pumper.cancel()

    async def watchdog() -> None:
        start = time.monotonic()
        # 至少等事件推完再开始计 linger
        floor = start + interval * (len(events) + 3)
        while True:
            await asyncio.sleep(0.5)
            now = time.monotonic()
            if now > start + args.timeout:
                print("timeout", file=sys.stderr)
                break
            if now > floor and now - max(last_action, floor) > args.linger:
                break
        done.set()

    async with serve(handler, args.host, args.port):
        print(f"fake onebot listening on ws://{args.host}:{args.port}", flush=True)
        await asyncio.gather(watchdog(), done.wait())
    record.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
