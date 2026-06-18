# mbplugin_recorder 原型说明

## 当前结构

recorder 现在分为五层：

- `db.models`：SQLModel 表结构，包含账号、外部身份、会话、成员事件、通用通知、原始事件、消息、消息段、媒体对象、媒体来源和媒体附件。
- `db.dto`：协议适配层输入 DTO，不暴露 ORM 实体给 adapter。
- `db.enums`：跨 ORM / DTO / worker 共享的状态枚举，例如媒体下载状态。
- `db.operations`：写入投影与媒体状态流转。
- `service`：面向其他插件的查询服务，通过 melobot IPC `recorder_service` share 暴露。
- `worker` / `media`：后台媒体下载、内容识别、内容寻址缓存落盘。

## 写入路径

消息事件：

1. OneBot11 adapter 将 `MessageEvent` 转为 `RecordedMessageInput`。
2. `record_message()` 写入 account / conversation / sender / raw event / message / segments / media sources。
3. 后台媒体 worker 扫描 pending / failed media source，下载到 UUID `.download` 临时文件。
4. 下载完成后按内容计算 `sha256`、用 `puremagic` 识别真实后缀和 MIME，再以内容 hash 命名缓存文件并更新 `MediaObject`。

通知事件：

1. OneBot11 adapter 将所有 `NoticeEvent` 转为 `NoticeInput`，写入 `recorder_notice` 通用时间线。
2. 群成员增减、禁言、管理员变化会额外转为 `MemberEventInput`。
3. `record_member_event()` 写入 raw event、member event，并更新当前 membership snapshot。
4. 群/好友消息撤回 notice 会同步把已记录消息的 `deleted_at` 标记为撤回时间。
5. 群文件上传 notice 会生成 file 类型 `MediaSource`，并关联到通用 notice。

## 查询服务

`RecorderService` 当前提供：

- `get_context_messages()`：围绕一条消息取前后上下文。
- `count_messages_by_sender()`：按发送者统计会话内消息数。
- `find_media_by_sha256()`：按内容 hash 查媒体对象。
- `list_pending_media()`：查看等待或失败待重试的媒体来源。

其他插件可通过 melobot IPC 获取：

```python
service = bot.get_share("mbplugin_recorder", "recorder_service").get()
```

也可通过插件导出的 typing stub 访问：

```python
from mbplugin_recorder import recorder_service
```

## 日志级别约定

- `info`：插件启动/停止、worker 启停、单个媒体下载完成等低频关键状态。
- `debug`：单条消息/通知/成员事件写入、worker 批次扫描等高频流水。
- `warning`：可恢复但需要关注的问题，例如单个媒体来源下载失败并等待重试。
- `exception` / `generic_exc`：数据库不可恢复错误或事件写入异常；数据库结构/连接错误会继续抛出，避免静默丢数据。

## 原型阶段约定

- 不做旧数据库迁移，表结构可继续破坏式调整。
- 通用 notice 投影默认保留完整 `raw` 到 `Notice.detail.raw`，便于支持非标 OneBot11 notice；例如 `group_msg_emoji_like` 会记录 `message_id`、`likes`、`is_add` 等原始字段。
- SQLite 读回的 `DateTime(timezone=True)` 可能丢失 `tzinfo`，业务比较时统一把 naive datetime 当作 UTC。
- 媒体下载目前是轻量后台轮询，失败后保留为 `failed`，下轮仍会重试。
- 媒体下载状态使用 `MediaDownloadStatus` 枚举约束，SQLite 中仍存储字符串值。
- 媒体缓存以 `sha256` 内容寻址；临时文件仅使用 UUID `.download` 名称，完成后原子替换为最终路径。
- URL / file id 后缀仅作为 fallback，`.suf` 和可执行脚本类后缀不会被信任。

## 下一步

- 为请求事件（好友申请、加群邀请/申请）增加通用投影。
- 为 SQLite 增加 WAL / busy timeout 启动参数。
- 增加真实数据库集成测试，覆盖消息幂等、成员事件、媒体状态流转和 IPC 查询。
