import calendar
import time
import uuid
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path

from lemony_images import FontCache, get_default_font_cache
from lemony_storage_helper.database.sqlite import SqliteDatabaseHelper
from lemony_utils.time import get_time_period_start
from PIL import Image, ImageDraw, ImageOps
from sqlmodel import Field, Session, select
from uuid_utils.compat import uuid7

DeerBase, _, deer_metadata = SqliteDatabaseHelper.new_base(
    "DeerBase",
)


class DeerRecord(DeerBase, table=True):
    __tablename__ = "deer_record"

    id: uuid.UUID = Field(primary_key=True, default_factory=uuid7)
    timestamp: float = Field(index=True)
    user_id: int = Field(index=True)
    group_id: int = Field(index=True)
    combo: int = Field(default=1)


DBPPATH = "record/deers.db"
deerdbcore = SqliteDatabaseHelper(DBPPATH, metadata=deer_metadata)


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


ValidImageInput = BytesIO | str | Path | Image.Image


def _to_image(pic: ValidImageInput):
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
        font: FontCache | None = None,
    ):
        self._font = font if font else get_default_font_cache()

    def draw(
        self,
        deer_pic: ValidImageInput,
        correct_sign: ValidImageInput,
        *,
        records: list[tuple[float, int]],
        year: int,
        month: int,
        user_name: str,
        user_avatar: ValidImageInput | None = None,
    ):
        deer_bg = Image.new("RGBA", self.GRID_SIZE, color=self.BG_COLOR)
        deer_bg.paste(ImageOps.contain(_to_image(deer_pic), self.GRID_SIZE))
        cs = Image.new("RGBA", self.GRID_SIZE, color=self.BG_COLOR)
        cs.paste(ImageOps.contain(_to_image(correct_sign), self.GRID_SIZE))
        deer_pic_ok = Image.alpha_composite(deer_bg, cs)

        mc = calendar.monthcalendar(year, month)
        user_avatar = Image.alpha_composite(
            Image.new(
                "RGBA", (self.MARGIN_INFO, self.MARGIN_INFO), color=self.BG_COLOR
            ),
            ImageOps.fit(
                (
                    _to_image(user_avatar)
                    if user_avatar
                    else _to_image(
                        "data/no_data.png"
                    )  # TODO: 从统一的资源管理器里拿, 别直接读相对路径, cwd 不一定是项目根
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
                    (deer_pic_ok if day in deer_count_map else deer_bg),
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
