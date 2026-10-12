# mbplugin_quote

把群消息画成引用图。只在群聊里响应。

## 命令

回复一条消息后发送:

- `.q` / `.quote`: 名言卡片 (1920x1080, 左侧头像)。只画文字, 目标消息没有文字时提示改用 `.mq`。
- `.mq` / `.momoquote [参数]`: 聊天记录样式。参数空白分隔、顺序任意:
  - `x..y`: 以被回复的消息为 0 的相对区间, 负数更早, 可以全负或全正, 例如 `-3..2`、`-5..-2`;
    只写一个数 `n` 等价于 `n..0` 或 `0..n`;
  - `-s`: 只取被回复者本人的消息 (偏移也只在本人的消息里数);
  - `Nx`: 输出倍率, 例如 `2x`。

区间需要 recorder 插件的记录; 没有记录时只能引用被回复的那一条。

emoji 图片来自配置的 `emoji_cdn` (EmojiServer)。未配置或取不到时退回字体字形,
普通中文字体没有 emoji 字形, 会画成方框。

## 权限点

插件名 `quote`, 命令名 `card` 与 `chat`。检查失败时静默。bot 管理员 (owner / admin) 不受区间、倍率与冷却限制。

## 配置

`configs/quote/default.json`, 字段见 `settings.py`。路径相对 data 根目录。

## 存档

每张发出的图都存到 `data/quote/artifacts/{年}/{月}/`, 索引在 `data/quote/quote.db`
(表 `quote_artifact`, 含请求者、被引用者、区间、文件哈希, 以及 bot 发出的那条消息 id)。
`QuoteArchive.add_hook` 可以注册存档完成后的回调。

bot 管理员 (owner / admin) 回复 bot 发出的引用图并发送 `.qdel`, 删除该图的存档 (索引与文件)。
只能删本群的存档; 非管理员发送时静默。

## 引用 bot 自己

默认 (`allow_quote_self = false`) bot 自己的消息当作不存在: 不进区间、不计偏移;
目标消息就是 bot 的消息时不回复, 也不消耗冷却。
