# melobot 协议层与跨协议能力

> 基于 melobot 3.5.1。源码取自 `references/melobot` (tag `v3.5.1`, commit `529882a`, 2026-10-19),
> 官方文档取自同仓库 `docs/source`。本文只记录核实过的行为, 不把 README 的宣传语当作能力清单。

## 分层

```
输入源 -> InPacket -> EventFactory -> Event -> Dispatcher -> Flow / FlowNode -> handler
handler -> 适配器方法 -> Action -> OutputFactory -> OutPacket -> 输出源 -> EchoPacket
        -> EchoFactory -> Echo -> ActionHandle
```

- 源 (source): 输入源、输出源、输入输出源三类。每类源只对应一个协议。
- 适配器 (adapter): 每类适配器只对应一个协议, 每个 bot 对每个协议只能绑定一个适配器。
  适配器做三件事: 把输入包转成事件, 提供产生行为的方法, 把输出源的回应包转成回应。
- 分发器 (dispatcher): 每个 bot 一个, 所有协议的事件都广播进同一个分发器。
- 处理流 (flow): 插件注册的全局处理流, 不按协议分区; 事件匹配靠 checker 与依赖注入。

## 基数与组合

| 维度 | 规则 | 结果 |
| --- | --- | --- |
| 每协议适配器 | 每个 bot 只能绑定一个 | 同协议多账号不能靠多适配器 |
| 每协议源 | 任意多 | 多账号 = 一个适配器挂多个源 |
| 每 bot 协议 | 任意多 | 不同协议的适配器共享分发器 |
| 事件/行为/回应 | 必须属于一个协议 | 跨协议不能直接复用这些对象 |

同一个协议的多路源由协议栈对象统一添加, 例如 `OneBotV11Protocol(*srcs)` 会把所有源同时放进
`inputs` 与 `outputs`。不同协议的适配器各自广播事件, 所有事件都会进入全局分发器, 各处理流再用
checker 与依赖注入过滤; 插件要限定协议, 只能自己在 checker 里判断 `event.protocol` 或事件类型。

## 协议中立的部分

### 事件与文本

`Event` 的公共字段: `time`, `id`, `protocol`, `scope`, `contents`。
`TextEvent` 在 `Event` 之上要求 `text` 与 `textlines`。

`contents` 是 melobot 设计的跨协议输入桥: 由各协议适配器自行填充通用内容实体。
`Content` 的内置子类只有:

- `TextContent` (带跨平台 `TextStyle` / `Color`)
- `MediaContent` 及其子类 `ImageContent`, `AudioContent`, `VoiceContent`, `VideoContent`
- `FileContent`
- `ReferContent` (引用)
- `ResourceContent` (网络资源)

没有 @、表情、按钮、合并转发这类内容实体, 需要时得自己定义 `Content` 子类, 但只有认识它的
协议端口才能处理。

`contents` 的可靠性因协议而异:

- Console 填的是整行输入的 `TextContent`; MCPM 按日志解析结果填 `TextContent`, 匹配到日志行时是内容部分,
  不是原始整行;
- OneBot v11 会在事件构造时调用 `seg_to_content` 填充, 但这个转换是有损的:
  只处理文本、接收图片、接收语音、接收视频、@、分享; @ 会被映射成 `ReferContent`,
  其余段 (表情、JSON、XML、forward、poke 等) 被丢弃。`MessageEvent.text` 也只是把所有
  `text` 段拼起来。

### 装饰器、依赖注入与会话

- `on_event` / `on_text` 是跨协议的事件绑定方法; `on_command` / `on_start_match` /
  `on_contain_match` / `on_full_match` / `on_end_match` / `on_regex_match` 只要求 `TextEvent`。
- 依赖注入按类型注解提供 `Event`, `Bot`, `Adapter`, `GenericLogger`, `FlowStore`,
  `Session`, `SessionStore`, `Rule`, 解析参数等。
- 处理流结点发生依赖不匹配时, melobot 抛出内部的 `DependNotMatched`; 该结点被跳过,
  它的后继结点不再遍历 (同一层的其他起始结点仍会运行)。这是有文档保证的行为, 不是面向用户的错误。
- 会话规则作用于任意 `Event`。`DefaultRule` 只比较事件的 `scope` 字段。
  `scope` 由各协议定义: OneBot 群聊是 `(group_id, user_id)`, 私聊是 `(-1, user_id)`;
  Console 不设置 `scope`; MCPM 是 `(server_id, player_name)`。
  `scope` 不含账号或源标识, 同协议多账号时默认规则可能跨账号匹配; 多协议同时在线时也可能
  出现 scope 碰撞。需要严格隔离时要自定义 `Rule`, 结合 `EventOrigin.in_src` 或 `self_id`。

