"""
Checker Manager 插件

用于让 Owner 和管理员从聊天通过指令管理 lemony_checkers 包中的过滤规则。

指令列表:
    .checker global mode <whitelist|blacklist>  - 设置全局权限模式
    .checker global rules [user|group]          - 查看全局规则
    .checker global add <user|group> <allow|deny> [id1,id2,...] - 添加全局规则
    .checker global remove <user|group> <index> - 移除全局规则
    .checker global clear [user|group]          - 清除全局规则

    .checker admin list                         - 查看管理员列表
    .checker admin add <user_id>                - 添加管理员
    .checker admin remove <user_id>             - 移除管理员

    .checker plugin <name> enable               - 启用插件
    .checker plugin <name> disable              - 禁用插件
    .checker plugin <name> mode <whitelist|blacklist|inherit> - 设置插件权限模式
    .checker plugin <name> rules [user|group]   - 查看插件规则
    .checker plugin <name> add <user|group> <allow|deny> [id1,id2,...] - 添加插件规则
    .checker plugin <name> remove <user|group> <index> - 移除插件规则
    .checker plugin <name> clear [user|group]   - 清除插件规则

    .checker reload [global|<plugin_name>]      - 重新加载配置
    .checker save [global|<plugin_name>]        - 保存配置
    .checker status                             - 查看当前状态
"""

from lemony_checkers import (
    Rule,
    add_admin,
    add_global_rule,
    add_plugin_rule,
    clear_global_rules,
    clear_plugin_rules,
    get_admins,
    # 获取配置
    get_checker_global_settings,
    get_checker_plugin_settings,
    # get_owner,
    is_admin,
    is_owner,
    reload_global_settings,
    reload_plugin_settings,
    remove_admin,
    remove_global_rule,
    remove_plugin_rule,
    # 保存配置
    save_global_settings,
    save_plugin_settings,
    set_global_mode,
    # 全局配置 API
    # 插件配置 API
    set_plugin_enabled,
    set_plugin_mode,
)
from melobot import PluginPlanner, get_logger
from melobot.handle import on_command
from melobot.protocols.onebot.v11 import Adapter
from melobot.protocols.onebot.v11.adapter.event import MessageEvent
from melobot.utils.parse import CmdArgs

CheckerManager = PluginPlanner("1.0.0")
logger = get_logger()


def _check_privilege(user_id: int) -> bool:
    """检查用户是否有权限操作 (owner 或 admin)"""
    return is_owner(user_id) or is_admin(user_id)


def _format_rules(rules: list[Rule], rule_type: str) -> str:
    """格式化规则列表为可读字符串"""
    if not rules:
        return f"暂无{rule_type}规则"

    lines = [f"{rule_type}规则列表:"]
    for i, rule in enumerate(rules):
        ids_str = "所有" if rule.ids is None else ", ".join(map(str, rule.ids))
        lines.append(f"  [{i}] {rule.action.upper():<6}: {ids_str}")
    return "\n".join(lines)


def _parse_ids(ids_str: str | None) -> list[int] | None:
    """解析 ID 列表字符串"""
    if ids_str is None or ids_str.lower() in ("all", "none", "*"):
        return None
    try:
        return [int(id_.strip()) for id_ in ids_str.split(",") if id_.strip()]
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
    global_settings = get_checker_global_settings()
    # owner = get_owner()
    admins = get_admins()

    lines = [
        "Checker 状态:",
        f"  全局模式: {global_settings.mode}",
        # f"  Owner: {owner or '未设置'}",
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
            ".checker global rules [user|group]\n"
            ".checker global add <user|group> <allow|deny> [ids]\n"
            ".checker global remove <user|group> <index>\n"
            ".checker global clear [user|group]"
        )
        return

    action = args[0].lower()
    action_args = args[1:]

    match action:
        case "mode":
            if not action_args:
                global_settings = get_checker_global_settings()
                await adapter.send_reply(f"当前全局模式: {global_settings.mode}")
                return
            mode = action_args[0].lower()
            if mode not in ("whitelist", "blacklist"):
                await adapter.send_reply("模式必须是 whitelist 或 blacklist")
                return
            set_global_mode(mode)  # type: ignore
            save_global_settings()
            await adapter.send_reply(f"全局模式已设置为: {mode}")
        case "rules":
            global_settings = get_checker_global_settings()
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

            ids = _parse_ids(ids_str)
            add_global_rule(rule_type, rule_action, ids)  # type: ignore
            save_global_settings()
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

            removed = remove_global_rule(rule_type, index)  # type: ignore
            if removed:
                save_global_settings()
                await adapter.send_reply(f"已移除全局{rule_type}规则 [{index}]")
            else:
                await adapter.send_reply(f"索引 {index} 无效")

        case "clear":
            rule_type = action_args[0].lower() if action_args else None
            if rule_type and rule_type not in ("user", "group"):
                await adapter.send_reply("规则类型必须是 user 或 group")
                return
            count = clear_global_rules(rule_type)  # type: ignore
            save_global_settings()
            type_str = f"{rule_type}" if rule_type else "所有"
            await adapter.send_reply(f"已清除 {count} 条全局{type_str}规则")

        case _:
            await adapter.send_reply(f"未知操作: {action}")


