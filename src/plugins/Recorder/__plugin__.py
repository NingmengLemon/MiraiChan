import asyncio
import functools
import logging
from typing import Concatenate
from collections.abc import Callable
import hashlib
import mimetypes
import os
import posixpath
import time
from pathlib import Path

import aiofiles
from melobot import get_bot
from melobot.plugin import PluginPlanner
from melobot.typ import AsyncCallable
from melobot.log import get_logger
from melobot.utils import lock
from melobot.protocols.onebot.v11.handle import on_message
from melobot.protocols.onebot.v11.adapter import Adapter
from melobot.protocols.onebot.v11.adapter.event import (
    MessageEvent,
    GroupMessageEvent,
    PrivateMessageEvent,
)
from melobot.protocols.onebot.v11.adapter.segment import ImageSegment, RecordSegment
from yarl import URL
from sqlmodel import SQLModel, Session, select, func, col, or_
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.ext.asyncio.engine import create_async_engine

from lemony_utils.templates import async_http
from lemony_utils.consts import http_headers
from recorder_models import User, Group, Message, MessageSegment, MediaFile, TABLES

from .utils import get_context_messages


class RecorderCore:
    def __init__(self, dburl: str, echo: bool = False):
        self._url = dburl
        self._engine = create_async_engine(
            dburl, connect_args={"check_same_thread": False}, echo=echo
        )
        self._startup_event = asyncio.Event()

    @property
    def started(self):
        return self._startup_event

    async def startup(self):
        if self.started.is_set():
            raise RuntimeError("already started")
        async with self._engine.begin() as conn:
            await conn.run_sync(
                SQLModel.metadata.create_all, tables=TABLES, checkfirst=True
            )
        self._startup_event.set()

    def get_session(self, autoflush=False):
        if not self.started.is_set():
            raise RuntimeError("recorder not started yet")
        return AsyncSession(self._engine, autoflush=autoflush)

    async def run_sync[
        **P, T
    ](
        self,
        func: Callable[Concatenate[Session, P], T],
        *args: P.args,
        **kwargs: P.kwargs,
    ):
        """单开一个 AsyncSession 来执行第一个参数是 Session 的同步函数"""
        async with self.get_session() as asess:
            return await asess.run_sync(func, *args, **kwargs)

    def to_async[
        **P, T
    ](self, func: Callable[Concatenate[Session, P], T]) -> AsyncCallable[P, T]:
        """将执行第一个参数是 Session 的同步函数装饰成异步函数, 运行时会单开一个 AsyncSession"""

        @functools.wraps(func)
        async def wrapped(*args: P.args, **kwargs: P.kwargs):
            return await self.run_sync(func, *args, **kwargs)

        return wrapped


DB_URL = "sqlite+aiosqlite:///data/record/messages.db"
IMAGE_LOCATION = Path("data/record/images")
os.makedirs(IMAGE_LOCATION, exist_ok=True)
VOICE_LOCATION = Path("data/record/voices")
os.makedirs(VOICE_LOCATION, exist_ok=True)

logger = get_logger()
recorder = RecorderCore(
    DB_URL, echo=getattr(logger, "level", logging.INFO) == logging.DEBUG
)


def do_md5(d: bytes):
    return hashlib.md5(d).hexdigest()


def url_to_fileid(url: URL):
    if url.host == "multimedia.nt.qq.com.cn":
        return url.query["fileid"]
    elif url.host.endswith("qpic.cn"):
        return max(url.parts, key=len)
    # logger.warning(f"url {url} is not known url pattern")
    return str(url)


async def get_filepath(fileid: str):
    async with recorder.get_session() as sess:
        file = (
            await sess.exec(select(MediaFile).where(MediaFile.fileid == fileid))
        ).one_or_none()
        if file:
            return file.path
        else:
            return None


async def _fetch_mediafile(url: str | URL, dest: Path):
    dest.mkdir(parents=True, exist_ok=True)
    async with async_http(url, "get", headers=http_headers) as resp:
        resp.raise_for_status()
        data = await resp.read()
        extension = mimetypes.guess_extension(resp.headers["Content-Type"])
    filename = (md5 := await asyncio.to_thread(do_md5, data)) + (
        extension if extension else ""
    )
    path = (dest / filename).as_posix()
    return data, md5, path


@lock()
async def _store_mediafile(data: bytes, fileid: str, hash_str: str, path: str):
    do_write = True
    logger.debug(f"MediaFile(fileid={fileid!r}) download ok, now saving...")
    async with recorder.get_session() as sess:
        img = (
            await sess.exec(select(MediaFile).where(MediaFile.fileid == fileid))
        ).one()
        former_imgs = (
            await sess.exec(
                select(MediaFile)
                .where(MediaFile.hash == hash_str)
                .order_by(col(MediaFile.timestamp).desc())
            )
        ).all()
        # 找到从前可能存在的有效图片路径
        former_existing_path = None
        missing_images: list[MediaFile] = []
        for i in former_imgs:
            if i.path and (_ := Path(i.path)).exists():
                former_existing_path = _.as_posix()
            else:
                missing_images.append(i)

        if former_existing_path:
            path = Path(former_existing_path).as_posix()
            do_write = False
            logger.debug(
                f"Former MediaFile record found as {path!r}, dont save new one"
            )
        if missing_images:
            for i in missing_images:
                i.path = path
            sess.add_all(missing_images)
            logger.debug(
                f"Refresh paths of {len(missing_images)} former media file, cuz they are missing"
            )
        if do_write and posixpath.exists(path):
            logger.debug(f"Media file already exists as {path!r}, dont write")
            do_write = False
        img.hash = hash_str
        img.path = path
        sess.add(img)
        await sess.commit()
    if do_write:
        async with aiofiles.open(path, "wb+") as fp:
            await fp.write(data)
        logger.debug(f"MediaFile(fileid={fileid!r}) saved as {path!r}")


