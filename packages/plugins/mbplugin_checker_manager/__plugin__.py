"""
Checker Manager 插件

用于让 Owner 和管理员从聊天通过指令管理 lemony_checkers 包中的过滤规则。

指令列表:
    .checker global mode <whitelist|blacklist>  - 设置全局权限模式
    .checker global rules                        - 查看全局规则
    .checker global add <allow|deny> [uid1:uid2,...|this] - 添加全局规则
    .checker global remove <index>               - 移除全局规则
    .checker global clear                        - 清除全局规则

    .checker admin list                          - 查看管理员列表
    .checker admin add <user_id>                 - 添加管理员
    .checker admin remove <user_id>              - 移除管理员

    .checker plugin <name> enable                - 启用插件
    .checker plugin <name> disable               - 禁用插件
    .checker plugin <name> mode <whitelist|blacklist|inherit> - 设置插件权限模式
    .checker plugin <name> rules                 - 查看插件规则
    .checker plugin <name> add <allow|deny> [uid1:uid2,...|this] - 添加插件规则
    .checker plugin <name> remove <index>        - 移除插件规则
    .checker plugin <name> clear                 - 清除插件规则

    .checker reload [global|<plugin_name>]       - 重新加载配置
    .checker save [global|<plugin_name>]         - 保存配置
    .checker status                              - 查看当前状态

备注:
    在 ids 参数中可以使用 "this" 代替当前群聊的群号 (仅限群聊中使用).
    uid 格式: 纯数字表示 user 规则, "数字:数字" 表示 user:group 规则.
"""

from typing import Any

from lemony_checkers import EditContext, Rule, get_checker_factory, require_admin
from lemony_checkers.adapters.ob11 import Ob11UniqueUser
from lemony_checkers.factory import LemonyCheckerFactory
from melobot import PluginPlanner, get_logger
from melobot.handle import on_command
from melobot.protocols.onebot.v11 import (
    Adapter,
    GroupMessageEvent,
    MessageEvent,
)
from melobot.utils.parse import CmdArgs

CheckerManager = PluginPlanner("1.0.2")
logger = get_logger()


def _get_factory() -> LemonyCheckerFactory:
    return get_checker_factory()


def _get_group_id(event: MessageEvent) -> int | None:
    """从事件中获取群组ID, 私聊返回 None."""
    if isinstance(event, GroupMessageEvent):
        return event.group_id
    return None


def _format_rules(rules: list[Rule]) -> str:
    """格式化规则列表为可读字符串"""
    if not rules:
        return "暂无规则"

    lines = ["规则列表:"]
    for i, rule in enumerate(rules):
        constrains_str = "所有" if rule.constrains is None else str(rule.constrains)
        lines.append(
            f"  [{i}] {rule.action.upper():<6}: proto={rule.protocol}, "
            f"constrains={constrains_str}"
        )
    return "\n".join(lines)


class ThisInPrivateChatError(Exception):
    """在私聊中使用了 'this' 简写"""


class ConstraintParseError(ValueError):
    """解析约束条件时出错（非法的 ID 格式）"""


def _parse_constrains(
    ids_str: str | None, *, group_id: int | None = None
) -> list[dict[str, list[Any]]] | None:
    """解析约束条件字符串.

    支持格式: "123456" (user_id), "123456:789012" (user_id:group_id),
    "this" (当前群号), "all"/"none"/"*" 表示匹配所有.

    Returns:
        constraint 列表或 None (匹配所有)。每个 constraint 内部字段为 AND, 多个 constraint 之间为 OR。

    Raises:
        ConstraintParseError: ID 格式无效时抛出
    """
    if ids_str is None or ids_str.lower() in ("all", "none", "*"):
        return None
    if not ids_str.strip():
        return []  # 空输入不匹配任何人, 避免意外创建无条件规则

    result: list[dict[str, list[Any]]] = []
    for part in ids_str.split(","):
        part = part.strip()
        if not part:
            continue
        if part.lower() == "this":
            if group_id is None:
                raise ThisInPrivateChatError()
            result.append({"group_id": [group_id]})
        elif ":" in part:
            uid_str, gid_str = part.split(":", 1)
            try:
                constraint: dict[str, list[Any]] = {"user_id": [int(uid_str)]}
            except ValueError:
                raise ConstraintParseError(f"无法解析 user_id: {uid_str!r}") from None
            if gid_str.strip():
                try:
                    constraint["group_id"] = [int(gid_str)]
                except ValueError:
                    raise ConstraintParseError(
                        f"无法解析 group_id: {gid_str!r}"
                    ) from None
            result.append(constraint)
        else:
            try:
                result.append({"user_id": [int(part)]})
            except ValueError:
                raise ConstraintParseError(f"无法解析 ID: {part!r}") from None
    return result if result else None


