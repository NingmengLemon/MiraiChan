from typing import AsyncGenerator
from contextlib import asynccontextmanager

from aiohttp import ClientSession
from melobot import get_bot
from melobot.plugin import Plugin, SyncShare

from .cookies import (
    cookiedicts_from_session,
    cookiedicts_to_morsels,
    loadable_tuples_from_morsels,
)
from .consts import http_headers
from .templates import async_reqtemplate
