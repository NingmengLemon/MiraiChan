# 精读与核查

两条 agent 指令, 都基于 `lemony_llm_provider` 的端点池与工具循环:

- `.读 <链接|正文>` 精读: 一句话结论 + 三个要点 + 值得注意的地方 + 适合谁看
- `.核 <说法>` 事实核查: 拆子命题、判时效、检索取证, 每条结论带来源与日期, 结尾写"以上信息截至 <日期>"

回答超过 `max_answer_chars` 时转成合并转发。

## 依赖

- `llm` 配置 (`configs/llm/default.json`), 见 `packages/shared/lemony_llm_provider/design.md`
- 联网检索与抓取走 DeepSeek 的工具接口 (`/v1/tools/search`、`/v1/tools/fetch`), 用同一个 key:
  - 凭据键名默认 `readcheck.tools.api_key`
  - 写进 `credentials.json`, 或设置环境变量 `MIRAICHAN_READCHECK_TOOLS_API_KEY`

## 工具

| 工具 | 作用 |
| --- | --- |
| `web_search` | 联网检索, 返回标题、链接与摘要 |
| `fetch_page` | 抓取网页正文 |

`.读` 收到链接时会先抓一次正文(失败就交给模型自己抓); 收到长文时直接截断后带进提问。

## 配置 (configs/readcheck/default.json)

| 项 | 默认值 | 说明 |
| --- | --- | --- |
| `alias` | `chat` | 用哪个模型别名 |
| `base_url` | `https://api.deepseek.com` | 检索与抓取接口地址 |
| `api_key_ref` | `readcheck.tools.api_key` | 联网接口的凭据键名 |
| `timezone` | `Asia/Shanghai` | 展示日期用的时区 |
| `max_rounds` | 5 | 工具调用最大轮数 |
| `max_tokens` | 2048 | 单次回答输出上限 |
| `max_answer_chars` | 200 | 超过就转合并转发 |
| `max_input_chars` | 6000 | 用户贴进来的正文最多带多少字 |
| `max_fetch_chars` | 12000 | 抓回来的正文最多带多少字 |
| `search_count` | 8 | 每次检索返回多少条 |
| `cooldown_seconds` | 30 | 同群两次使用的最小间隔 |
| `enabled_groups` | 空 | 允许使用的群号, 空表示不限制 |

## 关于时效性

`.核` 的提示词要求模型先把说法拆成子命题, 再给每个子命题判时效性: 价格、版本、排名、行程这类强时效
必须引最近一个月的来源, 只有来源明确否认才算"不实", 搜不到等于"存疑/无法核实"。当前时间会随系统提示
注入, 所以模型知道"最近"是相对哪一天。
