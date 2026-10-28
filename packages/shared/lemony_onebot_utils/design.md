# lemony_onebot_utils 实现端扩展层

OneBot 11 标准之外, 实现端 (SnowLuma / NapCat / Lagrange) 各自加了一批 action、event 与 segment。
melobot 只内置标准部分, 插件以前各写各的 `{"action": ...}` 字典, 参数形状、返回结构、失败处理都散落
在各处。`onebot_ext` 把这些收拢成三层:

| 层 | 内容 | 面向谁 |
| --- | --- | --- |
| `catalog` | 扩展清单: 名称、kind、参数/字段、有证据支持的实现端、来源 | 查资料、写文档、判断能不能用 |
| `actions` / `events` | 类型化封装: 关键字参数、回包解析 | 插件开发者日常调用 |
| `base` | `ExtensionAction`、`call_extension`、`try_extension`、`ExtensionError` | 统一发送与失败语义 |

## 用法

```python
from lemony_onebot_utils.onebot_ext import SetGroupReaction, try_extension

# 不支持就返回 None, 由调用方退回别的表现
if await try_extension(adapter, SetGroupReaction(
    group_id=1, message_id=2, code="424", is_set=True
)):
    ...
```

```python
from lemony_onebot_utils.onebot_ext import GroupMsgEmojiLike, is_message_sent

if (liked := GroupMsgEmojiLike.from_raw(event.raw)) is not None:
    ...
```

`call_extension` 失败抛 `ExtensionError` (带 action 名与 retcode); `try_extension` 只返回 `None`。
扩展 action 不是标准, 实现端不一定支持, 需要降级的地方一律用 `try_extension`。

## 收录规则

1. 只把**看过源码或实测过**的实现端写进 `impls`, 传闻写进 `notes`;
2. 参数、字段、响应形状以实现端源码为准, 不在同一 action 上猜两种拼写;
3. 每个 action 的参数形状用 `TypedDict` 或显式关键字参数固定下来, 不直接把 `dict` 透传;
4. 回包有结构 (历史消息、精华消息、收藏表情) 时加专用 `Echo`, 否则用通用 `Echo`;
5. 扩展 segment 先登记到 `catalog`, 需要真正解析时再写类型 (表情优先用 `lemony_mface`)。

## 数据与校验

收录清单是数据, 不是代码:

- `onebot_ext/resources/extensions.json`: 条目数组, 字段为 `name` / `kind` / `summary` /
  `impls` / `notes` / `source`;
- `onebot_ext/resources/extensions.schema.json`: JSON Schema (draft 2020-12), 约束 kind 枚举、
  `impls` 只能是已知实现端、名字格式与未知字段;
- `catalog.py` 用 `importlib.resources` 读取包内资源, 转成 `ExtensionSpec`; `EXTENSIONS` /
  `SPECS` / `find` / `for_impl` 的 API 不变, 插件侧不感知数据来源。

加载时只做轻量检查 (顶层类型、`kind` 枚举、重名), 校验失败直接抛错; 完整的 schema 校验放在
`tests/shared/test_onebot_ext.py`, 用 `jsonschema` 作为测试依赖, 运行时不引入这个依赖。

新增条目的步骤: 改 JSON -> 在 `tests/shared/test_onebot_ext.py` 补形状断言 (需要类型化时再加
action 类与 echo) -> 跑 `uv run pytest tests/shared/test_onebot_ext.py`。

## 已移除的旧模块

`extended_actions/` 曾把 Lagrange 风格的 action 与 `MfaceSegment` 混在一个文件里, 没有回包类型,
也没有支持范围记录。并入 `onebot_ext` 后:

- action 按家族搬到 `actions.py`, 名字改成动词开头的类名;
- `MfaceSegment` 不再维护, 表情解析用 `lemony_mface`;
- `set_group_special_title` 这类标准 action 删掉, 直接用 melobot 内置方法。

## 实现端支持情况

清单目前合并了两个实现端的源码核对结果: SnowLuma v2.2.1 (`8ffd3142`) 与 NapCat v4.18.41
(`ba0a53dd`), 核对日期 2026-10-28。`impls` 只写有源码位置或实测证据的实现端; 未核实的实现端
（例如当时的 Lagrange）先留空, 补证据后再加。

同名扩展的参数或返回差异写在该条目的 `notes` 里, 最需要注意的是:

- `set_group_reaction` 只有 SnowLuma 实现, NapCat 没有; NapCat 发送表情回应只能用
  `set_msg_emoji_like`;
- 表情回应的 `emoji_id` / `code` 是同一套编号: 1 到 3 位数字是 QQ 系统表情编号, 4 位及以上是
  Unicode 码位（SnowLuma 协议层按字符串长度判定）;
- `message_sent` 两家都默认不推送, 需要实现端打开 `reportSelfMessage`;
- `group_msg_emoji_like` 的字段不同: SnowLuma 用 `sub_type=add/remove` 与 `operator_id`,
  NapCat 用 `is_add`, 没有 `sub_type`/`operator_id`;
- 历史消息起始游标不同: SnowLuma 用 `message_id`, NapCat 用 `message_seq`;
- `mface` 在 NapCat 只在发送时出现, 接收时是 `image` 段挂 `emoji_id`/`emoji_package_id`/`key`;
- 闪传段命名不同: SnowLuma 是 `flash_file` + `file_set_id`, NapCat 是 `flashtransfer` + `fileSetId`;
- `get_forward_msg` 虽不在扩展清单里（标准 action）, 但两家返回形状不同: SnowLuma 是
  `{messages: [消息事件]}`, NapCat 是 `{messages: [node]}`;
- `poke` 与 `forward` 属于 OneBot 11 标准消息段, 不登记为扩展。

使用前用 `find(name)` / `for_impl(impl)` 查表, 不要在插件里硬编码"某实现端一定支持"。
