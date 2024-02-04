import asyncio
import threading
import queue
import base64
import io
from typing import Callable
import logging

import aiohttp

async def multi_downloader(request, *urls, runner=asyncio.run, return_type="base64"):
    recv_queue = queue.Queue()
    error_queue = queue.Queue()
    async def task(url):
        try:
            async with request(url) as f:
                f: aiohttp.ClientResponse
                match return_type.strip().lower():
                    case "bytes":
                        recv_queue.put(await f.read())
                    case "base64":
                        bio = io.BytesIO(await f.read())
                        recv_queue.put(base64.b64encode(bio).decode())
                    case _:
                        recv_queue.put(bio)
        except Exception as e:
            logging.exception(e)
            error_queue.put(url)
    for u in urls:
        runner(task(url=u))
    while True:
        await asyncio.sleep(0.2)
