import asyncio
import contextlib
import functools
import threading
from collections.abc import Awaitable, Callable, Generator
from contextlib import contextmanager

__all__ = ["SyncRWContext", "to_async", "gather_with_concurrency"]


class SyncRWContext:
    def __init__(self, read_limit: int | None = None) -> None:
        """初始化同步读写上下文

        same as RWContext in melobot.utils but for synchronous code.
        """
        self.write_semaphore = threading.Semaphore(1)
        self.read_semaphore = threading.Semaphore(read_limit) if read_limit else None
        self.read_num = 0
        self.read_num_lock = threading.Lock()

    @contextmanager
    def read(self) -> Generator[None, None, None]:
        """获取读锁上下文。

        多个读者可同时持有读锁；当第一个读者进入时阻塞写者，
        直到所有读者退出后才释放写锁。
        """
        if self.read_semaphore:
            self.read_semaphore.acquire()

        with self.read_num_lock:
            if self.read_num == 0:
                self.write_semaphore.acquire()
            self.read_num += 1

        try:
            yield
        finally:
            with self.read_num_lock:
                self.read_num -= 1
                if self.read_num == 0:
                    self.write_semaphore.release()
                if self.read_semaphore:
                    self.read_semaphore.release()

    @contextmanager
    def write(self) -> Generator[None, None, None]:
        """获取写锁上下文。

        写锁为排他锁，会阻塞所有其他读者和写者，直到当前写者退出。
        """
        self.write_semaphore.acquire()
        try:
            yield
        finally:
            self.write_semaphore.release()


def to_async[**P, T](func: Callable[P, T]) -> Callable[P, Awaitable[T]]:
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        return await asyncio.to_thread(func, *args, **kwargs)

    return wrapper


async def gather_with_concurrency[T](
    *aws: Awaitable[T], concurrency: int = 4, return_exceptions: bool = False
) -> list[T | BaseException]:
    """并发执行若干可等待对象, 同时最多运行 concurrency 个, 结果顺序与入参一致.

    ``return_exceptions=False`` 时, 任一个任务抛异常都会取消其余任务并等它们结束, 再把
    异常原样抛出。``asyncio.gather`` 自己不这么做: 调用方拿到异常就开始收尾, 而兄弟任务
    还在后台继续跑, 收尾期间继续产生副作用, 它们的异常也只能以 "Task exception was never
    retrieved" 的形式落到日志里。
    """
    semaphore = asyncio.Semaphore(concurrency)

    async def wrapper(aw: Awaitable[T]) -> T:
        async with semaphore:
            return await aw

    tasks = [asyncio.ensure_future(wrapper(aw)) for aw in aws]
    try:
        return await asyncio.gather(*tasks, return_exceptions=return_exceptions)
    except BaseException:
        for task in tasks:
            task.cancel()
        # 自身也在被取消时, 等待清理会再次抛 CancelledError: 忽略它, 让原来的异常继续向上
        with contextlib.suppress(BaseException):
            await asyncio.gather(*tasks, return_exceptions=True)
        raise
