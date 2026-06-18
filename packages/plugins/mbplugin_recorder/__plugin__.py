from lemony_storage_helper.database.sqlite import SqliteDatabaseHelper
from melobot import PluginPlanner, get_bot, get_logger
from melobot.plugin import SyncShare
from melobot.protocols.onebot.v11.adapter.event import MessageEvent, NoticeEvent
from melobot.protocols.onebot.v11.handle import on_message, on_notice
from sqlalchemy.exc import IntegrityError, OperationalError

from .adapters.ob11 import OneBot11MessageRecorderAdapter
from .db import models as recorder_models
from .db.models import recorder_metadata
from .db.operations import record_member_event, record_message, record_notice
from .service import RecorderService
from .worker import MediaDownloadWorker

PLUGIN_IDENTIFIER = "recorder"
DATABASE_PATH = "record/recorder.db"
MEDIA_CACHE_ROOT = "data/record/media"

bot = get_bot()
logger = get_logger()
recorder_db = SqliteDatabaseHelper(DATABASE_PATH, metadata=recorder_metadata)
recorder_service = RecorderService(recorder_db)
media_worker = MediaDownloadWorker(recorder_db, cache_root=MEDIA_CACHE_ROOT)
onebot11_adapter = OneBot11MessageRecorderAdapter()

recorder_db_share = SyncShare(
    "recorder_database",
    lambda: recorder_db,
    static=True,
)
recorder_service_share = SyncShare(
    "recorder_service",
    lambda: recorder_service,
    static=True,
)
recorder_models_share = SyncShare(
    "recorder_models",
    lambda: recorder_models,
    static=True,
)
plugin = PluginPlanner(
    "0.1.0a0",
    shares=[
        recorder_db_share,
        recorder_service_share,
        recorder_models_share,
    ],
)


@bot.on_started
async def _() -> None:
    logger.info(
        f"Recorder 插件启动中: db={DATABASE_PATH}, media_cache={MEDIA_CACHE_ROOT}"
    )
    await recorder_db.startup()
    media_worker.start()
    logger.info("Recorder 插件已启动")


@bot.on_stopped
async def _() -> None:
    logger.info("Recorder 插件停止中")
    await media_worker.stop()
    if recorder_db.is_initialized():
        await recorder_db.close()
    logger.info("Recorder 插件已停止")


@plugin.use
@on_message()
async def record_onebot11_message(event: MessageEvent) -> None:
    if not onebot11_adapter.supports(event):
        return
    await recorder_db.wait_until_initialized()
    payload = onebot11_adapter.to_recorded_message(event)
    try:
        async with recorder_db.get_session(style="sqlalchemy") as session:
            message = await record_message(session, payload)
            logger.debug(
                f"已记录 OneBot11 消息: conversation={payload.conversation.type}/"
                f"{payload.conversation.external_id} message_id="
                f"{payload.external_message_id} db_id={message.id}"
            )
    except (IntegrityError, OperationalError):
        logger.exception("数据库错误，消息记录终止")
        raise
    except Exception:
        logger.generic_exc(
            "记录 OneBot11 消息失败",
            obj={
                "protocol": str(event.protocol),
                "self_id": getattr(event, "self_id", None),
                "message_id": getattr(event, "message_id", None),
            },
        )


@plugin.use
@on_notice()
async def record_onebot11_notice(event: NoticeEvent) -> None:
    if not onebot11_adapter.supports_notice(event):
        return
    await recorder_db.wait_until_initialized()
    payload = onebot11_adapter.to_notice(event)
    if payload is None:
        logger.debug(
            f"忽略未投影的 OneBot11 通知: notice_type="
            f"{getattr(event, 'notice_type', None)}"
        )
        return
    try:
        async with recorder_db.get_session(style="sqlalchemy") as session:
            notice = await record_notice(session, payload)
            logger.debug(
                f"已记录 OneBot11 通知: type={payload.notice_type} "
                f"sub_type={payload.sub_type} notice_id={notice.id} "
                f"raw_id={payload.external_notice_id}"
            )
            member_payload = onebot11_adapter.to_member_event(event)
            if member_payload is not None:
                member_event = await record_member_event(session, member_payload)
                logger.debug(
                    f"已记录 OneBot11 成员事件: type={member_payload.event_type} "
                    f"event_id={member_event.id} raw_id={member_payload.raw_event_id}"
                )
    except (IntegrityError, OperationalError):
        logger.exception("数据库错误，成员事件记录终止")
        raise
    except Exception:
        logger.generic_exc(
            "记录 OneBot11 通知失败",
            obj={
                "protocol": str(event.protocol),
                "self_id": getattr(event, "self_id", None),
                "notice_type": getattr(event, "notice_type", None),
            },
        )
