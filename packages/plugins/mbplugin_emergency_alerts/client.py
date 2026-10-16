"""Wolfx WebSocket 客户端: 每个端点一条连接, 断线自动重连.

服务端每分钟发一次心跳; 超过 ``idle_timeout`` 没收到任何报文就认为连接已死, 主动断开重连,
避免半开连接让推送静默停掉。
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable, Sequence

import aiohttp

from .quake import Quake
from .sources.wolfx import WolfxParseError, parse_message

__all__ = ["WolfxClient"]

logger = logging.getLogger(__name__)

type QuakeHandler = Callable[[Quake], Awaitable[None]]


class WolfxClient:
    def __init__(
        self,
        base_url: str,
        endpoints: Sequence[str],
        on_quake: QuakeHandler,
        *,
        idle_timeout: float = 150.0,
        connect_timeout: float = 15.0,
        backoff_min: float = 1.0,
        backoff_max: float = 120.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._endpoints = list(dict.fromkeys(endpoints))
        self._on_quake = on_quake
        self._idle_timeout = idle_timeout
        self._connect_timeout = connect_timeout
        self._backoff_min = backoff_min
        self._backoff_max = backoff_max
        self._session: aiohttp.ClientSession | None = None
        self._tasks: list[asyncio.Task[None]] = []
        #: 每个端点是否处于已连接状态, 供状态查询
        self.connected: dict[str, bool] = dict.fromkeys(self._endpoints, False)

    def start(self) -> None:
        if self._tasks:
            return
        self._session = aiohttp.ClientSession()
        self._tasks = [
            asyncio.create_task(self._run(ep), name=f"wolfx:{ep}")
            for ep in self._endpoints
        ]

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        if self._session is not None:
            await self._session.close()
            self._session = None
        self.connected = dict.fromkeys(self._endpoints, False)

    async def _run(self, endpoint: str) -> None:
        url = f"{self._base}/{endpoint}"
        delay = self._backoff_min
        while True:
            try:
                received = await self._listen(url, endpoint)
            except asyncio.CancelledError:
                raise
            except (aiohttp.ClientError, TimeoutError, OSError) as e:
                received = False
                logger.warning(f"Wolfx {endpoint} 连接失败: {e!r}")
            except Exception:
                received = False
                logger.exception(f"Wolfx {endpoint} 连接出现意外错误")
            finally:
                self.connected[endpoint] = False
            # 收到过报文说明连接本身是好的, 重连从最短间隔开始
            delay = self._backoff_min if received else min(delay * 2, self._backoff_max)
            wait = delay * random.uniform(0.8, 1.2)
            logger.info(f"Wolfx {endpoint} 将在 {wait:.1f}s 后重连")
            await asyncio.sleep(wait)

    async def _listen(self, url: str, endpoint: str) -> bool:
        assert self._session is not None
        received = False
        # ws_receive 不设上限: 空闲判定由下面的 receive(timeout=...) 负责;
        # 建连 (DNS + TCP + TLS + 握手) 单独限时, 避免卡死在连接阶段
        async with asyncio.timeout(self._connect_timeout):
            ws = await self._session.ws_connect(
                url,
                # ClientWSTimeout 是 attrs 类, ty 暂不识别 attrs 生成的 __init__
                timeout=aiohttp.ClientWSTimeout(ws_receive=None, ws_close=5),  # ty: ignore[unknown-argument]
                autoping=True,
            )
        async with ws:
            self.connected[endpoint] = True
            logger.info(f"Wolfx {endpoint} 已连接")
            while True:
                try:
                    msg = await ws.receive(timeout=self._idle_timeout)
                except TimeoutError:
                    logger.warning(
                        f"Wolfx {endpoint} {self._idle_timeout:g}s 内没有任何报文, 重连"
                    )
                    return received
                if msg.type == aiohttp.WSMsgType.TEXT:
                    received = True
                    await self._handle(endpoint, msg.data)
                elif msg.type in (
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSING,
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.ERROR,
                ):
                    logger.warning(f"Wolfx {endpoint} 连接关闭: {msg.type.name}")
                    return received

    async def _handle(self, endpoint: str, raw: str) -> None:
        try:
            quake = parse_message(raw)
        except WolfxParseError as e:
            logger.warning(
                f"Wolfx {endpoint} 报文解析失败, 已丢弃: {e}; 原文 {raw[:300]!r}"
            )
            return
        if quake is None:
            return
        # 推送失败不能拖垮连接; 取消 (stop) 照常向上传播
        try:
            await self._on_quake(quake)
        except Exception:
            logger.exception(f"处理 {quake.source} {quake.event_id} 失败")