### 通用输出

`melobot.adapter.generic` 提供 `send_text`, `send_media`, `send_image`, `send_audio`,
`send_voice`, `send_video`, `send_file`, `send_refer`, `send_resource`。

这些函数的共同行为:

- 只发给**当前事件所属协议**的适配器, 不允许指定协议或会话;
- 返回 `ActionHandleGroup`, 没有统一的消息 id 契约;
- 协议未实现对应方法时, 基类回退到输出一段提示文本。例如 `send_file` 在 OneBot v11 上
  实际发出的是 `"[OneBot v11 file: ...]"` 文本, 不是文件上传;
- 不提供能力查询, 调用方无法在调用前知道会不会被降级成文本。

`filter_out` 可以筛选输出源, 但它只作用于当前适配器的 `out_srcs`, 即同一协议的多路输出,
不能把行为发到另一个协议。

### 事件来源

`Event.get_origin_info()` 返回 `EventOrigin`, 其中 `adapter` 是产生事件的适配器,
`in_src` 是产生事件的输入源。多账号场景下回复默认走产生事件的那个源
(`Adapter.call_output` 的选择顺序: 输出源过滤上下文 > 来源源 (若它也是输出源) > 该协议全部输出源)。

## 协议专用的部分

每个协议都要自己定义:

- 事件类型与字段 (`MessageEvent`、`NoticeEvent` 等只存在于对应协议包);
- 行为与回应类型, 以及行为到输出包的转换;
- 消息段/内容形状 (OneBot v11 的 `Segment`, Console 的 `InputData`, MCPM 的日志行等);
- 事件绑定方法 (`on_message`, `on_notice`, `on_input`, `on_log` 等);
- IO 包类型与协议栈类;
- 协议标识串, 约定为 `{NAME}-v{VERSION}@{AUTHOR}`, 例如 `OneBot-v11@Meloland`、
  `Console-v1@Meloland`、`MCPM-v1@Meloland`。

适配器在输出方法上最少只需实现 `__send_text__`; 其余 `__send_media__` / `__send_image__` 等都有文本回退。
MCPM 协议就只实现文本与自定义命令行为, 没有媒体能力, 依赖文本回退。
Console 协议直接复用通用文本模型, 没有实现回应 (Echo)。

## 跨协议 IO 的真实边界

### 输入

多协议同时输入是成立的: 每个协议各自有源和适配器, 事件进入同一个分发器, 插件能同时收到。
事件仍然保留自己的协议类型与字段, 不存在统一的"消息事件"。

### 输出

- 协议特定方法 (如 `adapter.send`) 按当前事件定位会话与来源源;
- 通用输出方法只走当前事件所属协议;
- 要把行为发到另一个协议, 必须先拿到目标协议的适配器对象 (例如
  `bot.get_adapter("Console-v1@Meloland")` 或依赖注入), 再调用它的协议方法。
  没有接受"目标协议"参数的通用 API;
- 无事件上下文时调用通用输出会取不到事件, 直接失败; 协议方法则取决于实现;
- 同协议多路输出时, 有事件上下文的发送默认走来源源; 无事件上下文 (定时推送、外部触发)
  会走该协议的全部输出源, 需要 `filter_out` 或直接操作目标源。

README 里"自由输出到指定协议实现端"的实现含义就是上面两条: 同一协议可以有多路输出源并筛选,
不同协议则通过各自的适配器对象输出。它不是"一个通用 send 接口可以指定任意协议"。

### 回应与失败

`Echo` 基类有 `status: int` 与 `prompt: str`, 但没有统一的成功/失败契约:

- OneBot v11 把 `retcode` 塞进 `Echo.status`, 另提供 `is_ok()` / `is_async()` / `is_failed()`;
  `is_ok()` 看的是原始 `status` 字符串, 不是 `Echo.status`;
- Console 没有实现回应;
- MCPM 的 `CmdEcho` 从命令输出构造, 也没有统一状态。

因此"发送是否成功"必须由协议端口自己解释, 不能依赖基类字段。

### 能力与消息模型

melobot 核心没有能力声明, 也没有跨协议的消息模型:

