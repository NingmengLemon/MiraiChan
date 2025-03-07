import asyncio
import functools
import threading
from asyncio import subprocess
from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import Any

from melobot.typ import AsyncCallable


def to_thread_decorator(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        return await asyncio.to_thread(func, *args, **kwargs)

    return wrapper


class ThreadWithReturn(threading.Thread):
    def __init__(
        self,
        group: None = None,
        target: Callable[..., Any] | None = None,
        name: str | None = None,
        args: Iterable[Any] = (),
        kwargs: Mapping[str, Any] | None = None,
        *,
        daemon: bool | None = None,
    ) -> None:
        super().__init__(group, target, name, args, kwargs, daemon=daemon)
        self._args = args
        self._kwargs = kwargs
        self._target = target
        self.result: Any = None
        self.exception: Exception | None = None

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

    async def close(self):
        if self._process is None:
            raise NotStartedError("call start() first before you act")
        if (code := self._process.returncode) is None:
            self._process.terminate()
            code = await self._process.wait()
        self._process = None
        return code

    @property
    def process(self):
        return self._process


async def gather_with_concurrency[
    T
](*aws: Awaitable[T], concurrency: int = 4, return_exceptions: bool = False) -> list[T]:
    semaphore = asyncio.Semaphore(concurrency)

    async def wrapper(aw: Awaitable[T]) -> T:
        async with semaphore:
            return await aw

    tasks = [wrapper(aw) for aw in aws]
    return await asyncio.gather(*tasks, return_exceptions=return_exceptions)


def async_retry[
    **P, T
](
    exceptions: type[Exception] | tuple[type[Exception], ...] = Exception,
    max_retries: int = 3,
    initial_delay: float = 1,
    exp_backoff: bool = True,
    max_delay: float = None,
):
    def decorator(func: AsyncCallable[P, T]):
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs):
            current_delay = initial_delay
            retries = 0

            while True:
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    if retries >= max_retries:
                        raise e

                    retries += 1
                    await asyncio.sleep(current_delay)

                    if exp_backoff:
                        current_delay *= 2
                        if max_delay is not None:
                            current_delay = min(current_delay, max_delay)

        return wrapper

    return decorator
