import asyncio
import hashlib
import mimetypes
import os
import posixpath
import time
from pathlib import Path

import aiofiles
from melobot import get_bot
from melobot.plugin import PluginPlanner
from melobot.log import get_logger
from melobot.protocols.onebot.v11.handle import on_message
from melobot.protocols.onebot.v11.adapter import Adapter
from melobot.protocols.onebot.v11.adapter.event import (
    MessageEvent,
    GroupMessageEvent,
    PrivateMessageEvent,
)
from melobot.protocols.onebot.v11.adapter.segment import ImageSegment
from yarl import URL
from sqlmodel import Session, create_engine, SQLModel, select, func, col, or_

from lemony_utils.templates import async_http
from lemony_utils.consts import http_headers
from recorder_models import User, Group, Message, MessageSegment, Image, TABLES


class Recorder:
    def __init__(self, dburl: str):
        self._engine = create_engine(dburl)
        SQLModel.metadata.create_all(self._engine, tables=TABLES)

    @property
    def session(self):
        return Session(self._engine)


DB_URL = "sqlite:///data/record/messages.db"
IMG_LOCATION = Path("data/record/images")
os.makedirs(IMG_LOCATION, exist_ok=True)

recorder = Recorder(DB_URL)
logger = get_logger()


def do_md5(d: bytes):
    return hashlib.md5(d).hexdigest()


def get_fileid(url: URL):
    if url.host == "multimedia.nt.qq.com.cn":
        return url.query["fileid"]
    elif url.host.endswith("qpic.cn"):
        return max(url.parts, key=len)
    # logger.warning(f"url {url} is not known url pattern")
    return str(url)


def get_filepath(fileid: str):
    with recorder.session as sess:
        file = sess.exec(select(Image).where(Image.fileid == fileid)).one_or_none()
        if file:
            return file.path
        else:
            return None


async def handle_image(url: str | URL):
    url = URL(url)  # .with_scheme("http")
    dest = IMG_LOCATION / time.strftime("%Y-%m", time.localtime())
    fileid = get_fileid(url)
    try:
        dest.mkdir(parents=True, exist_ok=True)
        async with async_http(url, "get", headers=http_headers) as resp:
            resp.raise_for_status()
            data = await resp.read()
            extension = mimetypes.guess_extension(resp.headers["Content-Type"])
        filename = (md5 := await asyncio.to_thread(do_md5, data)) + (
            extension if extension else ".jpg"
        )
        path = (dest / filename).as_posix()
    except Exception as e:
        logger.warning(f"Exception while fetching img: {e}")
    else:
        do_write = True
        logger.debug(f"Image(fileid={fileid!r}) download ok, now saving...")
        with recorder.session as sess:
            img = sess.exec(select(Image).where(Image.fileid == fileid)).one()
            former_imgs = sess.exec(
                select(Image)
                .where(Image.hash == md5)
                .order_by(col(Image.timestamp).desc())
            ).all()
            # 找到从前可能存在的有效图片路径
            former_existing_path = None
            missing_images: list[Image] = []
            for i in former_imgs:
                if i.path and (_ := Path(i.path)).exists():
                    former_existing_path = _.as_posix()
                else:
                    missing_images.append(i)

            if former_existing_path:
                path = Path(former_existing_path).as_posix()
                do_write = False
                logger.debug(
                    f"Former image record found as {path!r}, dont save new one"
                )
            if missing_images:
                for i in missing_images:
                    i.path = path
                sess.add_all(missing_images)
                logger.debug(
                    f"Refresh paths of {len(missing_images)} former images, cuz they are missing"
                )
            if do_write and posixpath.exists(path):
                logger.debug(f"Image already exists as {path!r}, dont write")
                do_write = False
            img.hash = md5
            img.path = path
            sess.add(img)
            sess.commit()
        if do_write:
            async with aiofiles.open(path, "wb+") as fp:
                await fp.write(data)
            logger.debug(f"Image(fileid={fileid!r}) saved as {path!r}")


def ensure_user(session: Session, uid: int, name: str | None = None):
    user = session.exec(select(User).where(User.id == uid)).one_or_none()
    if user is None:
        user = User(id=uid, name=name)
        session.add(user)
    return user


def ensure_group(session: Session, gid: int, name: str | None = None):
    group = session.exec(select(Group).where(Group.id == gid)).one_or_none()
    if group is None:
        group = Group(id=gid, name=name)
        session.add(group)
    return group


def ensure_image(session: Session, fileid: str):
    img = session.exec(select(Image).where(Image.fileid == fileid)).one_or_none()
    if img is None:
        img = Image(fileid=fileid)
        session.add(img)


async def fix_group_name(adapter: Adapter):
    with recorder.session as sess:
        groups = sess.exec(select(Group).where(col(Group.name).is_(None))).all()
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
        sess.commit()
        logger.debug(f"fixed names of {count} groups")


def get_session():
    return recorder.session


RecorderPlugin = PluginPlanner("0.1.0", funcs=[get_session, get_fileid, get_filepath])
bot = get_bot()


@bot.on_loaded
async def update_myself(adapter: Adapter):
    login = await (await adapter.with_echo(adapter.get_login_info)())[0]
    if login.data is None:
        logger.warning("Failed to get login info")
        return
    myid = login.data["user_id"]
    myname = login.data["nickname"]
    with recorder.session as sess:
        me = sess.exec(select(User).where(User.id == myid)).one_or_none()
        if me is None:
            me = User(id=myid, name=myname)
            sess.add(me)
        elif me.name != myname:
            me.name = myname
        sess.commit()
    logger.info(f"My name is {myname}, now recording!")


@bot.on_loaded
async def delete_failed():
    with recorder.session as sess:
        images = sess.exec(
            select(Image).where(
                or_(
                    col(Image.hash).is_(None),
                    col(Image.path).is_(None),
                )
            )
        ).all()
        if images:
            for i in images:
                sess.delete(i)
            sess.commit()
            logger.debug(f"deleted {len(images)} failed images left from last launch")


@RecorderPlugin.use
@on_message()
async def do_record(event: MessageEvent, adapter: Adapter):
    with recorder.session as sess:
        user = ensure_user(sess, event.sender.user_id, event.sender.nickname)
        params = {
            "message_id": event.message_id,
            "timestamp": event.time,
            "sender": user,
            "message_type": "group",
        }
        if isinstance(event, GroupMessageEvent):
            params["group"] = ensure_group(sess, event.group_id)
        elif isinstance(event, PrivateMessageEvent):
            params["receiver"] = ensure_user(sess, event.self_id)
            params["message_type"] = "private"
        message = Message(**params)
        sess.add(message)
        user.sent_messages.append(message)
        if params["message_type"] == "private":
            params["receiver"].received_messages.append(message)
        else:
            params["group"].messages.append(message)

        imgs_to_fetch: list[URL] = []
        for i, seg in enumerate(event.message):
            if isinstance(seg, ImageSegment):
                url = URL(str(seg.data["url"]))
                ensure_image(sess, get_fileid(url))
                imgs_to_fetch.append(url)
            dicted = seg.to_dict()
            message.segments.append(
                MessageSegment(order=i, type=seg.type, data=dicted["data"])
            )
        sess.add(message)
        sess.commit()
        count = sess.exec(
            select(func.count()).select_from(Message)  # pylint: disable=E1102
        ).one()
        logger.debug(f"Recorded new, now exists {count} msgs in db")
    await asyncio.gather(*[handle_image(u) for u in imgs_to_fetch])
    await fix_group_name(adapter)
