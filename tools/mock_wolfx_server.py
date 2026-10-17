# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "aiohttp>=3.10.0",
#   "pillow>=11.0.0",
# ]
# ///

"""Wolfx Open API mock server for local client development.

The real Wolfx service exposes JSON-over-HTTP endpoints under
``https://api.wolfx.jp`` and WebSocket endpoints under
``wss://ws-api.wolfx.jp``. This script provides a deterministic local mock for
client integration tests and manual development.

Usage:
    uv run python tools/mock_wolfx_server.py --host 127.0.0.1 --port 8765

Then point HTTP clients to ``http://127.0.0.1:8765`` and WebSocket clients to
``ws://127.0.0.1:8765`` while keeping the same endpoint paths.

Like the real server, a WebSocket connection only receives heartbeats until
something happens. Trigger a push to every connected client with::

    curl -X POST http://127.0.0.1:8765/_mock/push -d '{"type": "cenc_eew"}'

A body with only ``type`` sends the built-in sample with the times set to now;
a full message body is forwarded as is. ``--push-on-connect`` restores the old
behaviour of pushing every sample right after connecting.

Sample field shapes follow messages captured from the real service in 2026-10:
domestic sources use ``YYYY-MM-DD HH:MM:SS`` times, JMA sources use slashes,
and ``Magnitude`` is sent alongside the deprecated ``Magunitude``.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta, timezone
from io import BytesIO
from typing import Any, Final

from aiohttp import WSMsgType, web
from PIL import Image

JsonObject = dict[str, Any]
Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]

CST: Final = timezone(timedelta(hours=8), name="CST")
JST: Final = timezone(timedelta(hours=9), name="JST")

Image.new("RGB", (1, 1), color="red").save((_ := BytesIO()), format="JPEG")
ONE_PIXEL_JPEG_BYTES: Final[bytes] = _.read()


def now_text(tz: timezone = CST) -> str:
    """Return Wolfx-like local time text with second precision."""

    return datetime.now(tz).strftime("%Y/%m/%d %H:%M:%S")


def utc_timestamp_ms() -> str:
    """Return current timestamp in milliseconds as the WebSocket docs describe."""

    return str(int(time.time() * 1000))


def clone_json(value: JsonObject) -> JsonObject:
    """Return a deep copy for safe per-request mutation."""

    return copy.deepcopy(value)


SAMPLE_JMA_EEW: Final[JsonObject] = {
    "Title": "緊急地震速報（予報）",
    "CodeType": "緊急地震速報",
    "Issue": {"Source": "気象庁", "Status": "通常"},
    "EventID": "20260718184600",
    "Serial": 3,
    "AnnouncedTime": "2026/07/18 19:46:15",
    "OriginTime": "2026/07/18 19:45:58",
    "Hypocenter": "トカラ列島近海",
    "Latitude": 29.4,
    "Longitude": 129.6,
    "Magunitude": 5.6,
    "Magnitude": 5.6,
    "Depth": 20,
    "MaxIntensity": "5-",
    "Accuracy": {
        "Epicenter": "震央精度：P波/S波レベル越え、IPF法（1点）",
        "Depth": "深さ精度：仮定震源要素",
        "Magnitude": "マグニチュード精度：全点P相",
    },
    "MaxIntChange": {"String": "ほぼ変化なし", "Reason": "不明"},
    "WarnArea": [
        {
            "Chiiki": "鹿児島県十島村",
            "Shindo1": "5-",
            "Shindo2": "4",
            "Time": "2026/07/18 19:46:24",
            "Type": "Warning",
            "Arrive": False,
        },
        {
            "Chiiki": "奄美地方",
            "Shindo1": "4",
            "Shindo2": "3",
            "Time": "2026/07/18 19:46:32",
            "Type": "Forecast",
            "Arrive": False,
        },
    ],
    "isSea": True,
    "isTraining": False,
    "isAssumption": False,
    "isWarn": True,
    "isFinal": False,
    "isCancel": False,
    "OriginalText": "これは開発用 mock データです。",
}

SAMPLE_SC_EEW: Final[JsonObject] = {
    "ID": 260718184612,
    "EventID": "SC20260718184600",
    "ReportTime": "2026-07-18 18:46:12",
    "ReportNum": 2,
    "OriginTime": "2026-07-18 18:45:53",
    "HypoCenter": "四川省阿坝州汶川县",
    "Latitude": 31.02,
    "Longitude": 103.42,
    "Magunitude": 4.8,
    "Magnitude": 4.8,
    "Depth": 12,
    "MaxIntensity": 5,
}

SAMPLE_CENC_EEW: Final[JsonObject] = {
    "ID": "CENC20260718184603001",
    "EventID": "20260718184603",
    "ReportTime": "2026-07-18 18:46:19",
    "ReportNum": 1,
    "OriginTime": "2026-07-18 18:46:03",
    "HypoCenter": "新疆阿克苏地区库车市",
    "Latitude": 41.72,
    "Longitude": 83.06,
    "Magnitude": 5.1,
    "Depth": 10,
    "MaxIntensity": 6,
}

SAMPLE_FJ_EEW: Final[JsonObject] = {
    "ID": 260718184615,
    "EventID": "FJ20260718184600",
    "ReportTime": "2026-07-18 18:46:15",
    "ReportNum": 4,
    "OriginTime": "2026-07-18 18:45:59",
    "HypoCenter": "台湾花莲县海域",
    "Latitude": 24.03,
    "Longitude": 121.82,
    "Magunitude": 5.4,
    "Magnitude": 5.4,
    "isFinal": True,
}

SAMPLE_CQ_EEW: Final[JsonObject] = {
    "ID": "CQ20260718184605002",
    "EventID": "20260718184605",
    "ReportTime": "2026-07-18 18:46:21",
    "ReportNum": 2,
    "OriginTime": "2026-07-18 18:46:05",
    "HypoCenter": "重庆市荣昌区",
    "Latitude": 29.41,
    "Longitude": 105.59,
    "Magnitude": 4.2,
    "Depth": None,
    "MaxIntensity": 4,
}

SAMPLE_CWA_EEW: Final[JsonObject] = {
    "ID": 260718184620,
    "ReportTime": "2026-07-18 18:46:20",
    "ReportNum": 3,
    "OriginTime": "2026-07-18 18:46:05",
    "HypoCenter": "台湾花莲县海域",
    "Latitude": 24.03,
    "Longitude": 121.82,
    "Magunitude": 5.8,
    "Magnitude": 5.8,
    "Depth": 15,
    "MaxIntensity": "5弱",
}

CENC_EQ_RECORDS: Final[dict[str, JsonObject]] = {
    "No1": {
        "type": "reviewed",
        "time": "2026-07-18 18:30:21",
        "location": "新疆阿克苏地区库车市",
        "placeName": "新疆阿克苏地区库车市",
        "magnitude": "5.1",
        "depth": "10",
        "latitude": "41.72",
        "longitude": "83.06",
        "intensity": "6",
    },
    "No2": {
        "type": "automatic",
        "time": "2026-07-18 17:12:08",
        "location": "四川阿坝州汶川县",
        "placeName": "四川阿坝州汶川县",
        "magnitude": "4.8",
        "depth": "12",
        "latitude": "31.02",
        "longitude": "103.42",
        "intensity": "5",
    },
}

JMA_EQ_RECORDS: Final[dict[str, JsonObject]] = {
    "No1": {
        "Title": "震源・震度情報",
        "EventID": "20260718194558",
        "time": "2026/07/18 19:45",
        "time_full": "2026/07/18 19:45:58",
        "location": "トカラ列島近海",
        "magnitude": "5.6",
        "shindo": "5-",
        "depth": "20km",
        "latitude": "29.4",
        "longitude": "129.6",
        "info": "津波の心配はありません。",
    },
    "No2": {
        "Title": "震源・震度情報",
        "EventID": "20260718162214",
        "time": "2026/07/18 16:22",
        "time_full": "2026/07/18 16:22:14",
        "location": "福島県沖",
        "magnitude": "4.3",
        "shindo": "3",
        "depth": "50km",
        "latitude": "37.5",
        "longitude": "141.7",
        "info": "",
    },
}

TYPE_TO_SAMPLE: Final[dict[str, JsonObject]] = {
    "jma_eew": SAMPLE_JMA_EEW,
    "sc_eew": SAMPLE_SC_EEW,
    "cenc_eew": SAMPLE_CENC_EEW,
    "fj_eew": SAMPLE_FJ_EEW,
    "cq_eew": SAMPLE_CQ_EEW,
    "cwa_eew": SAMPLE_CWA_EEW,
}

HTTP_JSON_ENDPOINTS: Final[dict[str, str]] = {
    "/jma_eew.json": "jma_eew",
    "/sc_eew.json": "sc_eew",
    "/cenc_eew.json": "cenc_eew",
    "/fj_eew.json": "fj_eew",
    "/cq_eew.json": "cq_eew",
    "/cwa_eew.json": "cwa_eew",
}

WS_QUERY_TO_TYPE: Final[dict[str, str]] = {
    "query_jmaeew": "jma_eew",
    "query_sceew": "sc_eew",
    "query_cenceew": "cenc_eew",
    "query_fjeew": "fj_eew",
    "query_cqeew": "cq_eew",
    "query_cenceqlist": "cenc_eqlist",
    "query_jmaeqlist": "jma_eqlist",
}


def with_ws_type(data_type: str, payload: JsonObject) -> JsonObject:
    """Add the WebSocket-only ``type`` field to a response copy."""

    data = clone_json(payload)
    data["type"] = data_type
    return data


def add_record_md5(records: dict[str, JsonObject]) -> dict[str, JsonObject]:
    """Return copied earthquake list records with stable md5 fields."""

    result: dict[str, JsonObject] = {}
    for key, record in records.items():
        item = clone_json(record)
        digest_source = json.dumps(item, ensure_ascii=False, sort_keys=True).encode(
            "utf-8"
        )
        item["md5"] = hashlib.md5(digest_source).hexdigest()
        result[key] = item
    return result


def cenc_eqlist_payload(*, websocket: bool = False) -> JsonObject:
    """Build a CENC latest-earthquakes response."""

    payload: JsonObject = add_record_md5(CENC_EQ_RECORDS)
    if websocket:
        payload["type"] = "cenc_eqlist"
    return payload


def jma_eqlist_payload(*, websocket: bool = False) -> JsonObject:
    """Build a JMA latest-earthquakes response."""

    payload: JsonObject = add_record_md5(JMA_EQ_RECORDS)
    payload["Title"] = "震源・震度情報"
    if websocket:
        payload["type"] = "jma_eqlist"
    return payload


def weather_rank_payload() -> JsonObject:
    """Build a compact weather ranking payload following Wolfx field names."""

    now = datetime.now(CST).replace(minute=0, second=0, microsecond=0)
    result: JsonObject = {}
    for hours_ago in range(8):
        key = (now - timedelta(hours=hours_ago)).strftime("%Y%m%d%H00")
        item: JsonObject = {
            "tempRank": [
                {
                    "station": "吐鲁番",
                    "province": "新疆",
                    "temperature": 42.1 - hours_ago * 0.3,
                },
                {
                    "station": "重庆沙坪坝",
                    "province": "重庆",
                    "temperature": 39.7 - hours_ago * 0.2,
                },
                {
                    "station": "福州",
                    "province": "福建",
                    "temperature": 37.5 - hours_ago * 0.15,
                },
                {
                    "station": "杭州",
                    "province": "浙江",
                    "temperature": 36.8 - hours_ago * 0.1,
                },
                {
                    "station": "南昌",
                    "province": "江西",
                    "temperature": 36.2 - hours_ago * 0.12,
                },
                {
                    "station": "武汉",
                    "province": "湖北",
                    "temperature": 35.9 - hours_ago * 0.08,
                },
                {
                    "station": "南京",
                    "province": "江苏",
                    "temperature": 35.4 - hours_ago * 0.1,
                },
                {
                    "station": "长沙",
                    "province": "湖南",
                    "temperature": 35.0 - hours_ago * 0.2,
                },
                {
                    "station": "西安",
                    "province": "陕西",
                    "temperature": 34.7 - hours_ago * 0.18,
                },
                {
                    "station": "郑州",
                    "province": "河南",
                    "temperature": 34.3 - hours_ago * 0.15,
                },
            ],
            "rainRank": [
                {"station": "海口", "province": "海南", "rain": 42.8 + hours_ago},
                {"station": "福州", "province": "福建", "rain": 35.4 + hours_ago},
                {"station": "广州", "province": "广东", "rain": 28.6 + hours_ago},
                {"station": "南宁", "province": "广西", "rain": 22.1 + hours_ago},
                {"station": "长沙", "province": "湖南", "rain": 18.7 + hours_ago},
                {"station": "南昌", "province": "江西", "rain": 15.3 + hours_ago},
                {"station": "贵阳", "province": "贵州", "rain": 12.8 + hours_ago},
                {"station": "杭州", "province": "浙江", "rain": 9.5 + hours_ago},
                {"station": "成都", "province": "四川", "rain": 6.2 + hours_ago},
                {"station": "昆明", "province": "云南", "rain": 3.1 + hours_ago},
            ],
            "windSRank": [
                {"station": "舟山", "province": "浙江", "windSpeed": 24.6},
                {"station": "大连", "province": "辽宁", "windSpeed": 20.1},
                {"station": "青岛", "province": "山东", "windSpeed": 18.3},
                {"station": "厦门", "province": "福建", "windSpeed": 16.7},
                {"station": "温州", "province": "浙江", "windSpeed": 15.2},
                {"station": "三亚", "province": "海南", "windSpeed": 14.8},
                {"station": "连云港", "province": "江苏", "windSpeed": 13.5},
                {"station": "湛江", "province": "广东", "windSpeed": 12.1},
                {"station": "天津", "province": "天津", "windSpeed": 10.6},
                {"station": "上海浦东", "province": "上海", "windSpeed": 9.3},
            ],
        }
        digest_source = json.dumps(item, ensure_ascii=False, sort_keys=True).encode(
            "utf-8"
        )
        item["md5"] = hashlib.md5(digest_source).hexdigest()
        result[key] = item
    return result


async def json_response(payload: JsonObject) -> web.Response:
    """Return JSON with Wolfx-like UTF-8 output."""

    return web.json_response(
        payload, dumps=lambda obj: json.dumps(obj, ensure_ascii=False)
    )


async def handle_eew(request: web.Request) -> web.Response:
    """Handle single EEW HTTP endpoints."""

    data_type = HTTP_JSON_ENDPOINTS[request.path]
    return await json_response(clone_json(TYPE_TO_SAMPLE[data_type]))


async def handle_cenc_eqlist(_: web.Request) -> web.Response:
    """Handle ``/cenc_eqlist.json``."""

    return await json_response(cenc_eqlist_payload())


async def handle_jma_eqlist(_: web.Request) -> web.Response:
    """Handle ``/jma_eqlist.json``."""

    return await json_response(jma_eqlist_payload())


async def handle_weather_rank(_: web.Request) -> web.Response:
    """Handle ``/weather_rank.json``."""

    return await json_response(weather_rank_payload())


async def handle_geoip(request: web.Request) -> web.Response:
    """Handle ``/geoip.php`` with optional ``ip`` query parameter."""

    ip = request.query.get("ip") or request.remote or "127.0.0.1"
    return await json_response(
        {
            "ip": ip,
            "country_code": "CN",
            "country_name": "China",
            "country_name_zh": "中国",
            "province_code": "31",
            "province_name": "Shanghai",
            "province_name_zh": "上海市",
            "city": "Shanghai",
            "city_zh": "上海",
            "latitude": 31.2304,
            "longitude": 121.4737,
        }
    )


async def handle_ntp(_: web.Request) -> web.Response:
    """Handle ``/ntp.json``."""

    now_utc = datetime.now(UTC)
    cst_now = now_utc.astimezone(CST)
    return await json_response(
        {
            "JST": now_utc.astimezone(JST).strftime("%Y/%m/%d %H:%M:%S"),
            "CST": cst_now.strftime("%Y/%m/%d %H:%M:%S"),
            "str": cst_now.strftime("%Y/%m/%d %H:%M:%S"),
            "int": int(cst_now.strftime("%Y%m%d%H%M%S")),
            "timestamp": int(now_utc.timestamp()),
        }
    )


async def handle_ip(request: web.Request) -> web.Response:
    """Handle plain-text ``/ip.php``."""

    return web.Response(text=request.remote or "127.0.0.1", content_type="text/plain")


async def handle_img(request: web.Request) -> web.Response:
    """Handle ``/img.php`` and ``/img.php?return=...``."""

    if "return" in request.query:
        url = str(request.url.with_query({}))
        return web.Response(
            text=f"![mock wolfx image]({url})", content_type="text/plain"
        )
    return web.Response(body=ONE_PIXEL_JPEG_BYTES, content_type="image/jpeg")


def payload_for_type(data_type: str) -> JsonObject:
    """Return a WebSocket payload for the requested Wolfx data type."""

    if data_type == "cenc_eqlist":
        return cenc_eqlist_payload(websocket=True)
    if data_type == "jma_eqlist":
        return jma_eqlist_payload(websocket=True)
    return with_ws_type(data_type, TYPE_TO_SAMPLE[data_type])


def initial_ws_types(path: str) -> list[str]:
    """Map a WebSocket request path to initial data types to push."""

    data_type = path.strip("/")
    if data_type == "all_eew":
        return ["jma_eew", "sc_eew", "cenc_eew", "fj_eew", "cq_eew"]
    # cwa_eew is HTTP-only (no WebSocket per the Wolfx docs)
    if data_type in {"cenc_eqlist", "jma_eqlist"}:
        return [data_type]
    if data_type in TYPE_TO_SAMPLE and data_type != "cwa_eew":
        return [data_type]
    return []


async def send_ws_json(ws: web.WebSocketResponse, payload: JsonObject) -> None:
    """Send JSON to a WebSocket client."""

    await ws.send_str(json.dumps(payload, ensure_ascii=False))


async def heartbeat_loop(
    ws: web.WebSocketResponse, client_id: str, interval: float
) -> None:
    """Periodically send Wolfx-like heartbeat packets."""

    try:
        while not ws.closed:
            await send_ws_json(
                ws,
                {
                    "type": "heartbeat",
                    "ver": 20260415,
                    "id": client_id,
                    "timestamp": utc_timestamp_ms(),
                },
            )
            await asyncio.sleep(interval)
    except ConnectionResetError:
        return


async def handle_ws(request: web.Request) -> web.WebSocketResponse:
    """Handle Wolfx-compatible WebSocket endpoints and manual query commands."""

    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)

    client_id = str(uuid.uuid4())
    heartbeat_task = asyncio.create_task(
        heartbeat_loop(ws, client_id, request.app["heartbeat_interval"])
    )
    clients: dict[str, set[web.WebSocketResponse]] = request.app["clients"]
    endpoint = request.path.strip("/")
    clients.setdefault(endpoint, set()).add(ws)

    try:
        # 真实服务端建连后只发心跳; 需要样本时用 --push-on-connect 或 POST /_mock/push
        if request.app["push_on_connect"]:
            for data_type in initial_ws_types(request.path):
                await send_ws_json(ws, payload_for_type(data_type))

        async for message in ws:
            if message.type != WSMsgType.TEXT:
                if message.type == WSMsgType.ERROR:
                    break
                continue

            command = message.data.strip()
            if command == "ping":
                await send_ws_json(
                    ws, {"type": "pong", "timestamp": utc_timestamp_ms()}
                )
                continue

            data_type = WS_QUERY_TO_TYPE.get(command)
            if data_type is not None:
                await send_ws_json(ws, payload_for_type(data_type))
                continue

            await send_ws_json(
                ws,
                {
                    "type": "error",
                    "message": f"unsupported mock command: {command}",
                    "supported": ["ping", *WS_QUERY_TO_TYPE],
                },
            )
    finally:
        clients[endpoint].discard(ws)
        heartbeat_task.cancel()
        await asyncio.gather(heartbeat_task, return_exceptions=True)

    return ws


def _endpoints_for(data_type: str) -> set[str]:
    """一条某类型的报文会出现在哪些 ws 端点上 (all_eew 汇总所有预警)"""
    eps = {data_type}
    if data_type.endswith("_eew"):
        eps.add("all_eew")
    return eps


async def handle_push(request: web.Request) -> web.Response:
    """开发用: ``POST /_mock/push`` 向已连接的客户端推一条报文.

    body 是一个 JSON 对象, 必须带 ``type`` (如 ``cenc_eew``); 不带其余字段时用内置样本,
    并把发报/发震时间改成当前时间, 方便触发 "新鲜" 的推送。
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "body must be JSON"}, status=400)
    if not isinstance(body, dict) or not isinstance(body.get("type"), str):
        return web.json_response({"error": "missing 'type'"}, status=400)
    data_type: str = body["type"]
    if len(body) == 1:
        if data_type not in TYPE_TO_SAMPLE and data_type not in {
            "cenc_eqlist",
            "jma_eqlist",
        }:
            return web.json_response(
                {"error": f"no sample for {data_type}"}, status=400
            )
        payload = fresh_sample(data_type)
    else:
        payload = body
    clients: dict[str, set[web.WebSocketResponse]] = request.app["clients"]
    targets = {ws for ep in _endpoints_for(data_type) for ws in clients.get(ep, ())}
    for ws in targets:
        await send_ws_json(ws, payload)
    return web.json_response({"sent_to": len(targets), "payload": payload})