- 没有会话 (conversation)、发送者 (sender)、消息 id 这些统一概念;
- `scope` 只是会话规则用的键, 不是会话标识, 也不含账号;
- 没有统一的"回复"动作; 通用 `send_refer` 是唯一接近回复的跨协议行为, 但它只对当前事件所在
  会话生效, 内容转换由各协议适配器自己实现 (OneBot 用 `content_to_seg`);
- 没有撤回、禁言、合并转发、表情回应、文件上传的通用动作。

### 官方与三方实现

截至 2026-10, melobot 官方实际可用的协议只有两个:

- OneBot v11 (内置, 未支持 v12, v12 计划已在 3.2.2 移除);
- Console (内置, 3.3.0 加入)。

官方计划中的 QQ 官方协议仍是空壳: `aicorein/melobot-protocol-qq` 只有空的
`melobot_protocol_qq/__init__.py`, `pyproject.toml` 标的是 `Development Status :: 1 - Planning`。
三方实现目前能看到的完整样例是 `aicorein/melobot-protocol-mcpm` (Minecraft 服务端管理, 文本协议)。
目前在官方文档、GitHub 组织与可见社区仓库里没有查到 Satori、Milky、Telegram 适配器;
本仓库 `packages/shared/melobot_telegram_protocol` 也只有一句 `# to be rewritten`。

## 对本项目的结论

门面需要补的正是 melobot 不提供的这一层: 会话与发送者模型、消息标识、显式出站动作、能力声明、
消息事件装饰器。可以复用的是 `Event` / `TextEvent` / `Content` / `FlowDecorator` / 依赖注入 /
会话 / 分发器, 以及 `EventOrigin` 与 `DependNotMatched` 的语义。

据此对 `docs/development/protocol-facade.md` 的修正:

1. 端口注册表按**适配器实例**键控, 通过 `Event.get_origin_info().adapter` 查找;
   不按协议字符串全局单例, 避免多个 bot 实例与测试之间串状态。
2. `current_message()` 在取不到视图时抛 `DependNotMatched` 的子类, 让处理流结点正常跳过;
   不把它定义成普通异常, 也不要依赖"handler 被调用后再报错"。
3. 门面只需要 `on_message` / `on_group_message` / `on_private_message`; 命令、匹配类装饰器
   继续用 `melobot.handle` 的通用版本, 不需要包装。
4. 出站一律用显式目标 (`send_custom` / `send_forward_custom`), 不依赖当前处理流上下文,
   这样 `ChatMessage` 在会话或后台任务里也能用。
5. 不用通用 `send_text` / `send_image` / `send_file` 实现门面出站: 它们没有目标参数、
   没有消息 id, 未实现时还会静默降级成文本。
6. OneBot 入站从 `event.message` 转换, 不用 `event.contents`; 后者已经被有损转换过一次。
7. `Conversation` 增加协议侧账号字段 (OneBot 用 `self_id`), 为多账号场景留出身份;
   会话本身仍用 melobot 的 `scope`, 多协议隔离需要另加 `Rule`。
8. 回应状态由端口解释: OneBot 用 `is_failed()` / `is_async()`, 不能把基类 `status` 当成功标志。

细节设计见 `docs/development/protocol-facade.md`。

## 主要来源

- `references/melobot/src/melobot/adapter/model.py`: `Event`, `TextEvent`, `Action`, `Echo`, `ActionHandleGroup`
- `references/melobot/src/melobot/adapter/base.py`: 适配器、输出源选择、通用输出方法
- `references/melobot/src/melobot/adapter/generic.py`: 通用输出函数
- `references/melobot/src/melobot/adapter/content.py`: 通用内容实体
- `references/melobot/src/melobot/bot/base.py`: 源/适配器绑定、分发器
- `references/melobot/src/melobot/handle/register.py`: 通用事件绑定方法
- `references/melobot/src/melobot/handle/base.py`: 处理流结点与 `DependNotMatched`
- `references/melobot/src/melobot/session/option.py`: 会话规则与 `scope`
- `references/melobot/src/melobot/ctx.py`: `EventOrigin`
- `references/melobot/src/melobot/protocols/onebot/v11/`: OneBot v11 实现
- `references/melobot/src/melobot/protocols/console/`: Console 实现
- `references/melobot-protocol-mcpm/src/melobot_protocol_mcpm/`: 三方文本协议样例
- `references/melobot/docs/source/dive_in/{framework,source_adapter,adapter_extra,process_flow,dependency_injection}.md`
- `references/melobot/docs/source/update-log.md`: v3.0.0, v3.1.0, v3.2.2, v3.3.0 的协议相关变更
