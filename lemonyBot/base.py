from abc import abstractmethod
import os
import json
import logging
import threading
import time
import asyncio
import queue
import copy

import websockets
import aiohttp
import aiofiles


class SocketBase:
    """
    一切的开始

    start 方法被调用时应该是程序的开始, 因为此操作会阻塞线程
    """

    def __init__(self, host: str, authkey: str = None) -> None:
        self._ws_host = host
        self._ws_authkey = authkey
        if not self._ws_host.startswith("ws://"):
            self._ws_host = "ws://" + self._ws_host

    # @abstractmethod
    def recv(self, msg: str):
        """
        这个方法由启动后的程序自动调用, 传递收到的消息

        需要子类重写来实现收到消息时的行为
        """
        pass

    # @abstractmethod
    def error(self, err: Exception):
        logging.exception(err)

    async def __ws_recv_loop(self):
        while True:
            try:
                params = {}
                if self._ws_authkey:
                    params["extra_headers"] = {"Authorization": self._ws_authkey}
                async with websockets.connect(self._ws_host, **params) as ws:
                    while True:
                        try:
                            self.recv(await ws.recv())
                        except Exception as e:
                            self.error(e)
            except websockets.ConnectionClosed as e:
                logging.error("ws session closed: %s" % e)
                await asyncio.sleep(2)
            except KeyboardInterrupt:
                break
            except Exception as e:
                logging.exception(e)
                logging.error("Error while interacting: %s" % e)
                await asyncio.sleep(1)

    def start(self):
        asyncio.run(self.__ws_recv_loop())


class HttpBase:
    default_headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Charset": "UTF-8,*;q=0.5",
        "Accept-Encoding": "gzip,deflate,sdch",
        "Accept-Language": "en-US,en;q=0.8",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/79.0.3945.74 Safari/537.36 Edg/79.0.309.43",
    }

    def __init__(self):
        self._loop = asyncio.new_event_loop()
        self._session = aiohttp.ClientSession(loop=self._loop)
        self.__run_async_loop()

    def __async_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def __run_async_loop(self):
        thread = threading.Thread(target=self.__async_loop, name="aiohttp_event_loop")
        thread.setDaemon(True)
        thread.start()

    def add_task(self, coro):
        asyncio.run_coroutine_threadsafe(coro=coro, loop=self._loop)

    async def request(
        self, url, mod="get", data=None, return_type="str",req_type="dict", headers=None, **kwargs
    ) -> str | dict | bytes:
        result = None
        if headers is None:
            headers = copy.deepcopy(HttpBase.default_headers)
        # if data is None:
        #     data = {}
        # data = json.dumps(data)
        if mod.lower().strip() == "post":
            func = self._session.post
        else:
            func = self._session.get

        try:
            async with func(url, data=data, headers=headers, **kwargs) as req:
                match return_type.lower().strip():
                    case "str":
                        result = await req.text()
                    case "json" | "dict":
                        result = await req.json()
                    case _:
                        result = await req.read()
        except Exception as e:
            self.event_request_failed(e)
            raise
        else:
            self.event_request_ok(url)
            return result

    async def download(self, url, dest, chunk_size=1024, **kwargs):
        try:
            async with self._session.get(url, **kwargs) as req:
                #

                async with aiofiles.open(dest, "wb+") as f:
                    async for chunk in req.content.iter_chunked(chunk_size):
                        await f.write(chunk)
        except Exception as e:
            self.event_download_failed(e)
        else:
            self.event_download_ok(url)

    # 以下是留给用户重写的方法

    def event_download_ok(self, url):
        pass

    def event_download_failed(self, err):
        logging.error("download file error: %s" % err)
        logging.exception(err)

    def event_request_ok(self, url):
        pass

    def event_request_failed(self, err):
        logging.error("request error: %s" % err)
        logging.exception(err)


class Tester(SocketBase):
    def __init__(self, host: str) -> None:
        super().__init__(host)

    def recv(self, msg: str):
        j = json.loads(msg)
        # if j.get("post_type") != "meta_event":
        print(msg)


if __name__ == "__main__":
    sb = Tester("ws://172.16.40.5:5800")
    sb.start()