def fresh_sample(data_type: str) -> JsonObject:
    """内置样本, 时间改成现在"""
    payload = payload_for_type(data_type)
    if data_type == "jma_eew":
        tz, fmt = JST, "%Y/%m/%d %H:%M:%S"
    else:
        tz, fmt = CST, "%Y-%m-%d %H:%M:%S"
    now = datetime.now(tz)
    origin = (now - timedelta(seconds=10)).strftime(fmt)
    if data_type in {"cenc_eqlist", "jma_eqlist"}:
        entry = payload["No1"]
        if data_type == "jma_eqlist":
            entry["time_full"] = (now - timedelta(minutes=5)).strftime(fmt)
            entry["time"] = entry["time_full"][:-3]
        else:
            entry["time"] = (now - timedelta(minutes=5)).strftime(fmt)
            entry["ReportTime"] = now.strftime(fmt)
        return payload
    for key in ("ReportTime", "AnnouncedTime"):
        if key in payload:
            payload[key] = now.strftime(fmt)
    payload["OriginTime"] = origin
    return payload


async def handle_index(request: web.Request) -> web.Response:
    """Expose a small endpoint index for humans."""

    scheme = "ws" if request.scheme == "http" else "wss"
    host = request.host
    endpoints = {
        "http_json": [
            *HTTP_JSON_ENDPOINTS,
            "/cenc_eqlist.json",
            "/jma_eqlist.json",
            "/weather_rank.json",
            "/geoip.php",
            "/ntp.json",
        ],
        "http_plain": ["/ip.php"],
        "http_image": ["/img.php"],
        "websocket": [
            f"{scheme}://{host}/{name}"
            for name in [
                "all_eew",
                "sc_eew",
                "jma_eew",
                "fj_eew",
                "cq_eew",
                "cenc_eew",
                "cenc_eqlist",
                "jma_eqlist",
            ]
        ],
        "websocket_commands": ["ping", *WS_QUERY_TO_TYPE],
    }
    return await json_response(
        {"service": "Wolfx Open API mock", "time": now_text(), "endpoints": endpoints}
    )


