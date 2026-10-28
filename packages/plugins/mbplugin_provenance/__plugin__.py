"""AI 生成内容核验: 引用一条消息, 检查里面的图片是否带 C2PA 清单或 SynthID 水印。

接口说明见 https://developers.openai.com/api/docs/guides/content-provenance:
一张图一次请求, 结果同步返回, 图片会有 ``c2pa`` 与 ``synthid`` 两项。
"""

import asyncio
import hashlib
from collections.abc import Mapping
from logging import getLogger
from typing import Any

import aiohttp
from lemony_checkers import get_checker_factory, get_checker_factory_wrapper
from lemony_network.qqntmedia_sslcontext import QQNTMEDIA_SSL_CONTEXT
from lemony_network.request import HTTP_HEADERS
from lemony_onebot_utils.onebot_ext import SetGroupReaction, try_extension
from lemony_settings import BaseSettings, get_secret, require
from lemony_utils.help import Command, register_help
from melobot import PluginInfo, PluginPlanner, on_command
from melobot.bot import get_bot
from melobot.protocols.onebot.v11.adapter import Adapter
from melobot.protocols.onebot.v11.adapter.event import GroupMessageEvent, MessageEvent
from melobot.protocols.onebot.v11.adapter.segment import ReplySegment

from .client import ProvenanceError, ProvenanceResult, check_image
from .images import image_payloads, local_candidates, mime_of
from .report import format_report
from .runtime import CheckRegistry, Cooldown, access_level

PLUGIN_IDENTIFIER = "mbplugin_provenance"
# 凭据键: 值放在 credentials.json 的 refs 里, 或环境变量 MIRAICHAN_PROVENANCE_API_KEY
CREDENTIAL_KEY = "provenance.api_key"


class ProvenanceSettings(BaseSettings):
    check_command: str = "check"
    # 核验会花钱, 默认只给 owner 与管理员用
    allow_admins: bool = True
    # 连普通用户也开放; 默认关, 打开后所有群成员都能用 (仍受 user_cooldown 限制)
    allow_all: bool = False
    max_images: int = 3
    max_image_bytes: int = 10 * 1024 * 1024
    timeout: float = 30.0
    user_cooldown: float = 10.0
    # 同一张图在这个时间窗内查过就复用结果 (秒)
    image_cache_ttl: float = 900.0
    # 收到请求后在指令消息上贴的 QQ 表情编号 (424 是续标识); 空字符串关闭, 退回文字回执
    ack_reaction: str = "424"
    api_base: str = "https://api.openai.com/v1"
    # 服务器不能直连 OpenAI 时填 HTTP 代理, 例如 http://127.0.0.1:7890
    api_proxy: str | None = None


bot = get_bot()
logger = getLogger(__name__)
plugin = PluginPlanner(
    "0.1.0",
    info=PluginInfo(desc="引用一条消息, 核验图片是否带 C2PA / SynthID 等 AI 生成信号."),
)

cfgloader = require(model=ProvenanceSettings, identifier=PLUGIN_IDENTIFIER)
cfgloader.load()

_access = access_level(cfgloader.value.allow_all, cfgloader.value.allow_admins)
_WHO = {"all": "所有群成员", "admins": "owner 与 bot 管理员", "owner": "owner"}
register_help(
    PLUGIN_IDENTIFIER,
    title="内容核验",
    summary=f"核验图片是否带 AI 生成信号, 仅 {_WHO[_access]} 可用",
    aliases=["provenance"],
    commands=[
        Command(
            f".{cfgloader.value.check_command}",
            "回复一条带图片的消息, 检查 C2PA 清单与 SynthID 水印",
            admin_only=_access != "all",
        )
    ],
)
checker_factory = get_checker_factory_wrapper(plugin_name=PLUGIN_IDENTIFIER)
_factory = get_checker_factory()


def _privileged_checker():
    # allow_all 打开时返回 None, melobot 视为不设权限检查
    if _access == "all":
        return None
    if _access == "admins":
        return checker_factory.get_admin_checker()
    return checker_factory.get_owner_checker()


def _is_owner(event: MessageEvent) -> bool:
    user = _factory.extract_user(event)
    return user is not None and _factory.is_owner(user)


_gate = asyncio.Semaphore(2)
_cooldown = Cooldown(seconds=cfgloader.value.user_cooldown)
_registry = CheckRegistry(ttl=cfgloader.value.image_cache_ttl)


def _cooldown_remaining(user_id: int) -> float:
    return _cooldown.remaining(user_id)


def _reply_target(event: MessageEvent) -> str | None:
    replies = event.get_segments(ReplySegment)
    if not replies:
        return None
    return str(replies[0].data["id"])


async def _get_msg(adapter: Adapter, message_id: str) -> Mapping[str, Any] | None:
    """取消息的 OneBot 原始数据; 取不到返回 None"""
    try:
        echo = await (await adapter.get_msg(int(message_id)))[0]
    except Exception:
        logger.debug("get_msg %s 失败", message_id, exc_info=True)
        return None
    if echo is None or not echo.is_ok() or echo.data is None:
        return None
    return echo.data


async def _download(session: aiohttp.ClientSession, url: str) -> bytes:
    # QQ NT 图床要特定的 TLS 设置; 其余地址用 aiohttp 默认校验
    ssl = QQNTMEDIA_SSL_CONTEXT if "multimedia.nt.qq.com.cn" in url else True
    async with session.get(url, ssl=ssl, headers=dict(HTTP_HEADERS)) as response:
        response.raise_for_status()
        max_bytes = cfgloader.value.max_image_bytes
        if (response.content_length or 0) > max_bytes:
            raise ProvenanceError("图片太大了")
        buffer = bytearray()
        async for chunk in response.content.iter_chunked(64 * 1024):
            buffer.extend(chunk)
            if len(buffer) > max_bytes:
                raise ProvenanceError("图片太大了")
        return bytes(buffer)


