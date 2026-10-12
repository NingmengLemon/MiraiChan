# 部署手册

从零部署一个新实例, 或用新实例替换旧实例。主机地址、账号等现场信息不写在这里,
放在本地 gitignored 的 `docs/discussions/` 下。

## 前置

- Linux, Python 由 uv 管理 (`requires-python = ==3.12.*`, uv 会自动下载)。
- 一个已经登录、开启正向 ws 的 OneBot v11 实现端。`reportSelfMessage` 关闭即可;
  引用图插件默认忽略 bot 自己的消息, 不依赖这个开关。
- 字体文件 (不在仓库里): `data/fonts/NotoSansSC-Medium.ttf` 与 `data/fonts/sarasa-mono-sc-semibold.ttf`。
- 可选: EmojiServer (引用图里的 emoji 图片)。

## 步骤

1. 取代码并安装依赖:

   ```sh
   git clone -b dev <repo-url> <deploy-dir>
   cd <deploy-dir>
   uv sync --all-packages --frozen
   ```

2. 放字体到 `data/fonts/`。

3. 写 `config.json` (参考 `config.example.json`):

   - `websocket`: `type = forward`, `url` 指向实现端, `access_token` 与实现端一致;
   - `plugins`: 上线的插件, 见下;
   - `log_levels`: 默认留空。

4. 写权限配置 `configs/lemony_checkers/global.json` 的 `owner` / `admins`。
   其余插件配置首次启动时按默认值生成在 `configs/<插件>/default.json`, 需要改的再改:
   - `configs/quote/default.json`: `emoji_cdn` 指向 EmojiServer。

5. 迁移旧数据 (替换旧实例时):
   - `deers.db` 原样复制到 `data/record/deers.db`, 启动时自动转换, 见 `legacy-migration.md`;
   - 旧 Recorder 的 `messages.db` 与旧引用图产物只归档, 不复制。

6. 演练: 在开发机上跑 `uv run python tools/rehearse_e2e.py`, 应当全部通过。

7. 安装 systemd unit: 以 `deploy/miraichan.service.example` 为模板, 填好路径与用户,
   `systemctl daemon-reload` 后 `systemctl enable --now <name>`。

8. 验证: `journalctl -u <name> -f` 看到各插件 `成功加载插件` 与 ws 连接成功;
   在群里试 `.q` / `.mq` / `鹿`。

## 上线插件

```json
[
    "mbplugin_checker_manager",
    "mbplugin_recorder",
    "mbplugin_deeeer",
    "mbplugin_moelottery",
    "mbplugin_rebootable",
    "mbplugin_quote"
]
```

`mbplugin_emergency_alerts` 尚未实现功能, 不启用。

## 替换旧实例

两个实例同时连同一个实现端会对每条消息各回一次, 所以切换时先停旧服务再起新服务。

1. 备份旧实例的代码 (若它的提交不在远端, 打一个 git bundle) 与 `data/`。
2. 按上面的步骤部署新实例, 先不要启动。
3. 停旧服务并禁用开机启动, 再启动新服务。
4. 观察日志与群内表现。

回退: 停新服务, 重新启用并启动旧服务。旧目录与旧数据在整个过程中不动。
