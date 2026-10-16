# 路线图

跟踪还没做的点子与已知的技术债。做完的条目直接删掉, 历史看 `git log`。
条目尽量写清"要什么"和"卡在哪", 细节设计放到对应包的文档里。

## 功能

### 预警 (`mbplugin_emergency_alerts`)

- 历史查询指令: 留档 (`archive.py`) 已经在记, 缺按事件 / 地区 / 时间查询的指令与输出格式。
- 上线: 功能已完成, 尚未加入线上插件列表, 上线前跑 `tools/rehearse_alerts.py`。
- 国家突发事件预警信息发布网: `sources/sneb/` 是接入草稿, 尚未接线。

### 新插件

- 群聊管理: 入群审核等, 设想见 `packages/plugins/mbplugin_group_manager/planning.md`。
- 能不能好好说话 (缩写翻译): 见 `packages/plugins/mbplugin_nbnhhsh/planning.md`。
- LLM 接入: 纯异步 OpenAI 兼容层的可行性分析见 `packages/shared/lemony_llm_provider/planning.md`。
- 待迁移的旧插件: 在 gitignored 的 `packages/plugins/_to_be_migrated/` 下, 逐个评估迁移或放弃。

## 基础设施

- 本地文件管理的后续 (data root 与 `data_path` 已有, 见 `lemony_storage_helper.files`):
  原子写入、内容寻址命名等通用文件操作下沉到 `files`, recorder 的媒体缓存是第一个使用方;
  可覆盖资源 (用户目录优先, 包内资源兜底) 的解析。设想见 `packages/shared/lemony_storage_helper/ideas.md`。
- `data/no_data.png` 已没有代码引用 (deeeer 改用包内 `resources/no_avatar.png`), 确认线上不再需要后删除。
- QQInfoCache 的事件联动: 用消息事件的 sender 调 `remember_member` 预热,
  在群名片变更 / 退群通知里调 `invalidate_member`。目前只靠 TTL 过期。
- 远程插件加载 (`packages/miraichan/src/miraichan/loader.py`): 按 url 加载插件, 未实现。
- emoji 绘制: 替换 pilmoji, 原因是它不支持自定义源, 且整行只有 emoji 时 y 轴错位
  (`packages/shared/lemony_images/src/lemony_images/emoji.py`)。
- `lemony_settings` 完全异步化 (`core.py`)。
- `lemony_checkers` 的 checker 工厂完全惰性加载 (`factory.py`)。
- `lemony_utils` 的定位与拆分, 见 `packages/shared/lemony_utils/planning.md`。
