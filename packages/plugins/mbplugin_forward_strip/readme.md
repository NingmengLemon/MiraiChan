# 转发缩水 (forward strip)

回复一条合并转发, 用 Python 切片语法截掉不需要的节点 (通常是末尾的广告), 再把剩下的发回来。

## 指令

```
.strip [:-3]      回复一条合并转发, 保留除最后 3 条以外的全部
.strip 5:         从第 5 条开始到底
.strip -3:        只保留最后 3 条
.strip [1:5:2]    支持步长
```

切片作用在节点列表上, 与 Python 的 `list[a:b:c]` 完全一致。以下情况直接回文字提示:
没回复消息、回复的不是合并转发、切片结果为空、结果超过节点上限。

命令只对管理员及以上开放, 其他人发 `.strip` 不会得到任何回应。

## 昵称与头像怎么保住的

每个节点自带发送者的 `uin`(QQ 号) 与 `name`(昵称)。重新发送时原样回填这两个字段,
QQ 客户端按 `uin` 取头像、按 `name` 显示昵称, 所以截断之后每条消息看起来还是原来那个人。

两种节点形状都认, 回填时用 go-cqhttp 形状 (`uin`/`name`/`content`), 主流协议端都接受:

- OneBot 标准: `{"type": "node", "data": {"user_id", "nickname", "content"}}`
- go-cqhttp: `{"type": "node", "data": {"uin", "name", "content"}}`

只有 `id` 的引用节点也保留原样, 内容由协议端自己补。

## 嵌套转发

节点内容里还可能套一层合并转发 (只带一个 `id`)。默认把这一层原样带回去, 由协议端处理;
如果发送失败, 而保留下来的节点里确实有嵌套转发, 插件**直接报错**, 不发送缺内容的版本;
交给用户决定是换切片还是换实现端。

## 协议端支持

- SnowLuma: `send_group_forward_msg` 接受 `messages` 节点数组, 自定义节点的 `uin`/`name` 生效,
  核心层有专门的嵌套上传实现 (`forward-nested` 的 wire 对齐测试), 所以"保留昵称头像 + 嵌套"
  这条路可以走。
- NapCat: `send_group_forward_msg` 里自定义节点的 `uin`/`name` 会被忽略, 转发里所有消息都显示
  成 bot 自己 (NapNeko/NapCatQQ#61, 维护者回复"受原理限制不能伪造转发")。换成 NapCat 时
  这个插件的核心价值就没了。
- SnowLuma 的 `get_forward_msg` 返回 `{messages: [...]}`, 数组里每一项是消息事件 (`sender.user_id` / `sender.card` / `message` / `time`), 而不是 node 消息段; 发送侧收的是 `messages` 里的 node。插件两种形状都归一化。melobot 自带的 `GetForwardMsgEcho` 只认 `data.message`, 构造时直接 KeyError, 插件在导入时把该 echo 换成不解析正文的通用版本。
  节点还会带 `time`/`seq` 以及引用段的 `message` 内嵌正文; 本插件把 `time` 原样带走, 其余未知字段不参与重建。

## 配置

`configs/forward_strip/default.json`:

| 项 | 默认值 | 说明 |
| --- | --- | --- |
| `max_nodes` | 100 | 截完之后允许的节点数上限 (QQ 客户端对超长转发显示不全) |
| `enabled_groups` | 空 | 允许使用的群号, 空表示不限制 |

## 未验证与后续

- 真机上还没跑过: 需要一条真实的合并转发消息, 并且在群里发一次才能确认 SnowLuma 对
  自定义节点昵称/头像的实际表现, 以及嵌套层是否真的能带回去。
- 目前不做"按关键词找广告"的自动截断, 位置完全由用户给的切片决定。

## 已知问题: 嵌套转发的预览

真机结果 (SnowLuma 1.14.22): 不含嵌套的转发一切正常; 保留的节点里带嵌套转发时, 发送本身成功,
手机端点开内容完整, 但外层气泡的预览是坏的 —— PC 端显示 `#000000` / `34` / `聊天记录` /
`function () { [native code] }` 这类占位垃圾且点不开, 手机端没有内层消息预览但能打开。

结论是**协议端侧的问题**, 本插件这一侧改不了: 内容都已经正确上传 (手机端能看), 坏的是外层那条
合并转发消息的预览元素。SnowLuma 自己给嵌套转发准备了一条专门的代码路径
(`packages/core/src/bridge/apis/forward.ts`: 把内层占位元素换成指向内层 res_id 的 forward 预览,
并把内层 uuid 写进 LightApp JSON 的 `meta.detail.uniseq`), 我们发的节点内容已经按
`get_forward_msg` 原样带回了内层 `forward` 段的 id, 没有可以调整的参数。

如果以后要绕开: 可以在发送前把嵌套层展开 (取内层 `get_forward_msg` 的节点, 按顺序并进外层的节点列表),
内容一条不丢、只是失去"一层套一层"的结构; 那样走的是扁平转发的预览路径, PC/手机都正常。

### 其他实现端怎么处理嵌套

同一件事有两种做法, 都是协议端的活, 插件侧给的东西一样 (节点列表里放一个带 id 的 `forward` 段):

| 实现端 | 做法 | 关键代码 |
| --- | --- | --- |
| SnowLuma / 新版 NapCat | 外层 LongMsg 的 actions 里追加内层节点 (piggyback), 预览元素的 `meta.detail.uniseq` 与内层 actionCommand 对应 | SnowLuma `bridge/apis/forward.ts`; NapCat `UploadForwardMsgV2` + `ForwardMsgBuilder` |
| Lagrange.Core | 内层先单独上传成自己的 resId, 外层预览只引用它 (`com.tencent.multimsg` 的 `detail.resid`) | `MultiMsgEntity` 的 `Preprocess` 上传 / `Build` 生成 LightApp |

Lagrange 那条路的好处是内外层互不依赖, 预览坏了也能按 resid 再拉; SnowLuma 1.14.22 走 piggyback, 我们看到的
预览畸形就出在这一段。NapCat 老版本忽略自定义 `uin`/`name`, 新版有 `UploadForwardMsgV2`, 但没实测。

### 展开嵌套的点子 (未做)

发送前把嵌套层展开并进外层节点列表, 走扁平转发的预览路径。**限制是节点数**: QQ 客户端对超过约 100 条
的转发显示不全, 插件自己的 `max_nodes` 也是 100, 展开后很容易超。可行做法是展开到预算为止,
超预算就报错而不是发一条看不全的记录; 但没展开干净的层仍然会撞上上面的预览问题, 所以暂时搁置。
