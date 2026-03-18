"""
Checker Manager 插件

用于让 Owner 和管理员从聊天通过指令管理 lemony_checkers 包中的过滤规则。

指令列表:
    .checker global mode <whitelist|blacklist>  - 设置全局权限模式
    .checker global priority <group_first|user_first> - 设置全局规则匹配优先级
    .checker global rules [user|group]          - 查看全局规则
    .checker global add <user|group> <allow|deny> [id1,id2,...|this] - 添加全局规则
    .checker global remove <user|group> <index> - 移除全局规则
    .checker global clear [user|group]          - 清除全局规则

    .checker admin list                         - 查看管理员列表
    .checker admin add <user_id>                - 添加管理员
    .checker admin remove <user_id>             - 移除管理员

    .checker plugin <name> enable               - 启用插件
    .checker plugin <name> disable              - 禁用插件
    .checker plugin <name> mode <whitelist|blacklist|inherit> - 设置插件权限模式
    .checker plugin <name> priority <group_first|user_first|inherit> - 设置插件规则匹配优先级
    .checker plugin <name> rules [user|group]   - 查看插件规则
    .checker plugin <name> add <user|group> <allow|deny> [id1,id2,...|this] - 添加插件规则
    .checker plugin <name> remove <user|group> <index> - 移除插件规则
    .checker plugin <name> clear [user|group]   - 清除插件规则

    .checker reload [global|<plugin_name>]      - 重新加载配置
    .checker save [global|<plugin_name>]        - 保存配置
    .checker status                             - 查看当前状态

备注:
    在 ids 参数中可以使用 "this" 代替当前群聊的群号 (仅限群聊中使用).
"""

from lemony_checkers import EditContext, Rule, get_checker_factory
from lemony_checkers.factory import LemonyCheckerFactory
from melobot import PluginPlanner, get_logger
from melobot.handle import on_command
from melobot.protocols.onebot.v11 import Adapter
from melobot.protocols.onebot.v11.adapter.event import GroupMessageEvent, MessageEvent
from melobot.utils.parse import CmdArgs

CheckerManager = PluginPlanner("1.0.1")
logger = get_logger()


def _get_factory() -> LemonyCheckerFactory:
    return get_checker_factory()


def _get_group_id(event: MessageEvent) -> int | None:
    """从事件中获取群组ID, 私聊返回 None."""
    if isinstance(event, GroupMessageEvent):
        return event.group_id
    return None


def _check_privilege(user_id: int) -> bool:
    """检查用户是否有权限操作 (owner 或 admin)"""
    factory = _get_factory()
    return factory.is_owner(user_id) or factory.is_admin(user_id)


def _format_rules(rules: list[Rule], rule_type: str) -> str:
    """格式化规则列表为可读字符串"""
    if not rules:
        return f"暂无{rule_type}规则"

    lines = [f"{rule_type}规则列表:"]
    for i, rule in enumerate(rules):
        ids_str = "所有" if rule.ids is None else ", ".join(map(str, rule.ids))
        lines.append(f"  [{i}] {rule.action.upper():<6}: {ids_str}")
    return "\n".join(lines)


class ThisInPrivateChatError(Exception):
    """在私聊中使用了 'this' 简写"""


def _parse_ids(ids_str: str | None, *, group_id: int | None = None) -> list[int] | None:
    """解析 ID 列表字符串.

    支持 "this" 简写, 在群聊中代表当前群号.

    Args:
        ids_str: ID 列表字符串, 逗号分隔. "all"/"none"/"*" 表示匹配所有.
        group_id: 当前群组ID, 用于解析 "this".

    Returns:
        list[int] | None: 解析后的 ID 列表, None 表示匹配所有.

    Raises:
        ThisInPrivateChatError: 在私聊中使用了 "this".
    """
    if ids_str is None or ids_str.lower() in ("all", "none", "*"):
        return None
    try:
        result: list[int] = []
        for id_ in ids_str.split(","):
            id_ = id_.strip()
            if not id_:
                continue
            if id_.lower() == "this":
                if group_id is None:
                    raise ThisInPrivateChatError()
                result.append(group_id)
            else:
                result.append(int(id_))
        return result
    except ValueError:
        return []


