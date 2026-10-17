# 路线图

跟踪还没做的点子与已知的技术债。做完的条目直接删掉, 历史看 `git log`。
条目尽量写清"要什么"和"卡在哪", 细节设计放到对应包的文档里。

## 功能

### 预警 (`mbplugin_emergency_alerts`)

- 历史查询指令: 留档 (`archive.py`) 已经在记, 缺按事件 / 地区 / 时间查询的指令与输出格式。
- 国家突发事件预警信息发布网: `sources/sneb/` 是接入草稿, 尚未接线。

### 新插件

- 群聊管理: 入群审核等, 设想见 `packages/plugins/mbplugin_group_manager/planning.md`。
- 能不能好好说话 (缩写翻译): 见 `packages/plugins/mbplugin_nbnhhsh/planning.md`。
- LLM 接入: 纯异步 OpenAI 兼容层的可行性分析见 `packages/shared/lemony_llm_provider/planning.md`。
- B 站内容自动解析: 群里出现 B 站链接 / 小程序卡片 / BV 号时自动解析出标题、UP 主、简介等,
  并去掉分享链接里的跟踪参数 (旧实例的 BiliLinkPurify 插件做的就是后者)。
- "手性碳验证码": 新成员入群时出题验证 (给出分子结构, 找出手性碳), 可以和群聊管理的入群审核放在一起。
- 待定的旧插件: gitignored 的 `packages/plugins/_to_be_migrated/` 下还有 VVTTS (语音合成) 与
  WhatToListenToday, 以及 VVTTS 依赖的 `lemony_utils_legacy` (拼音转片假名)。

## 基础设施

- 本地文件的读改写互斥 (`file_lock`): `atomic_write_*` 只保证读到完整的一次写入, 不含互斥,
  等出现真正的读改写消费者 (文件索引、资源覆盖表这类) 时再加, 用已在依赖里的 `filelock`,
  `.lock` 后缀与 `lemony_settings` 对齐。内容寻址命名与可覆盖资源解析已在
  `lemony_storage_helper.files` (`content_path` / `resource_path`)。
- 插件配置里的秘密字段: 目前靠约定 (凭据进 `credentials.json`, 插件用 `lemony_settings.get_secret`
  读), 没有强制手段。`BaseSettings` 里若声明 `Secret[str]` 字段, `save()` 时 `model_dump()` 给的是
  `SecretStr` 对象, json / yaml 写入会直接失败。等真有插件需要在配置模型里声明密钥时, 再决定是
  save 时拒写 / 脱敏, 还是继续只走凭据存储。
- 凭据层的可选加固 (参考 DSH 的凭据 seam, 本项目只保留文件 + 环境变量): `describe()` 式只读
  元信息 (configured / source / writable, 不返回值) 与子进程环境清洗 (`KEY|PASSWORD|SECRET|TOKEN`
  这类变量名)。前者等 runbook 真需要排查凭据来源时再做, 后者等 bot 开始 spawn 外部程序时再加。
- QQInfoCache 的事件联动: 用消息事件的 sender 调 `remember_member` 预热,
  在群名片变更 / 退群通知里调 `invalidate_member`。目前只靠 TTL 过期。
- 远程插件加载 (`packages/miraichan/src/miraichan/loader.py`): 按 url 加载插件, 未实现。
- `lemony_settings` 完全异步化 (`core.py`)。
- `lemony_checkers` 的 checker 工厂完全惰性加载 (`factory.py`)。
- `lemony_utils` 的定位与拆分, 见 `packages/shared/lemony_utils/planning.md`。
