"""地震信息订阅推送: 接入 Wolfx WebSocket, 按会话订阅筛选后推送到群聊或私聊.

指令: ``.预警`` (查看用法). 群里修改订阅需要群管理员或 bot 管理员, 私聊里本人即可.
"""

import asyncio
import logging
from datetime import timedelta

from lemony_checkers import get_checker_factory
from lemony_settings import require
from melobot import PluginInfo, PluginPlanner, get_bot
from melobot.handle import on_command
from melobot.protocols.onebot.v11 import Adapter, GroupMessageEvent, MessageEvent
from melobot.utils.parse import CmdArgs

from .client import WolfxClient
from .commands import CommandError, execute
from .dispatch import Dispatcher
from .quake import Quake
from .render import render_quake, render_test
from .settings import AlertSettings
from .subscription import Subscription, SubscriptionStore, TargetKey

PLUGIN_IDENTIFIER = "emergency_alerts"

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


class _State:
    """on_ready 里建好的运行期对象; 初始化失败时 ready 为 False, handler 直接放弃"""

    ready = False
    client: WolfxClient
    dispatcher: Dispatcher
    #: 订阅的读改写与推送时的读取互斥, 保证保存到文件的是完整状态
    lock: asyncio.Lock


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


@bot.on_stopped
async def _() -> None:
    if state.ready:
        await state.client.stop()


async def _send(adapter: Adapter, target: TargetKey, text: str) -> bool:
    kind, tid = target
    try:
        if kind == "group":
            handles = await adapter.send_custom(text, group_id=tid)
        else:
            handles = await adapter.send_custom(text, user_id=tid)
        echo = await handles[0]
    except Exception:
        logger.exception(f"推送到 {kind}:{tid} 失败")
        return False
    if echo is None or not echo.is_ok():
        logger.warning(f"推送到 {kind}:{tid} 失败: {echo!r}")
        return False
    return True


async def _on_quake(quake: Quake) -> None:
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
    ok = 0
    for i, sub in enumerate(subs):
        if i and interval:
            await asyncio.sleep(interval)
        ok += await _send(adapter, sub.target, text)
    logger.info(
        f"已推送 {quake.source} {quake.event_id}#{quake.seq} "
        f"{quake.hypocenter} M{quake.magnitude}: {ok}/{len(subs)} 个会话"
    )


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
