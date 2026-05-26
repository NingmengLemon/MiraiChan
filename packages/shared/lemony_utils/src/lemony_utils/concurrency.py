import threading
from collections.abc import Generator
from contextlib import contextmanager

from melobot.utils.common import RWContext as AsyncRWContext

__all__ = ["AsyncRWContext", "SyncRWContext"]


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
