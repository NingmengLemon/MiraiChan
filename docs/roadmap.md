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

- 统一资源管理: 多处直接读 `data/...` 相对路径, 依赖 cwd 是项目根。
  - `packages/shared/lemony_onebot_utils/src/lemony_onebot_utils/botutils.py` (头像缓存目录)
  - `packages/plugins/mbplugin_deeeer/core.py` (`no_data.png`)
  - 设想见 `packages/shared/lemony_storage_helper/ideas.md`。
- QQ 信息缓存 (`lemony_onebot_utils/qq.py` 的 `QQInfoCache`): 头像、昵称、群名的缓存, 目前是空壳。
  引用图的 At 名字补全每次现查 `get_group_member_info`, 有了缓存后可以改用它。
- 远程插件加载 (`packages/miraichan/src/miraichan/loader.py`): 按 url 加载插件, 未实现。
- emoji 绘制: 替换 pilmoji, 原因是它不支持自定义源, 且整行只有 emoji 时 y 轴错位
  (`packages/shared/lemony_images/src/lemony_images/emoji.py`)。
- `lemony_settings` 完全异步化 (`core.py`)。
- `lemony_checkers` 的 checker 工厂完全惰性加载 (`factory.py`)。
- `lemony_utils` 的定位与拆分, 见 `packages/shared/lemony_utils/planning.md`。