@CheckerManager.use
@on_command(".", " ", ["checker", "ck"])
@require_admin("无权使用此指令，需要 Owner 或 Admin 权限")
async def checker_command(adapter: Adapter, event: MessageEvent, args: CmdArgs):
    """Checker 管理主命令"""

    if not args.vals:
        await adapter.send_reply(
            "Checker Manager 使用帮助:\n"
            ".checker status - 查看状态\n"
            ".checker global ... - 全局配置\n"
            ".checker admin ... - 管理员管理\n"
            ".checker plugin <name> ... - 插件配置\n"
            ".checker reload/save ... - 重载/保存配置"
        )
        return

    subcmd = args.vals[0].lower()
    sub_args = list(map(str, args.vals[1:]))

    match subcmd:
        case "status":
            await _handle_status(adapter)
        case "global":
            await _handle_global(adapter, event, sub_args)
        case "admin":
            await _handle_admin(adapter, event, sub_args)
        case "plugin":
            await _handle_plugin(adapter, event, sub_args)
        case "reload":
            await _handle_reload(adapter, sub_args)
        case "save":
            await _handle_save(adapter, sub_args)
        case _:
            await adapter.send_reply(f"未知子命令: {subcmd}")


async def _handle_status(adapter: Adapter):
    """处理 status 子命令"""
    factory = _get_factory()
    global_settings = factory.global_settings
    owners = factory.get_owner()
    admins = factory.get_admins()

    lines = [
        "Checker 状态:",
        f"  全局模式: {global_settings.mode}",
        f"  Owner 数量: {len(owners)}",
        f"  管理员数量: {len(admins)}",
        f"  全局规则: {len(global_settings.rules)} 条",
    ]
    await adapter.send_reply("\n".join(lines))


async def _handle_global(adapter: Adapter, event: MessageEvent, args: list[str]):
    """处理 global 子命令"""
    if not args:
        await adapter.send_reply(
            "全局配置命令:\n"
            ".checker global mode <whitelist|blacklist>\n"
            ".checker global rules\n"
            ".checker global add <allow|deny> [uid1:uid2,...|this]\n"
            ".checker global remove <index>\n"
            ".checker global clear"
        )
        return

    action = args[0].lower()
    action_args = args[1:]

    match action:
        case "mode":
            if not action_args:
                global_settings = _get_factory().global_settings
                await adapter.send_reply(f"当前全局模式: {global_settings.mode}")
                return
            mode = action_args[0].lower()
            if mode not in ("whitelist", "blacklist"):
                await adapter.send_reply("模式必须是 whitelist 或 blacklist")
                return
            async with EditContext(_get_factory()) as ctx:
                ctx.set_global_mode(mode)
            await adapter.send_reply(f"全局模式已设置为: {mode}")

        case "rules":
            global_settings = _get_factory().global_settings
            await adapter.send_reply(_format_rules(global_settings.rules))

        case "add":
            if len(action_args) < 1:
                await adapter.send_reply(
                    "用法: .checker global add <allow|deny> [uid1:uid2,...|this]"
                )
                return
            rule_action = action_args[0].lower()
            ids_str = action_args[1] if len(action_args) > 1 else None

            if rule_action not in ("allow", "deny"):
                await adapter.send_reply("动作必须是 allow 或 deny")
                return

            group_id = _get_group_id(event)
            try:
                constrains = _parse_constrains(ids_str, group_id=group_id)
            except ThisInPrivateChatError:
                await adapter.send_reply('"this" 只能在群聊中使用, 用于代替当前群号')
                return
            except ConstraintParseError as e:
                await adapter.send_reply(str(e))
                return
            async with EditContext(_get_factory()) as ctx:
                ctx.add_global_rule(
                    rule_action,
                    protocol=str(event.protocol),
                    constrains=constrains,
                )
            constrains_display = "所有" if constrains is None else str(constrains)
            await adapter.send_reply(
                f"已添加全局规则: {rule_action} -> {constrains_display}"
            )

        case "remove":
            if not action_args:
                await adapter.send_reply("用法: .checker global remove <index>")
                return
            try:
                index = int(action_args[0])
            except ValueError:
                await adapter.send_reply("索引必须是数字")
                return

            async with EditContext(_get_factory()) as ctx:
                removed = ctx.remove_global_rule(index)
            if removed:
                await adapter.send_reply(f"已移除全局规则 [{index}]")
            else:
                await adapter.send_reply(f"索引 {index} 无效")

        case "clear":
            async with EditContext(_get_factory()) as ctx:
                count = ctx.clear_global_rules()
            await adapter.send_reply(f"已清除 {count} 条全局规则")

        case _:
            await adapter.send_reply(f"未知操作: {action}")


