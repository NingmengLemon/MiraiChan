from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.types import Update
from melobot.io import AbstractIOSource
from melobot.log import logger

from ..const import PROTOCOL_IDENTIFIER
from .packet import EchoPacket, InPacket, OutPacket

_log = logging.getLogger(__name__)


class TelegramPollingIO(AbstractIOSource[InPacket, OutPacket, EchoPacket]):
    """基于 aiogram 长轮询的 Telegram IO 源

    :param token: Telegram Bot Token
    :param polling_timeout: 长轮询超时（秒）
    :param bot_properties: 传给 DefaultBotProperties 的参数
    :param dp_kwargs: 传给 Dispatcher 构造的额外参数
    """

    def __init__(
        self,
        token: str,
        *,
        polling_timeout: int = 10,
        bot_properties: dict[str, Any] | None = None,
        dp_kwargs: dict[str, Any] | None = None,
    ) -> None:
        super().__init__()
        self.protocol = PROTOCOL_IDENTIFIER
        self._token = token
        self._polling_timeout = polling_timeout
        self._bot_properties = bot_properties or {}
        self._dp_kwargs = dp_kwargs or {}

        self._bot: Bot | None = None
        self._dp: Dispatcher | None = None

        self._in_queue: asyncio.Queue[InPacket] = asyncio.Queue()
        self._opened = asyncio.Event()
        self._polling_task: asyncio.Task[None] | None = None

    @property
    def bot(self) -> Bot:
        """获取底层 aiogram Bot 实例"""
        if self._bot is None:
            raise RuntimeError("Telegram IO 源尚未打开，无法获取 Bot 实例")
        return self._bot

    async def open(self) -> None:
        if self._opened.is_set():
            return

        default_props = DefaultBotProperties(**self._bot_properties)
        self._bot = Bot(token=self._token, default=default_props)
        self._dp = Dispatcher(**self._dp_kwargs)

        # 注册一个通用 update handler，把所有 update 推入队列
        @self._dp.update.outer_middleware()  # type: ignore[arg-type]
        async def _capture_update(
            handler: Any,
            update: Update,
            data: dict[str, Any],
        ) -> Any:
            await self._in_queue.put(
                InPacket(
                    time=float(update.update_id),
                    data=update,
                )
            )
            # 不调用 handler，更新由 melobot 侧处理
            return None

        self._polling_task = asyncio.create_task(self._run_polling())
        self._opened.set()
        logger.info("Telegram Polling IO 源已启动")

    async def _run_polling(self) -> None:
        """在后台运行 aiogram polling"""
        assert self._dp is not None and self._bot is not None
        try:
            await self._dp.start_polling(
                self._bot,
                polling_timeout=self._polling_timeout,
                handle_as_tasks=False,
                handle_signals=False,
                close_bot_session=False,
            )
        except asyncio.CancelledError:
            pass
        except Exception:
            _log.exception("Telegram polling 异常退出")

    def opened(self) -> bool:
        return self._opened.is_set()

    async def close(self) -> None:
        if not self._opened.is_set():
            return

        self._opened.clear()
        if self._dp is not None:
            await self._dp.stop_polling()
        if self._polling_task is not None:
            self._polling_task.cancel()
            try:
                await self._polling_task
            except asyncio.CancelledError:
                pass
            self._polling_task = None
        if self._bot is not None:
            await self._bot.session.close()
            self._bot = None
        self._dp = None
        logger.info("Telegram Polling IO 源已停止")

    async def input(self) -> InPacket:
        await self._opened.wait()
        return await self._in_queue.get()

    async def output(self, packet: OutPacket) -> EchoPacket:
        """执行输出操作（调用 Telegram Bot API）"""
        if self._bot is None:
            return EchoPacket(ok=False, prompt="Bot 实例不可用", noecho=True)

        method = packet.data
        if method is None:
            return EchoPacket(noecho=True)

        try:
            result = await self._bot(method)
            return EchoPacket(data=result, ok=True)
        except Exception as e:
            _log.exception("Telegram API 调用失败")
            return EchoPacket(
                ok=False,
                prompt=str(e),
                data=None,
            )
