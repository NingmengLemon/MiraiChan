import functools
import asyncio
import subprocess

from melobot import Plugin, get_logger, GenericLogger
from melobot.protocols.onebot.v11 import on_message, on_start_match, Adapter
from melobot.protocols.onebot.v11.adapter.event import MessageEvent
from melobot.session import enter_session, get_rule, suspend
from melobot.session.option import Rule

import checker_factory


def run_shell_command(command):
    result = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout, result.stderr, result.returncode


@on_start_match(".sh", checker=lambda e: e.sender.user_id == checker_factory.owner)
async def run_shell(event: MessageEvent, adapter: Adapter, logger: GenericLogger):
    if len(_ := event.text.split(maxsplit=1)) != 2:
        return
    cmd = _[1].strip()
    if not cmd:
        return
    await adapter.send_reply("开始运行指令，请坐和放宽...")
    logger.debug(f"executing > {cmd}")
    stdout, stderr, code = await asyncio.to_thread(run_shell_command, cmd)
    reply = []
    if s := stdout.strip():
        reply.append(f"stdout:\n{s}")
    if s := stderr.strip():
        reply.append(f"stderr:\n{s}")
    reply.append(f"\ncode = {code}")
    await adapter.send_reply("\n".join(reply))


@on_start_match(".pyexec", checker=lambda e: e.sender.user_id == checker_factory.owner)
async def exec_py(event: MessageEvent, adapter: Adapter, logger: GenericLogger):
    pass


class Executor(Plugin):
    version = "0.1.0"
    author = "LemonyNingmeng"
    flows = (run_shell,)
