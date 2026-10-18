# 部署手册

从零部署一个新实例, 或用新实例替换旧实例。主机地址、账号等现场信息不写在这里,
放在本地 gitignored 的 `docs/discussions/` 下。

## 前置

- Linux, Python 由 uv 管理 (`requires-python = ==3.12.*`, uv 会自动下载)。
- 一个已经登录、开启正向 ws 的 OneBot v11 实现端。`reportSelfMessage` 关闭即可;
  引用图插件默认忽略 bot 自己的消息, 不依赖这个开关。
- 字体文件 (不在仓库里): `data/fonts/NotoSansSC-Medium.ttf` 与 `data/fonts/sarasa-mono-sc-semibold.ttf`。
- 可选: 彩色 emoji 字体 (推荐, 绝大多数 emoji 就不必再下载图片) 或 EmojiServer。
  Debian 装 `fonts-noto-color-emoji` 后把 `/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf`
  拷进 `data/fonts/` 即可 (trixie 的 2.051 版实测是 CBDT 位图字体, 只有 109px 一档,
  Pillow 能画)。COLRv1 的彩色字体 Pillow 画不出来, 放进去会在启动时告警。
  字体里缺的字形仍然会去 `emoji_cdn` 取, 两边都配也可以。

## 步骤

1. 取代码并安装依赖:

   ```sh
   git clone -b dev <repo-url> <deploy-dir>
   cd <deploy-dir>
   uv sync --all-packages --frozen
   ```

2. 放字体到 `data/fonts/`。插件自带的静态资源可以用同名文件覆盖: 放进
   `data/resources/<identifier>/` 即可 (`identifier` 是不带 `mbplugin_` 前缀的插件名,
   例如 `data/resources/quote/placeholder.png`、`data/resources/deeeer/no_avatar.png`),
   没放时用包内自带的那份。按参数画的图 (例如引用图的卡片遮罩) 没有这份资源,
   改插件的配置项即可。

3. 写 `config.json` (参考 `config.example.json`):

   - `websocket`: `type = forward`, `url` 指向实现端 (access token 不放这里, 见下一步);
   - `plugins`: 上线的插件, 见下;
   - `log_levels`: 默认留空。

4. 写凭据: 在项目根建 `credentials.json` (权限 0600), 把 access token 填进去:

   ```json
   {
       "version": 1,
       "refs": {
           "websocket.access_token": "与实现端一致的值"
       }
   }
   ```

   启动时如果文件不存在会自动建一份空模板, 线上建议先建好再启动。文件对同组或其他用户可读
   (例如手工 `cp` 出来的 644) 时启动会直接失败并提示 `chmod 600`, Windows 上没有可检查的
   权限位所以跳过; 没有 `version` 的旧平铺写法仍然可读。也可以不落文件, 用环境变量
   (unit 里 `Environment=MIRAICHAN_WEBSOCKET_ACCESS_TOKEN=...`, 或 `EnvironmentFile=`),
   环境变量优先于凭据文件。凭据文件要换位置时用环境变量 `MIRAICHAN_CREDENTIALS_PATH`:
   `mb run` 只透传入口文件, 传不进 CLI 参数; 直接跑 `miraichan launch --credentials-path ...`
   可以指定, 但那样没有 `.重启` 能力 (`mb run` 才提供)。配置文件与凭据文件分开存放, 所以
   `config.json` 可以放心分享 / 进备份。旧实例的 `config.json` 里如果还留着
   `websocket.access_token`, 启动时会打警告, 迁到凭据文件后删掉即可。

5. 写权限配置 `configs/lemony_checkers/global.json` 的 `owner` / `admins`。
   其余插件配置首次启动时按默认值生成在 `configs/<插件>/default.json`, 需要改的再改:
   - `configs/quote/default.json`: `emoji_font` 指向 `data/fonts/NotoColorEmoji.ttf`,
     或 `emoji_cdn` 指向 EmojiServer。

6. 迁移旧数据 (替换旧实例时):
   - `deers.db` 原样复制到 `data/record/deers.db`, 启动时自动转换, 见 `legacy-migration.md`;
   - 旧 Recorder 的 `messages.db` 与旧引用图产物只归档, 不复制。

7. 演练: 在开发机上跑 `uv run python tools/rehearse_e2e.py`, 应当全部通过。

8. 安装 systemd unit: 以 `deploy/miraichan.service.example` 为模板, 填好路径与用户,
   `systemctl daemon-reload` 后 `systemctl enable --now <name>`。模板里的 `KillMode=mixed`
   是为了避开 `mb run` 偶发的重复 SIGTERM 问题 (systemd 的 cgroup 停止加上 uv 的信号转发),
   上游修复后可以去掉。

