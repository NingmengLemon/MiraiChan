import asyncio
import subprocess

from melobot.handle.register import on_start_match
from melobot.log.base import GenericLogger
from melobot.plugin.base import PluginPlanner
from melobot.protocols.onebot.v11 import Adapter
from melobot.protocols.onebot.v11.adapter.event import MessageEvent

import checker_factory
import little_helper
from lemony_utils.images import text_to_imgseg

Executor = PluginPlanner("0.1.0")
little_helper.register(
    "Executor",
    {
        "cmd": ".shell <shell>",
        "text": "运行 shell\n*Owner Only*",
    },
)


def run_shell_command(command):
    result = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
    )
    return result.stdout, result.stderr, result.returncode


@Executor.use
@on_start_match(".shell ", checker=checker_factory.get_owner_checker())
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
    if s := stdout:
        reply.append(f"stdout:\n{s.strip()}")
    if s := stderr:
        reply.append(f"stderr:\n{s.strip()}")
    reply.append(f"\ncode = {code}")
    await adapter.send_reply(await text_to_imgseg("\n".join(reply)))


@on_start_match(".pyexec", checker=checker_factory.get_owner_checker())
async def exec_py(event: MessageEvent, adapter: Adapter, logger: GenericLogger):
    raise NotImplementedError()
