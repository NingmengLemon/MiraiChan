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

emoji 有两种来源, 按顺序取: 配置了 `emoji_font` (彩色 emoji 字体) 就用字体画字形,
字体里没有的字形再走 `emoji_cdn` (EmojiServer) 下载图片; 两者都没配时退回正文字体的字形,
普通中文字体没有 emoji 字形, 会画成方框。

"字体里没有"是按字形判定的: 渲染结果与 `.notdef` (方框) 逐像素相同就算没有,
所以缺字形不会贴一个黑框上去, 而是照常去 CDN 取。

字体自己的覆盖范围也有限: 旧字体可能没有较新 ZWJ 序列的合字, 会把一个簇画成并排的
几个字形 (Windows 10 的 Segoe UI Emoji 画 🧑‍🦳 就是人 + 白发两块)。这属于字体覆盖问题,
换一个 emoji 字集更新的字体即可。

`emoji_font` 得是 Pillow 能光栅化的彩色字体: CBDT/CBLC 位图字体 (Debian 的
`fonts-noto-color-emoji`, 只有一个 109px 档) 或 COLRv0 矢量字体 (Windows 的 Segoe UI Emoji)。
COLRv1 的字体 (例如 Windows 10 上那个 `NotoColorEmoji-Regular.ttf`) Pillow 画不出来,
配上去会在启动时告警, 所有 emoji 都退化成下一级来源。
`ColorFontEmoji(font).can_rasterize_color` 可以先验一下字体能不能用。

## 卡片遮罩

`.q` 的深色底板不是图片, 启动时按配置里的参数用 Pillow 画: 左侧透明 (露头像)、右侧不透明,
中间一条斜向渐变带。改 `card.mask` 即可, 不用准备素材。

| 字段 | 默认 | 含义 |
| --- | --- | --- |
| `fade_from` | 0.113 | 渐变带起点, 占卡片宽度的比例, 顶边处 0 到 255 从这里开始 |
| `fade_width` | 0.257 | 渐变带宽度, 占卡片宽度的比例 |
| `slant` | 0.191 | 底边相对顶边的水平偏移量, 占卡片宽度的比例, 正数是底边更靠右 |
| `curve` | 0.5 | 过渡曲线, 0 是直线, 1 是两端平缓、中间更陡的 smoothstep |

长度都按卡片宽度取比例, 换卡片尺寸不用改参数。默认值对应卡片现在的观感 (卡宽 1920 时顶边
217px 起、宽 493px、底边右移 367px)。

遮罩按 (尺寸, 参数) 缓存, 参数没变就复用画好的那张; 参数只在下一次启动时生效。

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
