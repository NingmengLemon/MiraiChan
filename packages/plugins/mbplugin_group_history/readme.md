# 群史问答

在群里问一句, 模型带着工具去翻 `mbplugin_recorder` 记下的聊天记录, 回答里带发言人与时间。

## 指令

- `.问 <问题>` 检索群历史后回答
- `.画像 <群名片>` 按历史发言给某位群友画人物画像

回答超过 `max_answer_chars` 时自动转成合并转发, 免得刷屏。

## 依赖

- `mbplugin_recorder` 必须加载, 插件通过 `recorder_service` 只读查询; 没加载时指令会直接说查不了。
- 需要一份 `llm` 配置 (`configs/llm/default.json`), 结构与端点池的设计见
  `packages/shared/lemony_llm_provider/design.md`。最少要有一个能用于工具调用的端点:

```json
{
  "default_alias": "chat",
  "aliases": {"chat": ["ds"]},
  "endpoints": {
    "ds": {
      "protocol": "chat",
      "base_url": "https://api.deepseek.com",
      "model": "deepseek-flash",
      "api_key_ref": "llm.ds.api_key",
      "quirks": "deepseek_chat"
    }
  }
}
```

`api_key_ref` 是凭据键名, 由 `lemony_settings.get_secret` 解析: 写进 `credentials.json` 的
`refs["llm.ds.api_key"]`, 或设置环境变量 `MIRAICHAN_LLM_DS_API_KEY`。

## 工具

模型能调用三个只读工具, 都限制在当前群与 `max_window_days` 的窗口内, 并且不计机器人自己的发言:

| 工具 | 作用 |
| --- | --- |
| `search_history` | 按关键词(可多个)与发言者检索消息 |
| `speaker_stats` | 统计一段时间内谁发言最多 |
| `speaker_messages` | 看某个群友最近说了什么 |

## 配置 (configs/group_history/default.json)

| 项 | 默认值 | 说明 |
| --- | --- | --- |
| `alias` | `chat` | 用哪个模型别名 |
| `max_rounds` | 4 | 工具调用最多几轮, 用完就不再给工具, 让模型按已有材料收尾 |
| `max_tokens` | 2048 | 单次回答的输出上限 |
| `window_days` | 30 | 默认回溯天数 |
| `max_window_days` | 365 | 模型能要求的最大回溯天数, 防止全库扫描 |
| `result_limit` | 20 | 单次检索最多返回条数 |
| `max_tool_chars` | 3000 | 单个工具结果回给模型的字符上限 |
| `max_answer_chars` | 800 | 超过就转合并转发 |
| `cooldown_seconds` | 30 | 同群两次提问的最小间隔 |
| `enabled_groups` | 空 | 允许使用的群号, 空表示不限制 |

## 已知限制

- 只读: 不写 recorder 的库, 也不回填任何东西。
- 引用回复暂时不当作时间锚点, 提问窗口完全由工具参数决定。
- 检索是 SQLite 的 `LIKE`, 中文没有分词, 关键词要自己挑。
