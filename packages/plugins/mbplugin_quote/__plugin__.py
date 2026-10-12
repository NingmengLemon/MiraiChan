"""引用图: ``.q`` 名言卡片, ``.mq`` 聊天记录。只在群聊里响应。

这里只做: 配置与资源初始化、权限、冷却、把事件翻译成 pipeline 的调用、发送与存档。
"""

import asyncio
import logging
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

from lemony_checkers import get_checker_factory
from lemony_checkers.core import check_command_permission
from lemony_images import bytes_to_b64_url
from lemony_mface import MFaceBlocklist
from lemony_onebot_utils.botutils import cached_avatar_source
from lemony_settings import require
from lemony_storage_helper.database import StorageStartupError
from lemony_storage_helper.database.sqlite import (
    SqliteDatabaseHelper,
    get_relative_path_base,
)
from melobot import PluginPlanner, get_bot
from melobot.handle import on_command
from melobot.protocols.onebot.v11 import Adapter, GroupMessageEvent
from melobot.protocols.onebot.v11.adapter.segment import ImageSegment, ReplySegment
from melobot.utils.parse import CmdArgs
from PIL import Image, ImageFont

from .archive import ArchiveRecord, QuoteArchive, quote_metadata
from .cooldown import Cooldown
from .model import SourceMessage
from .pipeline import (
    Assets,
    NothingToQuote,
    Rendered,
    encode,
    render_card_quote,
    render_chat_quote,
)
from .render import CanvasTooLarge
from .request import (
    ChatRequest,
    QuoteRequestError,
    check_limits,
    parse_chat_args,
)
from .resources import FetchLimits, ResourceResolver
from .settings import QuoteSettings
from .sources import fetch_messages, source_from_onebot

PLUGIN_IDENTIFIER = "quote"
DATABASE_PATH = "quote/quote.db"
ARCHIVE_DIR = "quote/artifacts"
RESOURCE_DIR = Path(__file__).parent / "resources"

logger = logging.getLogger(__name__)
bot = get_bot()
plugin = PluginPlanner("2.0.0")
cfgloader = require(model=QuoteSettings, identifier=PLUGIN_IDENTIFIER, auto_load=False)
quote_db = SqliteDatabaseHelper(DATABASE_PATH, metadata=quote_metadata)


class _State:
    """on_ready 里建好的运行期对象; 初始化失败时 ready 为 False, handler 直接放弃"""

    ready = False
    settings: QuoteSettings
    assets: Assets
    resolver: ResourceResolver
    archive: QuoteArchive
    executor: ThreadPoolExecutor
    pending: asyncio.Semaphore
    target_cd: Cooldown
    user_cd: Cooldown
    blocklist: MFaceBlocklist
    inflight: set[tuple]


state = _State()
_init_done = asyncio.Event()


def _data_root() -> Path:
    base = get_relative_path_base()
    if base is None:
        raise RuntimeError("storage relative path base is not set")
    return base


def _load_assets(font_path: Path) -> Assets:
    @lru_cache(maxsize=64)
    def fonts(size: int) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(str(font_path), size)

    with Image.open(RESOURCE_DIR / "card_mask.png") as mask_img:
        mask = mask_img.convert("RGBA")
    with Image.open(RESOURCE_DIR / "placeholder.png") as ph_img:
        placeholder = ph_img.convert("RGBA")
    fonts(28)  # 字体文件不存在时在这里就报错
    return Assets(fonts=fonts, mask=mask, placeholder=placeholder)


@plugin.on_ready
async def _() -> None:
    # melobot 会吞掉 hook 的异常, 失败时只记日志, 让 handler 放弃
    try:
        await cfgloader.load_async()
        cfg = cfgloader.value
        data_root = _data_root()
        state.settings = cfg
        state.assets = await asyncio.to_thread(_load_assets, data_root / cfg.font)
        state.resolver = ResourceResolver(
            data_root=data_root,
            avatar_source=cached_avatar_source.get,
            emoji_cdn=cfg.emoji_cdn,
            limits=FetchLimits(
                timeout=cfg.limits.fetch_timeout,
                max_bytes=cfg.limits.max_image_bytes,
            ),
        )
        await quote_db.startup()
        state.archive = QuoteArchive(quote_db, data_root / ARCHIVE_DIR)
        state.executor = ThreadPoolExecutor(
            max_workers=cfg.limits.render_workers, thread_name_prefix="quote-render"
        )
        state.pending = asyncio.Semaphore(cfg.limits.max_pending)
        state.target_cd = Cooldown(cfg.limits.same_target_cooldown)
        state.user_cd = Cooldown(cfg.limits.user_cooldown)
        state.blocklist = MFaceBlocklist(cfg.chat.banned_sticker_sets)
        state.inflight = set()
        state.ready = True
    except Exception:
        logger.exception("quote 插件初始化失败, 插件将不响应")
    finally:
        _init_done.set()


