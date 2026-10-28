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

当前收录的条目见 `catalog.py` 的 `EXTENSIONS`; 新增条目时同一条提交里补 `tests/shared/test_onebot_ext.py`
的形状断言。

## 已移除的旧模块

`extended_actions/` 曾把 Lagrange 风格的 action 与 `MfaceSegment` 混在一个文件里, 没有回包类型,
也没有支持范围记录。并入 `onebot_ext` 后:

- action 按家族搬到 `actions.py`, 名字改成动词开头的类名;
- `MfaceSegment` 不再维护, 表情解析用 `lemony_mface`;
- `set_group_special_title` 这类标准 action 删掉, 直接用 melobot 内置方法。

## 实现端支持情况

`impls` 字段当前只覆盖已核对的 SnowLuma (1.14.x)。NapCat 与 Lagrange 的同名 action 大多存在但未逐项实测,
条目里用 `notes` 标注, 不写进 `impls`。使用前用 `find(name)` / `for_impl(impl)` 查表, 不要在插件里
硬编码"某实现端一定支持"。