async def _handle_admin(adapter: Adapter, event: MessageEvent, args: list[str]):
    """处理 admin 子命令 (仅 Owner 可用)"""
    # 管理员操作仅 Owner 可用 — 手动检查（作为内部子函数无法使用装饰器）
    factory = _get_factory()
    user = factory.extract_user(event)
    if user is None or not factory.is_owner(user):
        await adapter.send_reply("管理员操作仅 Owner 可用")
        return

    if not args:
        await adapter.send_reply(
            "管理员命令:\n"
            ".checker admin list\n"
            ".checker admin add <user_id>\n"
            ".checker admin remove <user_id>"
        )
        return

    action = args[0].lower()
    action_args = args[1:]

    match action:
        case "list":
            admins = factory.get_admins()
            if not admins:
                await adapter.send_reply("暂无管理员")
            else:
                lines = ["管理员列表:"]
                for admin in admins:
                    lines.append(f"  • {admin.model_dump()}")
                await adapter.send_reply("\n".join(lines))

        case "add":
            if not action_args:
                await adapter.send_reply("用法: .checker admin add <user_id>")
                return
            try:
                uid = int(action_args[0])
            except ValueError:
                await adapter.send_reply("user_id 必须是数字")
                return

            new_admin = Ob11UniqueUser(
                user_id=uid,
                group_id=None,
                protocol=str(event.protocol),  # type: ignore[arg-type]
            )
            async with EditContext(factory) as ctx:
                success = ctx.add_admin(new_admin)
            if success:
                await adapter.send_reply(f"已添加管理员: {uid}")
            else:
                await adapter.send_reply(f"{uid} 已是管理员")

        case "remove":
            if not action_args:
                await adapter.send_reply("用法: .checker admin remove <user_id>")
                return
            try:
                uid = int(action_args[0])
            except ValueError:
                await adapter.send_reply("user_id 必须是数字")
                return

            target = Ob11UniqueUser(
                user_id=uid,
                group_id=None,
                protocol=str(event.protocol),  # type: ignore[arg-type]
            )
            async with EditContext(factory) as ctx:
                success = ctx.remove_admin(target)
            if success:
                await adapter.send_reply(f"已移除管理员: {uid}")
            else:
                await adapter.send_reply(f"{uid} 不是管理员")

        case _:
            await adapter.send_reply(f"未知操作: {action}")


