# mbplugin_toolbox

给 owner 与管理员用的小工具。没有权限时 bot 不回应。

| 指令 | 权限 | 作用 |
| --- | --- | --- |
| `.ping` | 管理员 | bot 在线时回复 `pong` |
| `.echo` | owner | 回复一条消息, bot 原样再发一遍; 卡片消息 (json / xml 段) 会被去掉 |
| `.withdraw` | owner | 回复一条消息, 尝试撤回它; 只在失败时回复 |
| `.getmsg` / `.get` | owner | 回复一条消息, 以合并转发查看 `get_msg` 返回的原始数据 (JSON, 超长时拆成多个节点); 合并转发发不出去时退回普通消息 |

管理员与 owner 的名单来自 `configs/lemony_checkers/global.json`。