async def _handle_admin(adapter: Adapter, event: MessageEvent, args: list[str]):
    """处理 admin 子命令 (仅 Owner 可用)"""
    # 管理员操作仅 Owner 可用
    if not is_owner(event.user_id):
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
            admins = get_admins()
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

            if add_admin(uid):
                save_global_settings()
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

            if remove_admin(uid):
                save_global_settings()
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
            ".checker plugin <name> rules [user|group]\n"
            ".checker plugin <name> add <user|group> <allow|deny> [ids]\n"
            ".checker plugin <name> remove <user|group> <index>\n"
            ".checker plugin <name> clear [user|group]"
        )
        return

    plugin_name = args[0]
    action = args[1].lower()
    action_args = args[2:]

    match action:
        case "enable":
            set_plugin_enabled(plugin_name, True)
            save_plugin_settings(plugin_name)
            await adapter.send_reply(f"插件 {plugin_name} 已启用")

        case "disable":
            set_plugin_enabled(plugin_name, False)
            save_plugin_settings(plugin_name)
            await adapter.send_reply(f"插件 {plugin_name} 已禁用")

        case "mode":
            if not action_args:
                plugin_settings = get_checker_plugin_settings(plugin_name)
                mode_str = plugin_settings.mode or "inherit (继承全局)"
                await adapter.send_reply(f"插件 {plugin_name} 当前模式: {mode_str}")
                return

            mode = action_args[0].lower()
            if mode == "inherit":
                set_plugin_mode(plugin_name, None)
            elif mode in ("whitelist", "blacklist"):
                set_plugin_mode(plugin_name, mode)  # type: ignore
            else:
                await adapter.send_reply("模式必须是 whitelist, blacklist 或 inherit")
                return
            save_plugin_settings(plugin_name)
            await adapter.send_reply(f"插件 {plugin_name} 模式已设置为: {mode}")

        case "rules":
            plugin_settings = get_checker_plugin_settings(plugin_name)
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

            ids = _parse_ids(ids_str)
            add_plugin_rule(plugin_name, rule_type, rule_action, ids)  # type: ignore
            save_plugin_settings(plugin_name)
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

            removed = remove_plugin_rule(plugin_name, rule_type, index)  # type: ignore
            if removed:
                save_plugin_settings(plugin_name)
                await adapter.send_reply(
                    f"已移除插件 {plugin_name} 的{rule_type}规则 [{index}]"
                )
            else:
                await adapter.send_reply(f"索引 {index} 无效")

        case "clear":
            rule_type = action_args[0].lower() if action_args else None
            if rule_type and rule_type not in ("user", "group"):
                await adapter.send_reply("规则类型必须是 user 或 group")
                return
            count = clear_plugin_rules(plugin_name, rule_type)  # type: ignore
            save_plugin_settings(plugin_name)
            type_str = f"{rule_type}" if rule_type else "所有"
            await adapter.send_reply(
                f"已清除插件 {plugin_name} 的 {count} 条{type_str}规则"
            )

        case _:
            await adapter.send_reply(f"未知操作: {action}")


async def _handle_reload(adapter: Adapter, args: list[str]):
    """处理 reload 子命令"""
    if not args:
        reload_global_settings()
        await adapter.send_reply("已重新加载全局配置")
        return

    target = args[0].lower()
    if target == "global":
        reload_global_settings()
        await adapter.send_reply("已重新加载全局配置")
    else:
        reload_plugin_settings(target)
        await adapter.send_reply(f"已重新加载插件 {target} 配置")


async def _handle_save(adapter: Adapter, args: list[str]):
    """处理 save 子命令"""
    if not args:
        save_global_settings()
        await adapter.send_reply("已保存全局配置")
        return

    target = args[0].lower()
    if target == "global":
        save_global_settings()
        await adapter.send_reply("已保存全局配置")
    else:
        save_plugin_settings(target)
        await adapter.send_reply(f"已保存插件 {target} 配置")
