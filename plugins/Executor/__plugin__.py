import functools
from asyncio import subprocess

from melobot import Plugin, get_logger, GenericLogger
from melobot.protocols.onebot.v11 import on_message, on_start_match, Adapter
from melobot.protocols.onebot.v11.adapter.event import MessageEvent
from melobot.session import enter_session, get_rule, suspend
from melobot.session.option import Rule

import checker_factory


@on_start_match(".shell", checker=lambda e: e.sender.user_id == checker_factory.owner)
async def run_shell(event: MessageEvent, adapter: Adapter, logger: GenericLogger):
    if len(_ := event.text.split(maxsplit=1)) != 2:
        return
    cmd = _[1].strip()
    if not cmd:
        return


@on_start_match(".pyexec", checker=lambda e: e.sender.user_id == checker_factory.owner)
async def exec_py(event: MessageEvent, adapter: Adapter, logger: GenericLogger):
    pass


class Executor(Plugin):
    version = "0.1.0"
    author = "LemonyNingmeng"
    flows = (run_shell,)