def create_app(
    *, heartbeat_interval: float = 60.0, push_on_connect: bool = False
) -> web.Application:
    """Create the aiohttp application."""

    app = web.Application()
    app["heartbeat_interval"] = heartbeat_interval
    app["push_on_connect"] = push_on_connect
    app["clients"] = {}
    app.router.add_post("/_mock/push", handle_push)

    for path in HTTP_JSON_ENDPOINTS:
        app.router.add_get(path, handle_eew)

    routes: dict[str, Handler] = {
        "/": handle_index,
        "/cenc_eqlist.json": handle_cenc_eqlist,
        "/jma_eqlist.json": handle_jma_eqlist,
        "/weather_rank.json": handle_weather_rank,
        "/geoip.php": handle_geoip,
        "/ntp.json": handle_ntp,
        "/ip.php": handle_ip,
        "/img.php": handle_img,
        "/all_eew": handle_ws,
        "/sc_eew": handle_ws,
        "/jma_eew": handle_ws,
        "/fj_eew": handle_ws,
        "/cq_eew": handle_ws,
        "/cenc_eew": handle_ws,
        "/cenc_eqlist": handle_ws,
        "/jma_eqlist": handle_ws,
    }
    for path, handler in routes.items():
        app.router.add_get(path, handler)

    return app


def parse_args() -> argparse.Namespace:
    """Parse command-line options."""

    parser = argparse.ArgumentParser(
        description="Run a local Wolfx Open API mock server."
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="Host to bind. Default: 127.0.0.1"
    )
    parser.add_argument(
        "--port", type=int, default=8765, help="Port to bind. Default: 8765"
    )
    parser.add_argument(
        "--heartbeat-interval",
        type=float,
        default=60.0,
        help="WebSocket heartbeat interval in seconds. Default: 60 (matches Wolfx server: every minute)",
    )
    parser.add_argument(
        "--push-on-connect",
        action="store_true",
        help="Push the built-in samples right after a client connects "
        "(the real server only sends a heartbeat).",
    )
    return parser.parse_args()


def main() -> None:
    """Run the mock server."""

    args = parse_args()
    app = create_app(
        heartbeat_interval=args.heartbeat_interval,
        push_on_connect=args.push_on_connect,
    )
    web.run_app(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
