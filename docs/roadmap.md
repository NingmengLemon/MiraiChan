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
- AI 生成内容核验: 引用一条消息, 把消息里的图片发给 OpenAI 的
  `POST /v1/content_provenance_checks` (文档:
  https://developers.openai.com/api/docs/guides/content-provenance) 检查是否带 C2PA 清单
  或 SynthID 水印, 把 `c2pa` / `synthid` 两项的 outcome 与 issuer / model 回给用户。
  要点: 请求同步返回, 不需要轮询或先上传到 Files API; 图片返回 c2pa 与 synthid, 音频只有
  synthid; `not_detected` 只说明没找到 OpenAI 支持的信号, 不代表一定不是 AI 生成。需要 OpenAI
  API key, 按凭据分离的方案单独存放。
- "手性碳验证码": 新成员入群时出题验证 (给出分子结构, 找出手性碳), 可以和群聊管理的入群审核放在一起。
- 待定的旧插件: gitignored 的 `packages/plugins/_to_be_migrated/` 下还有 VVTTS (语音合成) 与
  WhatToListenToday, 以及 VVTTS 依赖的 `lemony_utils_legacy` (拼音转片假名)。

## 基础设施

- 本地文件的读改写互斥 (`file_lock`): `atomic_write_*` 只保证读到完整的一次写入, 不含互斥,
  等出现真正的读改写消费者 (文件索引、资源覆盖表这类) 时再加, 用已在依赖里的 `filelock`,
  `.lock` 后缀与 `lemony_settings` 对齐。内容寻址命名与可覆盖资源解析已在
  `lemony_storage_helper.files` (`content_path` / `resource_path`)。
- QQInfoCache 的事件联动: 用消息事件的 sender 调 `remember_member` 预热,
  在群名片变更 / 退群通知里调 `invalidate_member`。目前只靠 TTL 过期。
- 远程插件加载 (`packages/miraichan/src/miraichan/loader.py`): 按 url 加载插件, 未实现。
- `lemony_settings` 完全异步化 (`core.py`)。
- `lemony_checkers` 的 checker 工厂完全惰性加载 (`factory.py`)。
- `lemony_utils` 的定位与拆分, 见 `packages/shared/lemony_utils/planning.md`。
