import asyncio
import logging
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any

from yarl import URL

logger = logging.getLogger(__name__)


def get_mface_package_url(package_id: int):
    return f"https://i.gtimg.cn/club/item/parcel/0/{package_id}_android.json"


def get_mface_url(mface_id: str):
    return f"https://gxh.vip.qq.com/club/item/parcel/item/{mface_id[0:2]}/{mface_id}/raw300.gif"


def uid_to_avatar_url(uid: int) -> str:
    # return f"https://q1.qlogo.cn/g?b=qq&nk={uid}&s=640"
    return f"https://q.qlogo.cn/headimg_dl?dst_uin={uid}&spec=640&img_type=png"


def avatar_url_to_uid(url: str | URL) -> int | None:
    if isinstance(url, str):
        url = URL(url)
    if url.host not in ["q.qlogo.cn", "q1.qlogo.cn"]:
        return None
    uid = url.query.get("nk") or url.query.get("dst_uin")
    if uid and uid.isdigit():
        return int(uid)
    return None


@dataclass(frozen=True, slots=True)
class MemberInfo:
    group_id: int
    user_id: int
    nickname: str
    card: str
    role: str = "member"
    title: str = ""

    @property
    def display_name(self) -> str:
        """群名片优先, 其次昵称, 都为空时是 QQ 号"""
        return self.card.strip() or self.nickname.strip() or str(self.user_id)


@dataclass(frozen=True, slots=True)
class GroupInfo:
    group_id: int
    group_name: str
    member_count: int = 0


class _Entry:
    __slots__ = ("expires", "value")

    def __init__(self, value: Any, expires: float) -> None:
        self.value = value
        self.expires = expires


async def _call_action(action: Callable[[], Awaitable[Any]]) -> Any | None:
    """OneBot action 的通用取数: ``(await (await adapter.xxx(...)))[0].data``; 失败返回 None"""
    handles = await action()
    echo = (await handles)[0]
    if echo is None or not echo.is_ok() or echo.data is None:
        return None
    return echo.data


class QQInfoCache:
    """群成员 / 陌生人 / 群信息的内存缓存, 避免同一份信息被反复请求。

    - 命中按 ttl 过期; 查不到 (失败、超时、实现端回 failed) 也会缓存 negative_ttl,
      不让一个不存在的成员在短时间内被反复查。
    - 同一个 key 并发请求只发一次 action (single-flight)。
    - 每次 action 限时 timeout: melobot 不给回执等待设超时, 实现端不回时不能挂住调用方。
    - 条目数超过 max_entries 时淘汰最久未用的。

    头像不在这里, 见 ``botutils.AvatarCache`` (文件缓存)。
    方法都接收 adapter 而不是在构造时绑定, 因为模块导入时 bot 还没有起来。
    """

    def __init__(
        self,
        *,
        ttl: float = 600.0,
        negative_ttl: float = 60.0,
        timeout: float = 5.0,
        max_entries: int = 4096,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl = ttl
        self.negative_ttl = negative_ttl
        self.timeout = timeout
        self.max_entries = max_entries
        self._clock = clock
        self._entries: OrderedDict[tuple, _Entry] = OrderedDict()
        self._inflight: dict[tuple, asyncio.Task[Any]] = {}

    # --- 通用部分 ---

    def _get_fresh(self, key: tuple) -> tuple[bool, Any]:
        entry = self._entries.get(key)
        if entry is None:
            return False, None
        if entry.expires <= self._clock():
            del self._entries[key]
            return False, None
        self._entries.move_to_end(key)
        return True, entry.value

    def _put(self, key: tuple, value: Any) -> None:
        ttl = self.ttl if value is not None else self.negative_ttl
        self._entries[key] = _Entry(value, self._clock() + ttl)
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

    async def _fetch(self, key: tuple, loader: Callable[[], Awaitable[Any]]) -> Any:
        hit, value = self._get_fresh(key)
        if hit:
            return value
        task = self._inflight.get(key)
        if task is None:
            task = asyncio.ensure_future(self._load(key, loader))
            self._inflight[key] = task
            task.add_done_callback(lambda _t: self._inflight.pop(key, None))
        # shield: 一个调用方被取消不应连带取消其他等待同一 key 的调用方
        return await asyncio.shield(task)

    async def _load(self, key: tuple, loader: Callable[[], Awaitable[Any]]) -> Any:
        try:
            async with asyncio.timeout(self.timeout):
                value = await loader()
        except TimeoutError:
            logger.debug("查询 %s 超时", key)
            value = None
        except Exception:
            logger.debug("查询 %s 失败", key, exc_info=True)
            value = None
        self._put(key, value)
        return value

    def clear(self) -> None:
        self._entries.clear()

    # --- 群成员 ---

    async def member(
        self, adapter: Any, group_id: int, user_id: int
    ) -> MemberInfo | None:
        async def load() -> MemberInfo | None:
            data = await _call_action(
                lambda: adapter.get_group_member_info(group_id, user_id)
            )
            if data is None:
                return None
            return MemberInfo(
                group_id=group_id,
                user_id=user_id,
                nickname=str(data.get("nickname") or ""),
                card=str(data.get("card") or ""),
                role=str(data.get("role") or "member"),
                title=str(data.get("title") or ""),
            )

        return await self._fetch(("member", group_id, user_id), load)

    async def members(
        self,
        adapter: Any,
        group_id: int,
        user_ids: Iterable[int],
        *,
        limit: int | None = None,
    ) -> dict[int, MemberInfo]:
        """并发查一批成员, 查不到的不出现在结果里; limit 限制单次最多查多少个"""
        uids = sorted(set(user_ids))
        if limit is not None:
            uids = uids[:limit]
        found = await asyncio.gather(*(self.member(adapter, group_id, u) for u in uids))
        return {u: m for u, m in zip(uids, found, strict=True) if m is not None}

    def remember_member(
        self,
        group_id: int,
        user_id: int,
        *,
        nickname: str | None,
        card: str | None,
        role: str | None = None,
    ) -> None:
        """用事件里带的发送者信息更新缓存, 省掉一次查询 (消息事件的 sender 字段)"""
        if not (nickname or card):
            return
        self._put(
            ("member", group_id, user_id),
            MemberInfo(
                group_id=group_id,
                user_id=user_id,
                nickname=nickname or "",
                card=card or "",
                role=role or "member",
            ),
        )

    def invalidate_member(self, group_id: int, user_id: int) -> None:
        """成员改名片、退群等通知到来时调用"""
        self._entries.pop(("member", group_id, user_id), None)

    # --- 陌生人 / 群 ---

    async def stranger_nickname(self, adapter: Any, user_id: int) -> str | None:
        async def load() -> str | None:
            data = await _call_action(lambda: adapter.get_stranger_info(user_id))
            nickname = str((data or {}).get("nickname") or "").strip()
            return nickname or None

        return await self._fetch(("stranger", user_id), load)

    async def group(self, adapter: Any, group_id: int) -> GroupInfo | None:
        async def load() -> GroupInfo | None:
            data = await _call_action(lambda: adapter.get_group_info(group_id))
            if data is None:
                return None
            return GroupInfo(
                group_id=group_id,
                group_name=str(data.get("group_name") or ""),
                member_count=int(data.get("member_count") or 0),
            )

        return await self._fetch(("group", group_id), load)

    def invalidate_group(self, group_id: int) -> None:
        self._entries.pop(("group", group_id), None)


#: 进程内共享的实例
qq_info_cache = QQInfoCache()
