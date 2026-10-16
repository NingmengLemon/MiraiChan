# mbplugin_emergency_alerts

接入 [Wolfx WebSocket API](https://wolfx.jp/zh/docs/websocket/), 把地震预警与地震速报按订阅推送到群聊或私聊。
信息仅供参考, 以官方发布为准。

## 订阅

每个会话 (一个群, 或与某人的私聊) 一份订阅。群里修改订阅需要群管理员或 bot 管理员, 私聊里本人即可;
查看状态任何人都可以。发送 `.预警` 查看完整用法。

筛选条件:

- 种类: 地震预警 / 地震速报
- 数据源: 见 `.预警 来源`, 默认全部
- 地区: 关键词, 与震源地做子串匹配; 日本气象厅的报文额外带 "日本" 标签, 可以用 "日本" 订阅
- 严重程度: 最小震级 (默认 4.0), 可选最小烈度 (只作用于中国源) 与最小震度 (只作用于日本源)
- 预警更新: 一次地震的预警会连发多报, 可选只推首报、首报加最终报 (默认)、每一报都推

"首报" 指该事件第一次达到阈值的那一报, 所以震级在后续报中上调过线时仍会推送。
取消报只推给之前收到过该事件的会话。

## 推送规则

- 同一报 (数据源, 事件, 报数) 只处理一次, 多条连接带来的重复报文会被丢弃
- 发报时间早于阈值的报文不推 (预警 10 分钟, 速报 60 分钟), 避免重连后推送旧地震
- 训练报不推
- 启动时从留档恢复最近一天的去重状态, 重启后不会重复推送同一报或同一事件

## 留档

`data/emergency_alerts/alerts.db` 记录收到的每一报 (含原文, 包括训练报、过期报和没有推送的报)
以及每一次推送的结果。同一报只存一份。时间以 UTC 存储。
留档库启动或写入失败只记日志, 不影响推送, 但重启后去重状态会丢失。
历史查询指令尚未实现。

## 配置

`configs/emergency_alerts/default.json`:

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `ws_base_url` | `wss://ws-api.wolfx.jp` | 本地调试可指向 `tools/mock_wolfx_server.py` |
| `endpoints` | `all_eew` `cenc_eqlist` `jma_eqlist` | 每个端点一条连接 |
| `eew_max_age_minutes` / `report_max_age_minutes` | 10 / 60 | 过期阈值 |
| `idle_timeout` | 150 | 这么多秒没有任何报文 (服务端每分钟发心跳) 就重连 |
| `send_interval` | 0.5 | 推送到多个会话时的发送间隔 |

订阅保存在 `configs/emergency_alerts/subscriptions.json`。

## 本地调试

`tools/mock_wolfx_server.py` 模拟 Wolfx, 建连后只发心跳, 用 `POST /_mock/push` 触发推送。
`tools/rehearse_alerts.py` 用它和假 OneBot 服务端跑一遍真实 bot, 检查订阅、权限与推送。

`sources/sneb/` 是国家突发事件预警信息发布网的接入草稿, 尚未接线。