async def _handle_plugin(adapter: Adapter, event: MessageEvent, args: list[str]):
    """处理 plugin 子命令"""
    if len(args) < 2:
        await adapter.send_reply(
            "插件配置命令:\n"
            ".checker plugin <name> enable|disable\n"
            ".checker plugin <name> mode <whitelist|blacklist|inherit>\n"
            ".checker plugin <name> rules\n"
            ".checker plugin <name> add <allow|deny> [uid1:uid2,...|this]\n"
            ".checker plugin <name> remove <index>\n"
            ".checker plugin <name> clear"
        )
        return

    plugin_name = args[0]
    action = args[1].lower()
    action_args = args[2:]

    match action:
        case "enable":
            async with EditContext(_get_factory()) as ctx:
                ctx.set_plugin_enabled(plugin_name, True)
            await adapter.send_reply(f"插件 {plugin_name} 已启用")

        case "disable":
            async with EditContext(_get_factory()) as ctx:
                ctx.set_plugin_enabled(plugin_name, False)
            await adapter.send_reply(f"插件 {plugin_name} 已禁用")

        case "mode":
            if not action_args:
                plugin_settings = _get_factory().get_plugin_settings(plugin_name)
                mode_str = plugin_settings.mode or "inherit (继承全局)"
                await adapter.send_reply(f"插件 {plugin_name} 当前模式: {mode_str}")
                return

            mode = action_args[0].lower()
            if mode == "inherit":
                async with EditContext(_get_factory()) as ctx:
                    ctx.set_plugin_mode(plugin_name, None)
            elif mode in ("whitelist", "blacklist"):
                async with EditContext(_get_factory()) as ctx:
                    ctx.set_plugin_mode(plugin_name, mode)
            else:
                await adapter.send_reply("模式必须是 whitelist, blacklist 或 inherit")
                return
            await adapter.send_reply(f"插件 {plugin_name} 模式已设置为: {mode}")

        case "rules":
            plugin_settings = _get_factory().get_plugin_settings(plugin_name)
            await adapter.send_reply(
                f"插件 {plugin_name}\n" + _format_rules(plugin_settings.rules)
            )

        case "add":
            if len(action_args) < 1:
                await adapter.send_reply(
                    f"用法: .checker plugin {plugin_name} add <allow|deny> [uid1:uid2,...|this]"
                )
                return
            rule_action = action_args[0].lower()
            ids_str = action_args[1] if len(action_args) > 1 else None

            if rule_action not in ("allow", "deny"):
                await adapter.send_reply("动作必须是 allow 或 deny")
                return

            group_id = _get_group_id(event)
            try:
                constrains = _parse_constrains(ids_str, group_id=group_id)
            except ThisInPrivateChatError:
                await adapter.send_reply('"this" 只能在群聊中使用, 用于代替当前群号')
                return
            except ConstraintParseError as e:
                await adapter.send_reply(str(e))
                return
            async with EditContext(_get_factory()) as ctx:
                ctx.add_plugin_rule(
                    plugin_name,
                    rule_action,
                    protocol=str(event.protocol),
                    constrains=constrains,
                )
            constrains_display = "所有" if constrains is None else str(constrains)
            await adapter.send_reply(
                f"已为插件 {plugin_name} 添加规则: {rule_action} -> {constrains_display}"
            )

        case "remove":
            if not action_args:
                await adapter.send_reply(
                    f"用法: .checker plugin {plugin_name} remove <index>"
                )
                return
            try:
                index = int(action_args[0])
            except ValueError:
                await adapter.send_reply("索引必须是数字")
                return

            async with EditContext(_get_factory()) as ctx:
                removed = ctx.remove_plugin_rule(plugin_name, index)
            if removed:
                await adapter.send_reply(f"已移除插件 {plugin_name} 的规则 [{index}]")
            else:
                await adapter.send_reply(f"索引 {index} 无效")

        case "clear":
            async with EditContext(_get_factory()) as ctx:
                count = ctx.clear_plugin_rules(plugin_name)
            await adapter.send_reply(f"已清除插件 {plugin_name} 的 {count} 条规则")

        case _:
            await adapter.send_reply(f"未知操作: {action}")


async def _handle_reload(adapter: Adapter, args: list[str]):
    """处理 reload 子命令"""
    factory = _get_factory()
    if not args:
        factory.reload_global_settings()
        await adapter.send_reply("已重新加载全局配置")
        return

    target = args[0].lower()
    if target == "global":
        factory.reload_global_settings()
        await adapter.send_reply("已重新加载全局配置")
    else:
        factory.reload_plugin_settings(target)
        await adapter.send_reply(f"已重新加载插件 {target} 配置")


async def _handle_save(adapter: Adapter, args: list[str]):
    """处理 save 子命令"""
    factory = _get_factory()
    if not args:
        factory.save_global_settings()
        await adapter.send_reply("已保存全局配置")
        return

    target = args[0].lower()
    if target == "global":
        factory.save_global_settings()
        await adapter.send_reply("已保存全局配置")
    else:
        factory.save_plugin_settings(target)
        await adapter.send_reply(f"已保存插件 {target} 配置")
