import calendar
import time
import uuid
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path

from lemony_images.core import (
    FontCache,
    default_font_cache,
)
from lemony_storage_helper.database import DatabaseHelper, SQLModel, registry
from lemony_utils.time import get_time_period_start
from lemony_utils.uuid7 import uuid7
from PIL import Image, ImageDraw, ImageOps
from sqlalchemy import URL
from sqlmodel import Field, Session, select

deerdb_registry = registry()


class DeerBase(SQLModel, registry=deerdb_registry):
    pass


class DeerRecord(DeerBase, table=True):
    __tablename__ = "deer_record"

    id: uuid.UUID = Field(primary_key=True, default_factory=uuid7)
    timestamp: float = Field(index=True)
    user_id: int = Field(index=True)
    group_id: int = Field(index=True)
    combo: int = Field(default=1)


DBPPATH = "data/record/deers.db"
dburl = URL.create(
    "sqlite+aiosqlite",
    database=DBPPATH,
)
deerdbcore = DatabaseHelper(dburl, deerdb_registry.metadata)


@deerdbcore.to_async
def query(
    session: Session,
    uid: int,
    gid: int | None = None,
    time_range: tuple[float, float] | None = None,
):
    now_time = time.time()
    if time_range is None:
        time_range = (get_time_period_start("month", now_time).timestamp(), now_time)
    query_stmt = select(
        DeerRecord.timestamp,
        DeerRecord.combo,
    ).where(
        DeerRecord.timestamp >= time_range[0],
        DeerRecord.timestamp <= time_range[1],
        DeerRecord.user_id == uid,
    )
    if gid is not None:
        query_stmt = query_stmt.where(DeerRecord.group_id == gid)
    return list(session.exec(query_stmt).all())


async def query_one_day_total(date: datetime, uid: int, gid: int | None = None):
    start = get_time_period_start("day", date)
    end = start + timedelta(days=1)
    return sum(
        i[1]
        for i in await query(
            uid=uid, gid=gid, time_range=(start.timestamp(), end.timestamp())
        )
    )


@deerdbcore.to_async
def record(
    session: Session, uid: int, gid: int, combo: int = 1, ts: float | None = None
) -> None:
    ts = time.time() if ts is None else ts
    session.add(DeerRecord(timestamp=ts, user_id=uid, group_id=gid, combo=combo))
    session.commit()


_ValidImageInput = BytesIO | str | Path | Image.Image


def _to_image(pic: _ValidImageInput):
    return (
        pic.convert("RGBA")
        if isinstance(pic, Image.Image)
        else Image.open(pic).convert("RGBA")
    )


class Painter:
    GRID_SIZE = (128, 128)
    MARGIN = 20
    MARGIN_INFO = 96
    BG_COLOR = "#ffffffff"
    GRAY = "#5a6165ff"
    FONT_SIZE = 42
    FONT_SIZE_SMALL = 24

    def __init__(
        self,
        deer_pic: _ValidImageInput,
        correct_sign: _ValidImageInput,
        font: FontCache | None = None,
    ):
        bg = Image.new("RGBA", self.GRID_SIZE, color=self.BG_COLOR)
        self._deer_pic = bg.copy()
        self._deer_pic.paste(ImageOps.contain(_to_image(deer_pic), self.GRID_SIZE))
        cs = bg.copy()
        cs.paste(ImageOps.contain(_to_image(correct_sign), self.GRID_SIZE))
        self._deer_pic_ok = Image.alpha_composite(self._deer_pic, cs)
        self._font = font if font else default_font_cache

    def draw(
        self,
        records: list[tuple[float, int]],
        year: int,
        month: int,
        user_name: str,
        user_avatar: _ValidImageInput | None = None,
    ):
        mc = calendar.monthcalendar(year, month)
        user_avatar = Image.alpha_composite(
            Image.new(
                "RGBA", (self.MARGIN_INFO, self.MARGIN_INFO), color=self.BG_COLOR
            ),
            ImageOps.fit(
                (
                    _to_image(user_avatar)
                    if user_avatar
                    else _to_image("data/no_data.png")
                ),
                (self.MARGIN_INFO, self.MARGIN_INFO),
            ),
        )

        deer_count_map: dict[int, int] = {}
        for ts, combo in records:
            t = time.localtime(ts)
            if (t.tm_year, t.tm_mon) != (year, month):
                continue
            if t.tm_mday not in deer_count_map:
                deer_count_map[t.tm_mday] = 0
            deer_count_map[t.tm_mday] += combo

        canvas = Image.new(
            "RGBA",
            (
                7 * self.GRID_SIZE[0] + self.MARGIN * 2,
                len(mc) * self.GRID_SIZE[1] + self.MARGIN * 3 + self.MARGIN_INFO,
            ),
            color=self.BG_COLOR,
        )
        draw = ImageDraw.Draw(canvas)
        canvas.paste(user_avatar, (self.MARGIN, self.MARGIN))
        draw.text(
            (self.MARGIN * 2 + self.MARGIN_INFO, self.MARGIN),
            f"{year}-{month} 签到日历",
            "#000000ff",
            font=self._font.use(self.FONT_SIZE),
        )
        if user_name:
            draw.text(
                (self.MARGIN * 2 + self.MARGIN_INFO, self.MARGIN + self.MARGIN_INFO),
                f"{user_name}",
                self.GRAY,
                font=self._font.use(self.FONT_SIZE_SMALL),
                anchor="ld",
            )
        coor_map: dict[int, tuple[int, int]] = {}
        for i, week in enumerate(mc):
            for j, day in enumerate(week):
                if day == 0:
                    continue
                coor_map[day] = (
                    x := int((self.MARGIN + j * self.GRID_SIZE[0])),
                    y := int(
                        (self.MARGIN * 2 + self.MARGIN_INFO + i * self.GRID_SIZE[1])
                    ),
                )
                canvas.paste(
                    (self._deer_pic_ok if day in deer_count_map else self._deer_pic),
                    (x, y),
                )
                draw.text(
                    (x, y + self.GRID_SIZE[1]),
                    text=str(day),
                    fill="#000000ff",
                    font=self._font.use(self.FONT_SIZE),
                    anchor="ls",
                )
        for day, count in deer_count_map.items():
            if count <= 1:
                continue
            x, y = coor_map[day]
            draw.text(
                (x + self.GRID_SIZE[0], y + self.GRID_SIZE[1] - self.MARGIN),
                f"x{count}",
                font=self._font.use(self.FONT_SIZE_SMALL),
                fill="#ff0000ff",
                anchor="rs",
            )
        result = BytesIO()
        canvas.save(result, "png")
        return result