async def _image_bytes(
    seg_data: Mapping[str, Any], session: aiohttp.ClientSession
) -> tuple[bytes, str]:
    """取一张图片的字节与 media type, 优先本地文件, 其次 url"""
    max_bytes = cfgloader.value.max_image_bytes
    for path in local_candidates(seg_data):
        try:
            data = await asyncio.to_thread(path.read_bytes)
        except OSError:
            continue
        if len(data) > max_bytes:
            raise ProvenanceError("图片太大了")
        return data, mime_of(data, seg_data, None)
    url = seg_data.get("url")
    if isinstance(url, str) and url:
        data = await _download(session, url)
        return data, mime_of(data, seg_data, url)
    raise ProvenanceError("取不到这张图片 (既没有本地文件也没有下载地址)")


@plugin.use
@on_command(
    ".",
    " ",
    [cfgloader.value.check_command],
    checker=_privileged_checker(),
)
async def check_command(event: MessageEvent, adapter: Adapter) -> None:
    base_id = _reply_target(event)
    if base_id is None:
        await adapter.send_reply("回复一条带图片的消息来核验")
        return
    user_id = event.user_id
    left = _cooldown_remaining(user_id)
    if left > 0 and not _is_owner(event):
        await adapter.send_reply(f"太快了, {int(left) + 1} 秒后再试")
        return
    await _run_check(
        adapter,
        base_id=base_id,
        user_id=user_id,
        message_id=event.message_id,
        group_id=event.group_id if isinstance(event, GroupMessageEvent) else None,
    )


async def _ack(
    adapter: Adapter,
    message_id: int,
    *,
    group_id: int | None,
    count: int,
    code: str,
) -> bool:
    """给指令消息贴一个 QQ 表情回应; 群聊以外或贴不上就退回文字回执"""
    if code and group_id is not None:
        echo = await try_extension(
            adapter,
            SetGroupReaction(
                group_id=group_id, message_id=message_id, code=code, is_set=True
            ),
        )
        if echo is not None:
            return True
    await adapter.send_reply(f"正在检查 {count} 张图片...")
    return False


async def _run_check(
    adapter: Adapter,
    *,
    base_id: str,
    user_id: int,
    message_id: int,
    group_id: int | None,
) -> None:
    api_key = get_secret(CREDENTIAL_KEY)
    if not api_key:
        await adapter.send_reply(
            "还没配置核验凭据 (provenance.api_key), 让管理员加到凭据文件或环境变量里"
        )
        return

    payload = await _get_msg(adapter, base_id)
    if payload is None:
        await adapter.send_reply("取不到这条消息")
        return
    images = image_payloads(payload)
    if not images:
        await adapter.send_reply("这条消息里没有图片")
        return
    total = len(images)
    images = images[: cfgloader.value.max_images]
    note = f"只核验前 {len(images)} 张图片" if total > len(images) else ""

    # 下载与请求都要几秒; 用表情回应表示"已收到, 正在处理", 贴不上才发文字
    await _ack(
        adapter,
        message_id,
        group_id=group_id,
        count=len(images),
        code=cfgloader.value.ack_reaction,
    )
    logger.info("开始核验图片: 用户 %s, %d 张", user_id, len(images))
    _cooldown.touch(user_id)
    reports: list[str] = []
    async with _gate, aiohttp.ClientSession() as session:
        for index, seg_data in enumerate(images, start=1):
            try:
                data, mime = await _image_bytes(seg_data, session)
            except ProvenanceError as exc:
                reports.append(f"图片 {index}/{len(images)}: {exc}")
                continue
            except aiohttp.ClientError as exc:
                logger.debug("图片下载失败", exc_info=True)
                reports.append(
                    f"图片 {index}/{len(images)}: 下载失败 ({type(exc).__name__})"
                )
                continue

            # 按内容摘要去重: 刚查过直接复用, 正在查的跳过, 避免重复花钱
            digest = hashlib.sha256(data).hexdigest()
            cached = _registry.cached(digest)
            if cached is not None:
                logger.info("复用刚查过的结果: %s", digest[:12])
                reports.append(
                    format_report(
                        index, len(images), mime=mime, size=len(data), results=cached
                    )
                    + "\n(这张图刚查过, 直接复用上次结果)"
                )
                continue
            if not _registry.begin(digest):
                logger.info("跳过正在检查的图片: %s", digest[:12])
                reports.append(f"图片 {index}/{len(images)}: 这张图正在检查中, 跳过")
                continue

            checked: tuple[ProvenanceResult, ...] | None = None
            try:
                checked = await check_image(
                    session,
                    data,
                    mime=mime,
                    api_key=api_key,
                    base_url=cfgloader.value.api_base,
                    total_timeout=cfgloader.value.timeout,
                    proxy=cfgloader.value.api_proxy,
                )
            except ProvenanceError as exc:
                reports.append(f"图片 {index}/{len(images)}: {exc}")
                continue
            finally:
                _registry.finish(digest, checked)
            reports.append(
                format_report(
                    index, len(images), mime=mime, size=len(data), results=checked
                )
            )

    if note:
        reports.append(note)
    await adapter.send_reply("\n\n".join(reports))
