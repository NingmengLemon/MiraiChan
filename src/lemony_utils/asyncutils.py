import threading
import asyncio
from asyncio import subprocess
import functools
import sys
import signal
from typing import Optional, Mapping, Iterable, Any, Callable


def to_thread_decorator(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        return await asyncio.to_thread(func, *args, **kwargs)

    return wrapper


class ThreadWithReturn(threading.Thread):
    def __init__(
        self,
        group: None = None,
        target: Optional[Callable[..., Any]] = None,
        name: Optional[str] = None,
        args: Iterable[Any] = (),
        kwargs: Optional[Mapping[str, Any]] = None,
        *,
        daemon: bool | None = None,
    ) -> None:
        super().__init__(group, target, name, args, kwargs, daemon=daemon)
        self._args = args
        self._kwargs = kwargs
        self._target = target
        self.result: Any = None
        self.exception: Optional[Exception] = None

    def run(self) -> None:
        try:
            if self._kwargs is None:
                self._kwargs = {}
            if self._target:
                self.result = self._target(*self._args, **self._kwargs)
        except Exception as e:
            self.exception = e
        finally:
            del self._target, self._args, self._kwargs


class NotStartedError(Exception):
    pass


class InteractiveProcess:
    def __init__(self, cmd: str):
        self._process: asyncio.subprocess.Process | None = None
        self._cmd = cmd

    async def start(self):
        self._process = await asyncio.create_subprocess_shell(
            cmd=self._cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    async def send(self, content: str, end: str = "\n"):
        if self._process is None:
            raise NotStartedError("call start() first before you act")
        self._process.stdin.write((content + end).encode("utf-8", errors="replace"))
        await self._process.stdin.drain()

    async def readline(self, strip: bool = False):
        if self._process is None:
            raise NotStartedError("call start() first before you act")
        output = (await self._process.stdout.readline()).decode(
            "utf-8", errors="replace"
        )
        return output.strip() if strip else output

    async def drain_output(self):
        while True:
            line = await self.readline(strip=False)
            if not line:
                break
            print("drained:", line.strip())

    async def close(self, force: bool = False):
        if self._process is None:
            raise NotStartedError("call start() first before you act")
        if (code := self._process.returncode) is None:
            if force:
                if sys.platform == "win32":
                    self._process.kill()
                else:
                    self._process.send_signal(signal.SIGKILL)
            else:
                self._process.send_signal(signal.SIGTERM)
            code = await self._process.wait()
        self._process = None
        return code