9. 验证: `journalctl -u <name> -f` 看到各插件 `成功加载插件` 与 ws 连接成功;
   在群里试 `.q` / `.mq` / `鹿`。

## 日志与日常操作

bot 由 systemd 管理, 输出进 journald (不再有单独的日志文件)。`<name>` 是 unit 名:

| 想做的事 | 命令 |
| --- | --- |
| 实时跟日志 (相当于 `pm2 logs`) | `journalctl -u <name> -f` |
| 最近 200 行 | `journalctl -u <name> -n 200 --no-pager` |
| 某个时间段 | `journalctl -u <name> --since "2026-10-13 00:00" --until "1 hour ago"` |
| 本次启动以来 | `journalctl -u <name> -b` |
| 只看警告和错误 | `journalctl -u <name> -p warning` 无效 (bot 日志都以 info 级别写入 journald), 用 `journalctl -u <name> --no-pager \| grep -E ' (WARNING\|ERROR) '` |
| 状态 (相当于 `pm2 status`) | `systemctl status <name>` |
| 重启 / 停止 / 启动 | `systemctl restart <name>` / `stop` / `start` |
| 开机自启开关 | `systemctl enable <name>` / `disable` |

日志里带 ANSI 颜色码, 用 `less -R` 查看, 或 `journalctl ... -o cat | sed 's/\x1b\[[0-9;]*m//g'` 去掉。
非 root 用户读 journal 需要在 `systemd-journal` 组里。

群里 owner 发 `.重启` / `.关机` 也可以, 前者由 `mb run` 拉起新进程, 后者正常退出 (unit 不会自动拉起)。
`.重启` 完成后会在原会话报告耗时, 以及和重启前相比代码提交、插件增减与插件版本的变化。

## 上线插件

```json
[
    "mbplugin_checker_manager",
    "mbplugin_recorder",
    "mbplugin_deeeer",
    "mbplugin_moelottery",
    "mbplugin_rebootable",
    "mbplugin_quote",
    "mbplugin_helper",
    "mbplugin_emergency_alerts",
    "mbplugin_toolbox",
    "mbplugin_provenance"
    // agent 插件需要额外配置 (configs/llm/default.json 与联网凭据), 配好之后再打开
    // "mbplugin_group_history",
    // "mbplugin_readcheck"
]
```

`mbplugin_emergency_alerts` 的推送行为改动后, 升级前先在开发机上跑
`uv run python tools/rehearse_alerts.py`。它的留档数据库在 `data/emergency_alerts/`。

`config.json` 由 json5 读取, 所以可以写注释; 上面两条 agent 插件默认注释掉:
`mbplugin_group_history` 要一份能调工具的 `llm` 配置, `mbplugin_readcheck` 还要联网检索的凭据
(键名 `readcheck.tools.api_key`)。没配就打开, 指令只会回一句"暂时不可用"。

## 升级已有实例

停服升级, 不做热更新:

1. 在实例目录确认工作区干净, `git fetch` 后确认当前提交是 `origin/dev` 的祖先 (可以快进)。
2. 看一眼两个提交之间的改动: 表结构 (`db/models.py`) 有变化时先在数据副本上演练迁移;
   `config.example.json` 的插件列表有变化时同步到 `config.json`。
3. `systemctl stop <name>`。
4. 备份 `data/` (可排除 `data/fonts`)、`configs/`、`config.json` 与 `credentials.json` (如果用了凭据文件),
   记下旧提交号, 校验备份包的 SHA256。
5. 以部署用户 `git merge --ff-only origin/dev`, 再 `uv sync --all-packages --frozen`。
6. 按需改 `config.json` 或凭据文件, 然后 `systemctl start <name>`, 按上面"验证"一步看日志。

回退: 停服, `git reset --hard <旧提交>`, `uv sync --all-packages --frozen`, 把备份解回实例目录, 再启动。

## 替换旧实例

两个实例同时连同一个实现端会对每条消息各回一次, 所以切换时先停旧服务再起新服务。

1. 备份旧实例的代码 (若它的提交不在远端, 打一个 git bundle) 与 `data/`。
2. 按上面的步骤部署新实例, 先不要启动。
3. 停旧服务并禁用开机启动, 再启动新服务。
4. 观察日志与群内表现。

回退: 停新服务, 重新启用并启动旧服务。旧目录与旧数据在整个过程中不动。
