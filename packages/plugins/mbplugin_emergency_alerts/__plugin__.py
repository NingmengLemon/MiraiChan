"""地震信息订阅推送: 接入 Wolfx WebSocket, 按会话订阅筛选后推送到群聊或私聊.

指令: ``.预警`` (查看用法). 群里修改订阅需要群管理员或 bot 管理员, 私聊里本人即可.
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta

from lemony_checkers import get_checker_factory
from lemony_settings import require
from lemony_storage_helper.database.sqlite import SqliteDatabaseHelper
from lemony_utils.help import Command, register_help
from melobot import PluginInfo, PluginPlanner, get_bot
from melobot.handle import on_command
from melobot.protocols.onebot.v11 import Adapter, GroupMessageEvent, MessageEvent
from melobot.utils.parse import CmdArgs

from .archive import AlertArchive, DeliveryResult, alerts_metadata
from .client import WolfxClient
from .commands import HELP_COMMANDS, CommandError, execute
from .dispatch import RETENTION, Dispatcher
from .quake import Quake
from .render import render_quake, render_test
from .settings import AlertSettings
from .subscription import Subscription, SubscriptionStore, TargetKey

PLUGIN_IDENTIFIER = "emergency_alerts"
DATABASE_PATH = "emergency_alerts/alerts.db"

logger = logging.getLogger(__name__)
bot = get_bot()
plugin = PluginPlanner(
    "0.2.0",
    info=PluginInfo(desc="地震预警 / 地震速报订阅推送 (数据来自 Wolfx)"),
)
cfgloader = require(model=AlertSettings, identifier=PLUGIN_IDENTIFIER, auto_load=False)
storeloader = require(
    model=SubscriptionStore,
    identifier=PLUGIN_IDENTIFIER,
    namespace="subscriptions",
    auto_load=False,
)
alerts_db = SqliteDatabaseHelper(DATABASE_PATH, metadata=alerts_metadata)
archive = AlertArchive(alerts_db)

register_help(
    PLUGIN_IDENTIFIER,
    title="地震预警",
    summary="按会话订阅地震预警与速报 (数据来自 Wolfx), 群里修改订阅需要群管理员或 bot 管理员",
    aliases=["预警", "eew"],
    commands=[Command(usage, desc) for usage, desc in HELP_COMMANDS],
)


class _State:
    """on_ready 里建好的运行期对象; 初始化失败时 ready 为 False, handler 直接放弃"""

    ready = False
    client: WolfxClient
    dispatcher: Dispatcher
    #: 订阅的读改写与推送时的读取互斥, 保证保存到文件的是完整状态
    lock: asyncio.Lock
    #: 留档库是否可用; 不可用时照常推送, 只是不留档, 重启后去重状态丢失
    archive_ok = False


state = _State()
_init_done = asyncio.Event()


@plugin.on_ready
async def _() -> None:
    # melobot 会吞掉 hook 的异常, 失败时只记日志, 让 handler 放弃
    try:
        await cfgloader.load_async()
        await storeloader.load_async()
        cfg = cfgloader.value
        state.lock = asyncio.Lock()
        state.dispatcher = Dispatcher(
            max_age={
                "eew": timedelta(minutes=cfg.eew_max_age_minutes),
                "report": timedelta(minutes=cfg.report_max_age_minutes),
            }
        )
        await _start_archive()
        state.client = WolfxClient(
            cfg.ws_base_url, cfg.endpoints, _on_quake, idle_timeout=cfg.idle_timeout
        )
        state.client.start()
        state.ready = True
        logger.info(
            f"预警插件已启动: {cfg.ws_base_url} {cfg.endpoints}, "
            f"{len(storeloader.value.subscriptions)} 个订阅"
        )
    except Exception:
        logger.exception("预警插件初始化失败, 插件将不响应")
    finally:
        _init_done.set()


async def _start_archive() -> None:
    """启动留档库并恢复去重状态; 失败只降级为不留档, 不阻止推送"""
    try:
        await alerts_db.startup()
        since = datetime.now(UTC) - RETENTION
        for key, at in await archive.recent_report_keys(since):
            state.dispatcher.restore_seen(key, at)
        restored = await archive.recent_deliveries(since)
        for d in restored:
            state.dispatcher.restore_pushed(
                d.target, d.event_key, seq=d.seq, final=d.final, at=d.at
            )
        state.archive_ok = True
        logger.info(f"预警留档已启动, 恢复了 {len(restored)} 条推送记录")
    except Exception:
        logger.exception("预警留档库启动失败, 将不留档, 重启后可能重复推送")


@bot.on_stopped
async def _() -> None:
    if state.ready:
        await state.client.stop()
    if alerts_db.is_initialized():
        await alerts_db.close()


async def _send(adapter: Adapter, target: TargetKey, text: str) -> DeliveryResult:
    kind, tid = target
    try:
        if kind == "group":
            handles = await adapter.send_custom(text, group_id=tid)
        else:
            handles = await adapter.send_custom(text, user_id=tid)
        echo = await handles[0]
    except Exception as e:
        logger.exception(f"推送到 {kind}:{tid} 失败")
        return DeliveryResult(target, ok=False, error=repr(e))
    if echo is None or not echo.is_ok():
        logger.warning(f"推送到 {kind}:{tid} 失败: {echo!r}")
        return DeliveryResult(target, ok=False, error=repr(echo))
    return DeliveryResult(target, ok=True)


async def _archive_report(quake: Quake, raw: str) -> uuid.UUID | None:
    """留档一报; 留档不可用或失败时返回 None, 不影响推送"""
    if not state.archive_ok:
        return None
    try:
        return await archive.record_report(quake, raw)
    except Exception:
        logger.exception(f"留档 {quake.source} {quake.event_id}#{quake.seq} 失败")
        return None


async def _on_quake(quake: Quake, raw: str) -> None:
    # 每一报都留档 (含不推送的、训练报、过期报), 重复报文由唯一约束挡掉
    report_id = await _archive_report(quake, raw)
    async with state.lock:
        subs: list[Subscription] = state.dispatcher.select(
            quake, list(storeloader.value.subscriptions)
        )
    if not subs:
        logger.debug(f"{quake.source} {quake.event_id}#{quake.seq} 无需推送")
        return
    adapter = bot.get_adapter(Adapter)
    if adapter is None:
        logger.warning("没有 OneBot v11 适配器, 无法推送")
        return
    text = render_quake(quake)
    interval = cfgloader.value.send_interval
    results: list[DeliveryResult] = []
    for i, sub in enumerate(subs):
        if i and interval:
            await asyncio.sleep(interval)
        results.append(await _send(adapter, sub.target, text))
    ok = sum(r.ok for r in results)
    logger.info(
        f"已推送 {quake.source} {quake.event_id}#{quake.seq} "
        f"{quake.hypocenter} M{quake.magnitude}: {ok}/{len(subs)} 个会话"
    )
    if report_id is not None:
        try:
            await archive.record_deliveries(report_id, results)
        except Exception:
            logger.exception("留档推送结果失败")


def _target_of(event: MessageEvent) -> TargetKey:
    if isinstance(event, GroupMessageEvent):
        return ("group", event.group_id)
    return ("private", event.user_id)


def _can_manage(event: MessageEvent) -> bool:
    if not isinstance(event, GroupMessageEvent):
        # 私聊订阅只影响本人
        return True
    if event.sender.is_group_admin():
        return True
    factory = get_checker_factory()
    user = factory.extract_user(event)
    return user is not None and (factory.is_owner(user) or factory.is_admin(user))


def _status_extra() -> str:
    conn = state.client.connected
    up = sum(conn.values())
    return f"数据源连接: {up}/{len(conn)}"


@plugin.use
@on_command(".", " ", ["预警", "eew"])
async def alert_command(event: MessageEvent, adapter: Adapter, args: CmdArgs) -> None:
    await _init_done.wait()
    if not state.ready:
        await adapter.send_reply("预警插件初始化失败, 暂不可用")
        return
    target = _target_of(event)
    tokens = [str(v) for v in args.vals]
    try:
        async with state.lock:
            store = storeloader.value
            # 在副本上改, 保存成功后才替换; 保存失败时内存与文件保持一致
            draft = store.model_copy(deep=True)
            result = execute(
                draft,
                target,
                tokens,
                can_manage=_can_manage(event),
                status_extra=_status_extra(),
            )
            if result.changed:
                previous = store.subscriptions
                store.subscriptions = draft.subscriptions
                try:
                    await storeloader.save_async()
                except Exception:
                    store.subscriptions = previous
                    raise
    except CommandError as e:
        await adapter.send_reply(str(e))
        return
    except Exception:
        logger.exception("处理 .预警 指令失败")
        await adapter.send_reply("出错了, 订阅未修改")
        return
    if result.send_test:
        sub = storeloader.value.get(target)
        conditions = "本会话尚未订阅" if sub is None else sub.describe()
        await _send(adapter, target, render_test(conditions))
        return
    await adapter.send_reply(result.reply)
