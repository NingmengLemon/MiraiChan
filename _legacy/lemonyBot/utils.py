import asyncio
from collections.abc import Callable, Iterable, Mapping
import threading
from io import BytesIO
from typing import Any, Callable
import logging
import base64

from PIL.Image import Image
import qrcode


def make_qrcode(data) -> bytes:
    qr = qrcode.QRCode()
    qr.add_data(data)
    img: Image = qr.make_image()
    a = BytesIO()
    img.save(a, "jpeg")
    return a.getvalue()


class Thread_with_return(threading.Thread):
    def __init__(
        self,
        group: None = None,
        target: Callable[..., object] | None = None,
        name: str | None = None,
        args: Iterable[Any] = ...,
        kwargs: Mapping[str, Any] | None = None,
        *,
        daemon: bool | None = None,
    ) -> None:
        super().__init__(group, target, name, args, kwargs, daemon=daemon)
        self.return_value = None
        self.exception = None

    def run(self) -> None:
        try:
            self.return_value = self._target(*self._args, **self._kwargs)
        except Exception as e:
            self.exception = e
        finally:
            del self._target, self._args, self._kwargs


async def async_adapter(func, *args, **kwargs):
    thread = Thread_with_return(target=func, args=args, kwargs=kwargs, daemon=True)
    thread.start()
    while thread.is_alive():
        await asyncio.sleep(0.1)
    if e := thread.exception:
        raise e
    return thread.return_value
