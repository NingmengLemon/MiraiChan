from contextlib import contextmanager
import functools
import random
import threading
import time
from typing import Type

from sqlmodel import create_engine, SQLModel, Session, select, or_, and_
from melobot.protocols.onebot.v11.adapter.echo import _GetGroupMemberInfoEchoData

from .models import DailyWaifuRel, MarriageRel

_UserSeq = list[_GetGroupMemberInfoEchoData] | list[int]

__all__ = (
    "WaifuManager",
    "RelExistsError",
    "RelNotExistsError",
)


class RelExistsError(Exception):
    pass


class RelNotExistsError(Exception):
    pass


class WaifuManager:
    def __init__(self, dburl: str):
        self._engine = create_engine(
            dburl,
            connect_args={"check_same_thread": False},
        )
        SQLModel.metadata.create_all(self._engine)
        self._mlock = threading.Lock()

    @contextmanager
    def _get_session(self):
        with Session(self._engine) as session, self._mlock as _:  # 死锁注意
            yield session

    def filter_waifuable[T: _UserSeq](self, gid: int, users: T) -> T:
        married = set[int]()
        with self._get_session() as sess:
            for e in sess.exec(select(MarriageRel).where(MarriageRel.gid == gid)).all():
                married.add(e.a)
                married.add(e.b)

        def filter_func(user: _GetGroupMemberInfoEchoData | int):
            if isinstance(user, dict):
                user = user["user_id"]
            return user not in married

        return list(filter(filter_func, users))

    def draw_waifu(self, gid: int, users: _UserSeq):
        waifuable = self.filter_waifuable(gid, users)
        if waifuable:
            waifu = random.choice(waifuable)
            return waifu
        return None

    def _select_dwr(self, gid: int, src: int | None, dst: int | None):
        where = []
        if src:
            where.append(DailyWaifuRel.src == src)
        if dst:
            where.append(DailyWaifuRel.dst == dst)
        return select(DailyWaifuRel).where(
            DailyWaifuRel.gid == gid,
            DailyWaifuRel.time < self.to_next_midnight(),
            *where,
        )

    def _select_mr(self, gid: int, a: int, b: int | None):
        where = (
            or_(
                and_(MarriageRel.a == a, MarriageRel.b == b),
                and_(MarriageRel.a == b, MarriageRel.b == a),
            )
            if b
            else or_(MarriageRel.a == a, MarriageRel.b == a)
        )
        return select(MarriageRel).where(
            where,
            MarriageRel.gid == gid,
        )

    def query_dwrels(self, gid: int, *, src: int | None, dst: int | None):
        with self._get_session() as sess:
            return sess.exec(self._select_dwr(gid, src, dst)).all()

    def query_mrels(self, gid: int, a: int, b: int | None):
        with self._get_session() as sess:
            return sess.exec(self._select_mr(gid, a, b)).all()

    def add_waifu_rel(self, gid: int, src: int, dst: int):
        with self._get_session() as sess:
            sess.add(DailyWaifuRel(src=src, dst=dst, gid=gid))
            sess.commit()

    def marry(self, gid: int, a: int, b: int):
        with self._get_session() as sess:
            if sess.exec(self._select_mr(gid, a, b)).one_or_none() is None:
                sess.add(MarriageRel(a=a, b=b, gid=gid))
                if (
                    er := sess.exec(self._select_dwr(gid, a, b)).one_or_none()
                ) is not None:
                    sess.delete(er)
                if (
                    er := sess.exec(self._select_dwr(gid, b, a)).one_or_none()
                ) is not None:
                    sess.delete(er)
                sess.commit()
            else:
                raise RelExistsError()

    def divorce(self, gid: int, a: int, b: int):
        with self._get_session() as sess:
            if (rel := sess.exec(self._select_mr(gid, a, b)).one_or_none()) is None:
                raise RelNotExistsError()
            else:
                sess.delete(rel)
                sess.commit()

    @staticmethod
    def _dump_table(session: Session, table: Type[SQLModel], gid: int | None = None):
        sel = select(table)
        if gid:
            sel = sel.where(table.gid == gid)
        return [i.model_dump() for i in session.exec(sel).all()]

    def dump(self, gid: int | None = None):
        with self._get_session() as sess:
            return (
                self._dump_table(sess, DailyWaifuRel, gid),
                self._dump_table(sess, MarriageRel, gid),
            )

    def clear_expired_dwr(self):
        with self._get_session() as sess:
            todelete = sess.exec(
                select(DailyWaifuRel).where(
                    DailyWaifuRel.time < self.to_next_midnight()
                )
            ).all()
            for r in todelete:
                sess.delete(r)
            sess.commit()

    @classmethod
    def to_next_midnight(cls, ts: float | None = None):
        ts = time.time() if ts is None else ts
        return cls.to_midnight(ts + 60 * 60 * 24)

    @staticmethod
    def to_midnight(ts: float | None = None):
        ts = time.time() if ts is None else ts
        nd = [*time.localtime(ts)]
        nd[3], nd[4], nd[5] = [0] * 3
        return time.mktime(tuple(nd))