@bot.on_stopped
async def _() -> None:
    if not state.ready:
        return
    state.ready = False
    await state.resolver.close()
    state.executor.shutdown(wait=False, cancel_futures=True)
    await quote_db.close()


def _allowed(event: GroupMessageEvent, command: str) -> bool:
    factory = get_checker_factory()
    user = factory.extract_user(event)
    return user is not None and check_command_permission(
        global_settings=factory.global_settings,
        plugin_settings=factory.get_plugin_settings(PLUGIN_IDENTIFIER),
        user=user,
        command_name=command,
    )


def _is_bot_admin(event: GroupMessageEvent) -> bool:
    factory = get_checker_factory()
    user = factory.extract_user(event)
    return user is not None and (factory.is_owner(user) or factory.is_admin(user))


def _reply_target(event: GroupMessageEvent) -> str | None:
    replies = event.get_segments(ReplySegment)
    if not replies:
        return None
    return str(replies[0].data["id"])


async def _get_msg(adapter: Adapter, message_id: str) -> SourceMessage | None:
    try:
        echo = (await (await adapter.get_msg(int(message_id))))[0]
    except Exception:
        logger.debug("get_msg %s 失败", message_id, exc_info=True)
        return None
    if echo is None or not echo.is_ok() or echo.data is None:
        return None
    data = echo.data
    sender = data["sender"]
    return source_from_onebot(
        message_id=message_id,
        sender_id=int(sender.user_id or 0),
        card=getattr(sender, "card", None),
        nickname=sender.nickname,
        # 用 raw 保留实现端的扩展字段 (例如 SnowLuma 的商城表情标记)
        segments=[getattr(s, "raw", s.to_dict()) for s in data["message"]],
    )


def _recorder():
    try:
        share = bot.get_share("mbplugin_recorder", "recorder_service")
    except Exception:
        return None
    return share.get()


def _window_query(event: GroupMessageEvent):
    def make(req: ChatRequest, base_id: str):
        from mbplugin_recorder.db.views import MessageWindowQuery

        return MessageWindowQuery(
            account_protocol=str(event.protocol),
            account_self_id=str(event.self_id),
            conversation_type="group",
            conversation_external_id=str(event.group_id),
            base_external_message_id=base_id,
            start=req.start,
            end=req.end,
            sender_only=req.sender_only,
            # 默认不引用 bot 自己: bot 的消息不进窗口, 偏移也不数它们
            exclude_sender_external_ids=(
                () if state.settings.allow_quote_self else (str(event.self_id),)
            ),
        )

    return make


async def _gate(
    event: GroupMessageEvent, adapter: Adapter, command: str, target_key: tuple
) -> bool:
    """初始化、权限、冷却、在途去重; 通过时登记冷却与在途"""
    await _init_done.wait()
    if not state.ready or not _allowed(event, command):
        return False
    if _is_bot_admin(event):
        state.inflight.add(target_key)
        return True
    if target_key in state.inflight:
        await adapter.send_reply("这条正在生成, 稍等一下")
        return False
    if (left := state.target_cd.remaining(target_key)) > 0:
        await adapter.send_reply(f"这条刚引用过, {int(left) + 1} 秒后再试")
        return False
    user_key = (event.group_id, event.user_id)
    if (left := state.user_cd.remaining(user_key)) > 0:
        await adapter.send_reply(f"太快了, {int(left) + 1} 秒后再试")
        return False
    state.inflight.add(target_key)
    state.target_cd.touch(target_key)
    state.user_cd.touch(user_key)
    return True