@CheckerManager.use
@on_command(".", " ", ["checker", "ck"])
async def checker_command(adapter: Adapter, event: MessageEvent, args: CmdArgs):
    """Checker 管理主命令"""
    user_id = event.user_id

    # 权限检查
    if not _check_privilege(user_id):
        await adapter.send_reply("无权使用此指令，需要 Owner 或 Admin 权限")
        return

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
    admins = factory.get_admins()

    priority_display = (
        "先群组后用户"
        if global_settings.rule_priority == "group_first"
        else "先用户后群组"
    )
    lines = [
        "Checker 状态:",
        f"  全局模式: {global_settings.mode}",
        f"  规则优先级: {priority_display} ({global_settings.rule_priority})",
        f"  Owner: {'有' if global_settings.owner else '未设置'}",
        f"  管理员数量: {len(admins)}",
        f"  全局用户规则: {len(global_settings.rules.user_rules)} 条",
        f"  全局群组规则: {len(global_settings.rules.group_rules)} 条",
    ]
    await adapter.send_reply("\n".join(lines))


async def _handle_global(adapter: Adapter, event: MessageEvent, args: list[str]):
    """处理 global 子命令"""
    if not args:
        await adapter.send_reply(
            "全局配置命令:\n"
            ".checker global mode <whitelist|blacklist>\n"
            ".checker global priority <group_first|user_first>\n"
            ".checker global rules [user|group]\n"
            ".checker global add <user|group> <allow|deny> [ids|this]\n"
            ".checker global remove <user|group> <index>\n"
            ".checker global clear [user|group]"
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

        case "priority":
            if not action_args:
                global_settings = _get_factory().global_settings
                await adapter.send_reply(
                    f"当前全局规则优先级: {global_settings.rule_priority}"
                )
                return
            priority = action_args[0].lower()
            if priority not in ("group_first", "user_first"):
                await adapter.send_reply("优先级必须是 group_first 或 user_first")
                return
            async with EditContext(_get_factory()) as ctx:
                ctx.set_global_rule_priority(priority)
            await adapter.send_reply(f"全局规则优先级已设置为: {priority}")

        case "rules":
            global_settings = _get_factory().global_settings
            rule_type = action_args[0].lower() if action_args else None

            if rule_type == "user" or rule_type is None:
                await adapter.send_reply(
                    _format_rules(global_settings.rules.user_rules, "用户")
                )
            if rule_type == "group" or rule_type is None:
                await adapter.send_reply(
                    _format_rules(global_settings.rules.group_rules, "群组")
                )

        case "add":
            if len(action_args) < 2:
                await adapter.send_reply(
                    "用法: .checker global add <user|group> <allow|deny> [ids]"
                )
                return
            rule_type = action_args[0].lower()
            rule_action = action_args[1].lower()
            ids_str = action_args[2] if len(action_args) > 2 else None

            if rule_type not in ("user", "group"):
                await adapter.send_reply("规则类型必须是 user 或 group")
                return
            if rule_action not in ("allow", "deny"):
                await adapter.send_reply("动作必须是 allow 或 deny")
                return

            group_id = _get_group_id(event)
            try:
                ids = _parse_ids(ids_str, group_id=group_id)
            except ThisInPrivateChatError:
                await adapter.send_reply('"this" 只能在群聊中使用, 用于代替当前群号')
                return
            async with EditContext(_get_factory()) as ctx:
                ctx.add_global_rule(rule_type, rule_action, ids)
            ids_display = "所有" if ids is None else ", ".join(map(str, ids))
            await adapter.send_reply(
                f"已添加全局{rule_type}规则: {rule_action} -> {ids_display}"
            )

        case "remove":
            if len(action_args) < 2:
                await adapter.send_reply(
                    "用法: .checker global remove <user|group> <index>"
                )
                return
            rule_type = action_args[0].lower()
            try:
                index = int(action_args[1])
            except ValueError:
                await adapter.send_reply("索引必须是数字")
                return

            if rule_type not in ("user", "group"):
                await adapter.send_reply("规则类型必须是 user 或 group")
                return

            async with EditContext(_get_factory()) as ctx:
                removed = ctx.remove_global_rule(rule_type, index)
            if removed:
                await adapter.send_reply(f"已移除全局{rule_type}规则 [{index}]")
            else:
                await adapter.send_reply(f"索引 {index} 无效")

        case "clear":
            rule_type = action_args[0].lower() if action_args else None
            if rule_type is not None and rule_type not in ("user", "group"):
                await adapter.send_reply("规则类型必须是 user 或 group")
                return
            async with EditContext(_get_factory()) as ctx:
                count = ctx.clear_global_rules(rule_type)
            type_str = f"{rule_type}" if rule_type else "所有"
            await adapter.send_reply(f"已清除 {count} 条全局{type_str}规则")

        case _:
            await adapter.send_reply(f"未知操作: {action}")


async def _handle_admin(adapter: Adapter, event: MessageEvent, args: list[str]):
    """处理 admin 子命令 (仅 Owner 可用)"""
    # 管理员操作仅 Owner 可用
    factory = _get_factory()
    if not factory.is_owner(event.user_id):
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
                for uid in admins:
                    lines.append(f"  • {uid}")
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

            async with EditContext(factory) as ctx:
                success = ctx.add_admin(uid)
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

            async with EditContext(factory) as ctx:
                success = ctx.remove_admin(uid)
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
            ".checker plugin <name> priority <group_first|user_first|inherit>\n"
            ".checker plugin <name> rules [user|group]\n"
            ".checker plugin <name> add <user|group> <allow|deny> [ids|this]\n"
            ".checker plugin <name> remove <user|group> <index>\n"
            ".checker plugin <name> clear [user|group]"
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

        case "priority":
            if not action_args:
                plugin_settings = _get_factory().get_plugin_settings(plugin_name)
                priority_str = plugin_settings.rule_priority or "inherit (继承全局)"
                await adapter.send_reply(
                    f"插件 {plugin_name} 当前规则优先级: {priority_str}"
                )
                return

            priority = action_args[0].lower()
            if priority == "inherit":
                async with EditContext(_get_factory()) as ctx:
                    ctx.set_plugin_rule_priority(plugin_name, None)
            elif priority in ("group_first", "user_first"):
                async with EditContext(_get_factory()) as ctx:
                    ctx.set_plugin_rule_priority(plugin_name, priority)
            else:
                await adapter.send_reply(
                    "优先级必须是 group_first, user_first 或 inherit"
                )
                return
            await adapter.send_reply(
                f"插件 {plugin_name} 规则优先级已设置为: {priority}"
            )

        case "rules":
            plugin_settings = _get_factory().get_plugin_settings(plugin_name)
            rule_type = action_args[0].lower() if action_args else None

            if rule_type == "user" or rule_type is None:
                await adapter.send_reply(
                    f"插件 {plugin_name}\n"
                    + _format_rules(plugin_settings.rules.user_rules, "用户")
                )
            if rule_type == "group" or rule_type is None:
                await adapter.send_reply(
                    f"插件 {plugin_name}\n"
                    + _format_rules(plugin_settings.rules.group_rules, "群组")
                )

        case "add":
            if len(action_args) < 2:
                await adapter.send_reply(
                    f"用法: .checker plugin {plugin_name} add <user|group> <allow|deny> [ids]"
                )
                return
            rule_type = action_args[0].lower()
            rule_action = action_args[1].lower()
            ids_str = action_args[2] if len(action_args) > 2 else None

            if rule_type not in ("user", "group"):
                await adapter.send_reply("规则类型必须是 user 或 group")
                return
            if rule_action not in ("allow", "deny"):
                await adapter.send_reply("动作必须是 allow 或 deny")
                return

            group_id = _get_group_id(event)
            try:
                ids = _parse_ids(ids_str, group_id=group_id)
            except ThisInPrivateChatError:
                await adapter.send_reply('"this" 只能在群聊中使用, 用于代替当前群号')
                return
            async with EditContext(_get_factory()) as ctx:
                ctx.add_plugin_rule(plugin_name, rule_type, rule_action, ids)
            ids_display = "所有" if ids is None else ", ".join(map(str, ids))
            await adapter.send_reply(
                f"已为插件 {plugin_name} 添加{rule_type}规则: {rule_action} -> {ids_display}"
            )

        case "remove":
            if len(action_args) < 2:
                await adapter.send_reply(
                    f"用法: .checker plugin {plugin_name} remove <user|group> <index>"
                )
                return
            rule_type = action_args[0].lower()
            try:
                index = int(action_args[1])
            except ValueError:
                await adapter.send_reply("索引必须是数字")
                return

            if rule_type not in ("user", "group"):
                await adapter.send_reply("规则类型必须是 user 或 group")
                return

            async with EditContext(_get_factory()) as ctx:
                removed = ctx.remove_plugin_rule(plugin_name, rule_type, index)
            if removed:
                await adapter.send_reply(
                    f"已移除插件 {plugin_name} 的{rule_type}规则 [{index}]"
                )
            else:
                await adapter.send_reply(f"索引 {index} 无效")

        case "clear":
            rule_type = action_args[0].lower() if action_args else None
            if rule_type is not None and rule_type not in ("user", "group"):
                await adapter.send_reply("规则类型必须是 user 或 group")
                return
            async with EditContext(_get_factory()) as ctx:
                count = ctx.clear_plugin_rules(
                    plugin_name=plugin_name,
                    rule_type=rule_type,
                )
            type_str = f"{rule_type}" if rule_type else "所有"
            await adapter.send_reply(
                f"已清除插件 {plugin_name} 的 {count} 条{type_str}规则"
            )

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
