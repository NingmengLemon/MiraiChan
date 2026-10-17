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

- 本地文件管理的后续 (data root、`data_path` 与原子写入已有, 见 `lemony_storage_helper.files`):
  内容寻址命名等通用文件操作下沉 (recorder 的媒体缓存已经有安全后缀、魔数判断与 sha256 命名,
  可以搬过去); 可覆盖资源 (用户目录优先, 包内资源兜底) 的解析。设想见
  `packages/shared/lemony_storage_helper/ideas.md`。
- 凭据与配置分离: 凭据 (根 `config.json` 里 OneBot 11 的 `access_token`, 以后的 API key 等)
  单独存放, 普通配置可以放心分享 / 进备份 / 给人看; 凭据文件权限收紧, 也可以从环境变量读。
  `lemony_settings` 生成的插件配置同理。
- QQInfoCache 的事件联动: 用消息事件的 sender 调 `remember_member` 预热,
  在群名片变更 / 退群通知里调 `invalidate_member`。目前只靠 TTL 过期。
- emoji 排版规则有两份: `lemony_images.layout` 与 `mbplugin_quote.render.text` 各算一遍
  方块宽度与行高 (前者已换成 `ascent+descent`、后者是 `max(ascent+descent, 字号)`,
  已经开始分叉), `fit_to_square` 也只共用了一半。要么让引用图直接用前者的排版,
  要么把测量规则抽成一处。
- 重启前后的状态 diff: `.重启` 完成后, 除了耗时 (`mbplugin_rebootable`), 再报告和重启前相比
  插件的增减、版本与提交的变化等。需要在重启前把这些状态和 `reboot_info.json` 一起记下来。
- 远程插件加载 (`packages/miraichan/src/miraichan/loader.py`): 按 url 加载插件, 未实现。
- `text_to_image` 不渲染 emoji (只有 `draw_multiline_text_auto` 接了 `ColorFontEmoji`),
  emoji 会落成正文字体里的方框。
- `lemony_settings` 完全异步化 (`core.py`)。
- `lemony_checkers` 的 checker 工厂完全惰性加载 (`factory.py`)。
- `lemony_utils` 的定位与拆分, 见 `packages/shared/lemony_utils/planning.md`。