async def _deliver(
    event: GroupMessageEvent,
    adapter: Adapter,
    rendered: Rendered,
    record: ArchiveRecord,
) -> None:
    cfg = state.settings.archive
    data, ext = await asyncio.get_running_loop().run_in_executor(
        state.executor, encode, rendered.image, cfg.format, cfg.quality
    )
    handles = await adapter.send_reply(ImageSegment(file=bytes_to_b64_url(data)))
    if state.settings.show_timing:
        t = rendered.timings
        await adapter.send_reply(
            f"fetch {t.get('fetch', 0):.2f}s, draw {t.get('draw', 0):.2f}s"
        )
    try:
        artifact = await state.archive.save(record, data, ext)
    except StorageStartupError:
        return
    except Exception:
        logger.exception("引用图存档失败")
        return
    try:
        echo = (await handles)[0]
        if echo is not None and echo.data is not None:
            await state.archive.attach_sent_message(
                artifact.id, str(echo.data["message_id"])
            )
    except Exception:
        logger.debug("记录发送消息 id 失败", exc_info=True)


def _record(
    event: GroupMessageEvent,
    style: str,
    base_id: str,
    req: ChatRequest,
    rendered: Rendered,
) -> ArchiveRecord:
    return ArchiveRecord(
        style=style,
        group_id=event.group_id,
        requester_id=event.user_id,
        base_message_id=base_id,
        range_start=req.start,
        range_end=req.end,
        sender_only=req.sender_only,
        scale=req.scale,
        sender_ids=sorted({m.sender_id for m in rendered.messages}),
        width=rendered.image.width,
        height=rendered.image.height,
    )


def _drop_self(
    event: GroupMessageEvent, sources: Sequence[SourceMessage]
) -> list[SourceMessage]:
    """默认把 bot 自己的消息当作不存在 (不画、不报错)"""
    if state.settings.allow_quote_self:
        return list(sources)
    return [m for m in sources if m.sender_id != event.self_id]


def _base_is_self(event: GroupMessageEvent, base_sender: int | None) -> bool:
    return not state.settings.allow_quote_self and base_sender == event.self_id


class _MsgCache:
    """一次请求内对同一条消息只调一次 get_msg"""

    def __init__(self, adapter: Adapter) -> None:
        self._adapter = adapter
        self._cache: dict[str, SourceMessage | None] = {}

    async def get(self, message_id: str) -> SourceMessage | None:
        if message_id not in self._cache:
            self._cache[message_id] = await _get_msg(self._adapter, message_id)
        return self._cache[message_id]

    async def sender_of(self, message_id: str) -> int | None:
        one = await self.get(message_id)
        return one.sender_id if one is not None else None


def _release(event: GroupMessageEvent, target_key: tuple) -> None:
    """请求被静默放弃时撤销这次登记的冷却"""
    state.target_cd.clear(target_key)
    state.user_cd.clear((event.group_id, event.user_id))


@plugin.use
@on_command(".", " ", ["q", "quote"])
async def quote_card(event: GroupMessageEvent, adapter: Adapter) -> None:
    if not isinstance(event, GroupMessageEvent):
        return
    base_id = _reply_target(event)
    target_key = (event.group_id, base_id, "card")
    if base_id is None:
        if await _gate_permission_only(event, "card"):
            await adapter.send_reply("回复一条消息来引用它")
        return
    if not await _gate(event, adapter, "card", target_key):
        return
    try:
        msgs = _MsgCache(adapter)
        async with state.pending:
            result = await fetch_messages(
                ChatRequest(),
                base_id,
                recorder=_recorder(),
                make_query=_window_query(event),
                fetch_one=msgs.get,
            )
            sources = _drop_self(event, result.messages if result else ())
            if not sources:
                if _base_is_self(event, await msgs.sender_of(base_id)):
                    _release(event, target_key)
                    return
                await adapter.send_reply("取不到这条消息")
                return
            source = sources[0]
            rendered = await render_card_quote(
                source,
                resolver=state.resolver,
                assets=state.assets,
                executor=state.executor,
            )
            await _deliver(
                event,
                adapter,
                rendered,
                _record(event, "card", base_id, ChatRequest(), rendered),
            )
    except NothingToQuote as e:
        await adapter.send_reply(str(e))
    except Exception:
        logger.exception("生成卡片引用图失败: group=%s msg=%s", event.group_id, base_id)
        await adapter.send_reply("生成失败了")
    finally:
        state.inflight.discard(target_key)


