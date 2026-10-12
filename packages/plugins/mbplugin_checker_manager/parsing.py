"""checker 管理指令的 ID 约束解析.

单独成模块是为了脱离 melobot 上下文测试: ``__plugin__.py`` 在模块级注册插件与指令,
测试里不能导入它.
"""

from typing import Any

#: 与省略 ids 参数同义的输入, 表示匹配所有用户
MATCH_ALL_ALIASES = frozenset({"all", "none", "*"})


class ThisInPrivateChatError(Exception):
    """在私聊中使用了 'this' 简写"""


class ConstraintParseError(ValueError):
    """解析约束条件时出错 (非法的 ID 格式)"""


def join_id_tokens(tokens: list[str]) -> str:
    """把被空白拆散的 ids 参数拼回一个字符串.

    melobot 的命令解析按空白分词, 因此 ``.checker global add deny 123, 456`` 传进来的是
    ``["123,", "456"]``. 旧实现只取 ``tokens[0]``, ``456`` 会被静默丢弃, 落库的规则与
    用户预期不符.

    Args:
        tokens: ids 参数位置之后的全部命令分词

    Returns:
        用逗号连接的 ID 串; 分词两端的逗号被去掉, 只由逗号组成的分词被忽略
    """
    return ",".join(p for p in (t.strip().strip(",") for t in tokens) if p)


def parse_constrains(
    ids_str: str | None, *, group_id: int | None = None
) -> list[dict[str, list[Any]]] | None:
    """解析约束条件字符串.

    支持格式: "123456" (user_id), "123456:789012" (user_id:group_id),
    "this" (当前群号), "all"/"none"/"*" 或省略参数表示匹配所有.

    Args:
        ids_str: 待解析的 ID 串; None 表示匹配所有
        group_id: 当前群号, 用于展开 "this"

    Returns:
        约束列表, 每项内部字段之间为 AND, 多项之间为 OR; None 表示匹配所有用户

    Raises:
        ThisInPrivateChatError: 在私聊中使用了 "this"
        ConstraintParseError: 未解析出任何有效 ID, 或 ID 格式无效
    """
    if ids_str is None or ids_str.strip().lower() in MATCH_ALL_ALIASES:
        return None

    result: list[dict[str, list[Any]]] = []
    for part in (p.strip() for p in ids_str.split(",")):
        if not part:
            # 容忍多余逗号 (如 "123,"), 但整串都是空项时下面会报错
            continue
        if part.lower() == "this":
            if group_id is None:
                raise ThisInPrivateChatError()
            result.append({"group_id": [group_id]})
        elif ":" in part:
            uid_str, gid_str = part.split(":", 1)
            try:
                uid = int(uid_str)
            except ValueError:
                raise ConstraintParseError(f"无法解析 user_id: {uid_str!r}") from None
            constraint: dict[str, list[Any]] = {"user_id": [uid]}
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

    if not result:
        # 解析不出任何 ID 时必须报错: 旧实现此处返回 None, 于是一个笔误 (如 ",") 会变成
        # "匹配所有" 的无条件规则, 权限范围被悄悄放大
        raise ConstraintParseError(
            f"未解析出任何有效 ID: {ids_str!r}; 省略该参数才表示匹配所有"
        )
    return result
