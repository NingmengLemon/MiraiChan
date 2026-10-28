# 协议边界与多协议准备

现状的协议相关代码集中在 melobot 的 OneBot v11 适配器上。这份文档记录哪些部分已经与协议无关,
哪些是 OneBot 11 专用, 以及新增协议适配器时要动哪里; 后续迁移按这里列出的边界做。
OneBot 侧的扩展清单与实现端差异见 `packages/shared/lemony_onebot_utils/design.md`,
插件门面的设计见 `docs/development/protocol-facade.md`。
melobot 框架侧的协议层能力与限制见 `docs/melobot/protocol-layer.md`: 官方目前只有 OneBot v11 与
Console 两个协议实现, 没有跨协议的消息模型、能力声明或统一出站动作。

## 总览

| 类别 | 位置 | 状态 |
| --- | --- | --- |
| 完全通用 | `lemony_settings`、`lemony_storage_helper`、`lemony_network`、`lemony_images`、`lemony_media`、`lemony_llm_provider`、`lemony_utils` | 不 import melobot 或 onebot, 可直接复用 |
| 协议无关核心 + 可插适配 | `lemony_checkers` | 规则、权限、身份模型是通用的; `adapters/ob11.py` 是 OneBot 身份适配器, 注册在 `registry` 上 |
| 通用启动流程 | `packages/miraichan/src/miraichan/` (CLI、loader、日志桥、配置模型) | 除 IO 接线与配置里的 `websocket` 段外, 与协议无关 |
| OneBot 11 专用 | `lemony_onebot_utils` 的 botutils / forward / onebot_ext、`miraichan/validation_patches/ob11.py`、所有插件的 handler 与消息段处理 | 依赖 v11 的 Adapter / 事件 / 段 / handle |
| QQ 语义专用但协议中立 | `lemony_mface`、`lemony_onebot_utils/qq.py` 里的身份/资料工具 | 处理 QQ 数据语义, 不依赖适配器, Milky 这类 QQ 协议可复用 |

## 插件现状

`packages/plugins/` 下已跟踪的 12 个插件入口全部直接 import `melobot.protocols.onebot.v11`:
`checker_manager`、`deeeer`、`emergency_alerts`、`forward_strip`、`helper`、`mikufans`、`moelottery`、
`provenance`、`quote`、`rebootable`、`recorder`、`toolbox`。另有本地实验插件 `mbplugin_test_forward_msg` 被目录内
`.gitignore` 忽略, 同样绑定 v11, 不计入已跟踪数量。

这是多协议迁移的主要成本所在: handler 的类型注解、消息段拆分、`send_reply`、群号字段都绑定 v11。

## 已知的混合点

1. `miraichan/config.py` 的 `GlobalConfigModel` 只有单个 `websocket` 段
   (forward / reverse 二选一), `main.py` 固定 `add_io(...)` + `add_adapter(Adapter())`。
   多实现端或多协议同时在线需要改成列表并允许每项带 `protocol`。
2. `lemony_checkers` 的主体是通用的, 但 `migration.py` 直接 import ob11 常量, `models.py` 里也写了
   ob11 的 protocol 字面量; 新协议的身份适配应仿照 `adapters/ob11.py`, 同时把这些硬引用收进适配器。
3. 插件把 OneBot 字段当作业务模型: 例如 recorder 存的是 v11 消息段形状, quote / forward_strip 依赖
   `message_id` / `get_msg` / 合并转发结构, provenance 依赖群表情回应。换协议时这些字段没有等价物。
4. `lemony_onebot_utils` 里的 `onebot_ext` 是实现端扩展清单, 天然只服务 OneBot; 但 `qq.py` 等
   QQ 语义工具与协议无关, 可被其他 QQ 协议复用。
5. `melobot_telegram_protocol` 目前只有一个占位 `__init__.py`, 还没有实现。

## 新增协议时的建议顺序

1. 先定义插件用的协议无关门面: 入站 (群/私聊文本事件、发送者、图片与其他消息段) 与出站
   (回复、发消息、发图、撤回、禁言、转发) 两类, 能复用的 melobot 泛型 `Event` / `TextEvent` /
   `Content` 就不再造一套; 设计见 `protocol-facade.md`;
2. 每协议一个 adapter 子包: melobot IO 与 Adapter 接线、事件转换到门面、出站动作实现、
   能力声明 (有没有表情回应、合并转发、群文件等);
3. `lemony_checkers` 补同协议的 `adapters/<protocol>.py`, 提供唯一身份提取;
4. 插件逐步迁移, 由能力声明决定功能隐藏或降级, 不假装支持;
5. 启动配置改成多 IO / 多 adapter, 插件可以声明只在某些协议上启用。

## 实现端现状 (2026-10)

- SnowLuma 与 NapCat 仍在活跃更新, 扩展清单以这两家为核对对象;
- Lagrange 的 OneBot 11 线已冻结: `Lagrange.OneBot` 仓库 404, OneBot 代码只剩 `Lagrange.Core`
  的 `v1` 分支 (最后提交 2025-10-10, README 有终止说明), master 转向 V2/Milky。
  因此 OneBot 扩展清单不把 Lagrange 当活跃目标; 需要兼容存量部署时按冻结源码单独建适配档案,
  `set_group_reaction` 用 `is_add`、没有 `set_msg_emoji_like`、没有 `message_sent`、
  `send_forward_msg` 只上传资源不发送。
- 这意味着 Milky 适配器不只是"再加一个协议", 也是 Lagrange 生态的接续方向。