async def _gate_permission_only(event: GroupMessageEvent, command: str) -> bool:
    await _init_done.wait()
    return state.ready and _allowed(event, command)


@plugin.use
@on_command(".", " ", ["mq", "momoquote"])
async def quote_chat(event: GroupMessageEvent, adapter: Adapter, args: CmdArgs) -> None:
    if not isinstance(event, GroupMessageEvent):
        return
    base_id = _reply_target(event)
    if base_id is None:
        if await _gate_permission_only(event, "chat"):
            await adapter.send_reply(
                "回复一条消息来引用它, 可选参数: 区间 x..y (例如 -3..2), 仅本人 -s, 倍率 2x"
            )
        return
    # 参数错误与超限在登记冷却之前处理, 写错参数不消耗冷却
    if not await _gate_permission_only(event, "chat"):
        return
    try:
        req = parse_chat_args([str(v) for v in args.vals])
        if not _is_bot_admin(event):
            check_limits(
                req,
                max_offset=state.settings.chat.max_offset,
                max_scale=state.settings.chat.max_scale,
            )
    except QuoteRequestError as e:
        await adapter.send_reply(str(e))
        return
    target_key = (event.group_id, base_id, "chat", req)
    if not await _gate(event, adapter, "chat", target_key):
        return
    try:
        msgs = _MsgCache(adapter)
        async with state.pending:
            result = await fetch_messages(
                req,
                base_id,
                recorder=_recorder(),
                make_query=_window_query(event),
                fetch_one=msgs.get,
            )
            sources = _drop_self(event, result.messages if result else ())
            if not sources:
                if _base_is_self(event, await msgs.sender_of(base_id)):
                    _release(event, target_key)
                    return
                if result is None:
                    msg = "取不到这条消息"
                elif result.degraded_to_single:
                    msg = "记录里没有这条消息的上下文"
                else:
                    msg = "区间内没有消息"
                await adapter.send_reply(msg)
                return
            if result is not None and result.degraded_to_single:
                await adapter.send_reply("记录里没有这条消息的上下文, 只能引用它本身")
            rendered = await render_chat_quote(
                sources,
                blocklist=state.blocklist,
                scale=req.scale,
                max_pixels=state.settings.chat.max_canvas_pixels,
                resolver=state.resolver,
                assets=state.assets,
                executor=state.executor,
            )
            await _deliver(
                event, adapter, rendered, _record(event, "chat", base_id, req, rendered)
            )
    except CanvasTooLarge:
        await adapter.send_reply("图太大了, 少引用几条或者把倍率调小")
    except NothingToQuote as e:
        await adapter.send_reply(str(e))
    except Exception:
        logger.exception(
            "生成聊天引用图失败: group=%s msg=%s req=%s", event.group_id, base_id, req
        )
        await adapter.send_reply("生成失败了")
    finally:
        state.inflight.discard(target_key)


@plugin.use
@on_command(".", " ", ["qdel"])
async def delete_archive(event: GroupMessageEvent, adapter: Adapter) -> None:
    """bot 管理员回复 bot 发出的引用图, 删除对应的存档"""
    if not isinstance(event, GroupMessageEvent):
        return
    await _init_done.wait()
    if not state.ready or not _is_bot_admin(event):
        return
    target = _reply_target(event)
    if target is None:
        await adapter.send_reply("回复一张 bot 发出的引用图来删除它的存档")
        return
    try:
        artifact = await state.archive.find_by_sent_message(target)
        # 只能删本群的存档
        if artifact is None or artifact.group_id != event.group_id:
            await adapter.send_reply("这条消息没有对应的存档")
            return
        await state.archive.delete(artifact.id)
    except Exception:
        logger.exception("删除引用图存档失败: group=%s msg=%s", event.group_id, target)
        await adapter.send_reply("删除失败了")
        return
    logger.info(
        "已删除引用图存档 %s (group=%s, by=%s)",
        artifact.id,
        event.group_id,
        event.user_id,
    )
    await adapter.send_reply("已删除存档")
