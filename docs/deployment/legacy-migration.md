# 从旧实例迁移

目标: 用本仓库 (`dev` 分支, melobot 3.5) 替换线上运行的旧 MiraiChan (`main` 分支 2025-04 版本, melobot 3.2)。
主机地址、账号等现场细节不进仓库, 见本地 gitignored 的 `docs/discussions/legacy-instance-survey.md`。

## 运行形态对照

| 项 | 旧实例 | 新实例 |
| --- | --- | --- |
| 入口 | `python -m melobot run src/bot.py` | `mb run miracle_entrance.py` (`just run`) |
| 环境 | PDM 建的 venv | `uv sync --all-packages` |
| 全局配置 | `config.json` 键 `forwwsio.url` `forwwsio.access_token` `plugins` | `config.json` 键 `websocket.{type,url}` `plugins` `load_depth` `config_root` |
| 凭据 | 与全局配置同文件 (`forwwsio.access_token`) | `credentials.json` 的 `websocket.access_token`, 或环境变量 `MIRAICHAN_WEBSOCKET_ACCESS_TOKEN` |
| 插件配置 | `plugin_config/*_conf.json` | `configs/<identifier>/default.json` 与 `configs/lemony_checkers/*.json` |
| 数据根 | 仓库下 `data/` | 仓库下 `data/` (`lemony_storage_helper.files.set_data_root(project_root / "data")`) |
| OneBot 端 | 正向 ws | 同样支持正向 ws, 实现端可原样复用 |

## 插件对照

| 旧插件 | 新位置 | 状态 |
| --- | --- | --- |
| Deeeer | `mbplugin_deeeer` | 已迁移, 启动时自动转换旧库 (见下) |
| MoeAttriLottery | `mbplugin_moelottery` | 已迁移 |
| Recorder | `mbplugin_recorder` | 已重写, schema 完全不同, 旧库归档 |
| JustQuote, MomoQuote | `mbplugin_quote` | 已重写并合并, 命令 `.q` / `.mq` 保留, `.mq` 参数改为 `x..y` / `-s` / `Nx` |
| Helper | `mbplugin_helper` | 已重写, 帮助由各插件注册, 以合并转发发送 |
| LemonyUtils | `mbplugin_toolbox` (复读、撤回、查看消息数据) 与 `mbplugin_rebootable` (重启、关机) | 已迁移 |
| Pooooke | `mbplugin_toolbox` 的 `.ping` | 只保留 ping, 戳一戳回戳不迁移 |
| EmergencyStop | `mbplugin_rebootable` 的关机指令 | 不单独迁移 |
| VVTTS, WhatToListenToday | `_to_be_migrated/` | 待定 |
| OneBotInfoProvider, Executor, DailyWaifu, ArknightsUtils, RecorderTest | 无 | 放弃 |
| BiliLinkPurify | 无 | 计划以 B 站内容自动解析重做, 见 `docs/roadmap.md` |
| 无 | `mbplugin_checker_manager` `mbplugin_emergency_alerts` | 新增 |

旧实例的权限名单 (`checkers_conf` 的 owner / super_users / white_users / black_users) 需要转写到 `configs/lemony_checkers/global.json`。

## 数据迁移

### deers.db

旧表名 `deerrecord`, 新表名 `deer_record`, 列完全一致 (`id CHAR(32)`, `timestamp`, `user_id`, `group_id`, `combo`)。
旧库 id 由 uuid4 生成, 新代码用 uuid7, 二者都存为 32 位 hex 文本, 可以共存。

插件启动时 `mbplugin_deeeer/migration.py` 在建表事务内自动处理: 旧表改名为 `deer_record` 并补齐三个索引。
两张表同时存在或列不全时报错, 插件不响应, 库保持原样。把旧 `deers.db` 原样放到新部署的
`data/record/deers.db` 即可。迁移已在线上库的副本上演练过, 1814 行改名前后逐行一致。

### messages.db

旧 Recorder 的表 (`message` `messagesegment` `mediafile` `user` `group` `usergrouplink`) 与新 recorder 的
`recorder_*` 表没有对应关系。旧库只读归档, 不导入; 新插件写 `record/recorder.db`, 不会碰旧文件名。

归档副本用 SQLite online backup API 在线取得 (不停服务, 得到一致快照), 已通过 `PRAGMA integrity_check`。

### 其他

- `group_waifus.db` 两张表均为空, 与 messages.db 一并归档。
- `record/quotes/` 是旧引用图产物, 已打包归档 (tar 加逐文件 sha256 清单) 并从线上删除, 新的引用图插件不导入。
- `record/images/` 是旧 Recorder 媒体, 随 messages.db 归档。

## 切换步骤 (草案)

1. 在主机上另起目录部署新仓库, 不改动旧目录。
2. 复制 `data/` 中需要的文件到新目录, 在副本上跑数据转换, 用只读查询核对行数。
3. 写新的 systemd unit, 先停旧服务再起新服务 (两者同时连实现端会重复响应)。
4. 观察日志; 回退方式是停新服务、起旧服务, 旧目录与旧数据全程不动。

## 待决事项

- 服务器上的 `main` 分支 HEAD 不在远端 `main` 上, 切换前先把它推到一个归档分支或打 bundle 备份。
- 旧实例的插件配置 (`plugin_config/`) 中仍然需要的项转写到新的 `configs/`。引用图对应关系:
  `quoter_conf.emoji_cdn` / `momoquote_conf.emoji_cdn` -> `configs/quote/default.json` 的 `emoji_cdn`;
  `banned_stickersets` -> `chat.banned_sticker_sets`; `same_msg_min_dist` -> `limits.same_target_cooldown`;
  `font` 改为相对 data 根的路径; `mask` `saveto` `uploader` 不再使用。
- 切换前用 `tools/fake_onebot_server.py` 在隔离目录里把计划启用的插件组合跑一遍 (见 `docs/development/testing.md`)。