async def handle_mediafile(url: str | URL):
    url = URL(url)  # .with_scheme("http")
    dest = IMAGE_LOCATION / time.strftime("%Y-%m", time.localtime())
    # TODO: 处理语音文件
    fileid = url_to_fileid(url)
    try:
        data, md5, path = await _fetch_mediafile(url, dest)
    except Exception as e:
        logger.warning(f"Exception while fetching img: {e}")
    else:
        await _store_mediafile(data, fileid=fileid, hash_str=md5, path=path)


async def ensure_user(session: AsyncSession, uid: int, name: str | None = None):
    user = (await session.exec(select(User).where(User.id == uid))).one_or_none()
    if user is None:
        user = User(id=uid, name=name)
        session.add(user)
    return user


async def ensure_group(session: AsyncSession, gid: int, name: str | None = None):
    group = (await session.exec(select(Group).where(Group.id == gid))).one_or_none()
    if group is None:
        group = Group(id=gid, name=name)
        session.add(group)
    return group


async def ensure_mediafile(session: AsyncSession, fileid: str):
    img = (
        await session.exec(select(MediaFile).where(MediaFile.fileid == fileid))
    ).one_or_none()
    if img is None:
        img = MediaFile(fileid=fileid)
        session.add(img)


async def fix_group_name(adapter: Adapter):
    async with recorder.get_session() as sess:
        groups = (await sess.exec(select(Group).where(col(Group.name).is_(None)))).all()
        if not groups:
            return
        handles = await asyncio.gather(
            *[adapter.with_echo(adapter.get_group_info)(group_id=g.id) for g in groups]
        )
        count = 0
        for echo, group in zip(await asyncio.gather(*[h[0] for h in handles]), groups):
            if echo.data is None:
                continue
            if echo.data["group_id"] == group.id:
                group.name = echo.data["group_name"]
                count += 1
        sess.add_all(groups)
        await sess.commit()
        logger.debug(f"fixed names of {count} groups")


get_session = recorder.get_session
run_sync = recorder.run_sync
to_async = recorder.to_async

RecorderPlugin = PluginPlanner(
    "0.1.0",
    funcs=[
        get_session,
        url_to_fileid,
        get_filepath,
        get_context_messages,
        run_sync,
        to_async,
    ],
)
bot = get_bot()


# TODO: 占用空间超过指定大小自动删除距上次使用时间最长的文件


@bot.on_started
async def _():
    await recorder.startup()


@bot.on_loaded
async def update_myself(adapter: Adapter):
    await recorder.started.wait()
    login = await (await adapter.with_echo(adapter.get_login_info)())[0]
    if login.data is None:
        logger.warning("Failed to get login info")
        return
    myid = login.data["user_id"]
    myname = login.data["nickname"]
    async with recorder.get_session() as sess:
        me = (await sess.exec(select(User).where(User.id == myid))).one_or_none()
        if me is None:
            me = User(id=myid, name=myname)
            sess.add(me)
        elif me.name != myname:
            me.name = myname
        await sess.commit()
    logger.info(f"My name is {myname}, now recording!")


@bot.on_loaded
async def delete_failed():
    await recorder.started.wait()
    async with recorder.get_session() as sess:
        images = (
            await sess.exec(
                select(MediaFile).where(
                    or_(
                        col(MediaFile.hash).is_(None),
                        col(MediaFile.path).is_(None),
                    )
                )
            )
        ).all()
        if images:
            for i in images:
                await sess.delete(i)
            await sess.commit()
            logger.debug(f"deleted {len(images)} failed images left from last launch")


@RecorderPlugin.use
@on_message()
async def do_record(event: MessageEvent, adapter: Adapter):
    await recorder.started.wait()
    async with recorder.get_session() as sess:
        user = await ensure_user(sess, event.sender.user_id, event.sender.nickname)
        params = {
            "message_id": event.message_id,
            "timestamp": event.time,
            "sender": user,
            "sender_id": event.sender.user_id,
            "message_type": "group",
        }
        if isinstance(event, GroupMessageEvent):
            params["group"] = await ensure_group(sess, event.group_id)
            params["group_id"] = event.group_id
        elif isinstance(event, PrivateMessageEvent):
            params["receiver"] = await ensure_user(sess, event.self_id)
            params["receiver_id"] = event.self_id
            params["message_type"] = "private"
        message = Message(**params)
        sess.add(message)

        urls_to_fetch: list[URL] = []
        segments = []
        objs_to_add = []
        for i, seg in enumerate(event.message):
            if isinstance(seg, ImageSegment):
                url = URL(str(seg.data["url"]))
                await ensure_mediafile(sess, url_to_fileid(url))
                urls_to_fetch.append(url)
            elif isinstance(seg, RecordSegment):
                pass
                # TODO: 处理语音消息段
            dicted = seg.to_dict()
            dbseg = MessageSegment(
                order=i,
                type=seg.type,
                data=dicted["data"],
                message_store_id=message.store_id,
            )
            segments.append(dbseg)
            objs_to_add.append(dbseg)
        objs_to_add.append(message)
        sess.add_all(objs_to_add)
        (await message.awaitable_attrs.segments).extend(segments)
        await sess.commit()
        count = (
            await sess.exec(
                select(func.count()).select_from(Message)  # pylint: disable=E1102
            )
        ).one()
        logger.debug(f"Recorded new, now exists {count} msgs in db")
    await asyncio.gather(*[handle_mediafile(u) for u in urls_to_fetch])
    await fix_group_name(adapter)
