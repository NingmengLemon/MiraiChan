# 协议无关插件门面设计

`docs/development/protocols.md` 记录的协议边界是本文的前提。这里只定门面本身: 插件看到的入站与出站模型、
端口契约、能力声明与迁移顺序。实现包暂定 `lemony_chat`, 第一版只接 OneBot 11, Milky / Satori / Telegram
按同一份契约补齐。

## 目标与边界

做:

- 入站: 群聊与私聊消息统一成 `ChatMessage`, 包含会话、发送者、文本、内容序列、消息标识与原始事件;
- 出站: 回复、发消息、发图/音频/视频、撤回、禁言、合并转发、表情回应、上传文件;
- 每协议一份能力声明, 插件据此隐藏或降级协议特有功能;
- 复用 melobot 的 `Event` / `TextEvent` / `Content` / `FlowDecorator` / 依赖注入, 不另建事件模型与分发。

不做:

- 不接管事件构造与广播, 不建第二套 dispatcher, 不新增 "门面事件" 类型;
- 不表达 QQ 专有语义 (QQ 表情编号、合并转发节点上限、群文件分类、Markdown 与内联键盘段等),
  这些留给协议扩展包;
- 第一版不覆盖通知与请求事件 (入群、撤回通知、加好友请求等);
- 第一版不提供无事件上下文的主动推送;
- 不做跨协议账号互通、消息同步或统一群成员管理。

## 现状约束

1. melobot 的适配器按协议标识注册, 同一协议只能有一份适配器; 一个适配器可以挂多个 IO 源,
   不同协议的适配器共享同一个 `Dispatcher`。
2. 事件由各协议的适配器构造后直接广播, 插件的 `FlowDecorator` 只按 checker 过滤事件。
   适配器的输入循环是 `final`, 事件工厂是私有字段, 门面不能替换事件, 只能从已有事件上取视图。
3. `melobot.handle` 的 `on_command` / `on_start_match` / `on_contain_match` / `on_full_match` /
   `on_end_match` / `on_text` 已经只要求通用 `TextEvent`, 与协议无关。消息事件装饰器
   (`on_message` / `on_at_qq` / `on_notice` 等) 在 v11 的 handle 里, 绑定了 v11 类型。
4. melobot 自带的通用内容转换是有损的: `seg_to_content` 把 v11 的 `at` 段映射成 `ReferContent`,
   把文件与引用压成文本; `content_to_seg` 也只是近似。门面复用 `Content` 类型, 不复用这层转换。
5. melobot 3.5.1 的 v11 段表里没有 `file` 段类; 文件类消息只能从原始段里识别,
   不能当成标准文件内容处理。
6. 已跟踪插件对 v11 的依赖面集中在: `Adapter`、`MessageEvent` / `GroupMessageEvent` / `NoticeEvent`、
   `TextSegment` / `ImageSegment` / `ReplySegment` / `JsonSegment`、`on_message` / `on_notice`。

## 方案取舍

三个候选:

- A, 门面事件类: 每个协议适配器创建 `ChatMessage` 子类的 `Event`, 插件直接按事件类型路由。
- B, 第二套分发: 在适配器 hook 里把原生事件转换成门面事件, 再广播到另一个 `Dispatcher`。
- C, 视图加端口: 原生事件照旧流经 `Dispatcher`; 门面从事件构建只读快照 `ChatMessage`,
  出站通过按协议注册的端口调用原适配器。装饰器用 checker 限定视图可用的事件, 依赖注入提供快照。

选 C:

- 不改上游。A 与 B 都要覆盖适配器的 final 输入循环或私有事件工厂, 等于 fork melobot,
  或者让同一事件被两套处理链消费, 重新定义顺序、阻断与会话语义;
- 未迁移的插件继续拿原生事件, 可以逐个迁移;
- 事件只被处理一次, 会话、匹配器、解析器、阻断都沿用 melobot 的现有行为;
- 视图无状态, 在会话中重新获取仍然有效;
- 代价是 `ChatMessage` 不是 `Event` 子类, 不能用 `isinstance(event, ChatMessage)` 做路由,
  路由改由门面装饰器加依赖注入完成; 每个协议都要写一段事件到视图的转换, 这部分成本本来也存在。

门面模型只是投影, 内容类型直接复用 melobot 的 `Content`, 因此不算 "第三套模型"。

## 核心模型

下面的代码是签名示意, 不是最终实现。

```python
ChatProtocol = Literal["onebot11", "milky", "satori", "telegram"]  # 新协议追加
PartLike = str | Content


@dataclass(frozen=True, slots=True)
class Conversation:
    kind: Literal["group", "private"]
    id: str


@dataclass(frozen=True, slots=True)
class Sender:
    id: str
    name: str
    role: Literal["owner", "admin", "member"] | None = None
    card: str | None = None


@dataclass(frozen=True, slots=True)
class ForwardNode:
    name: str
    user_id: str | None
    contents: tuple[Content, ...]


@dataclass(frozen=True, slots=True)
class Capabilities:
    reply_quote: bool
    recall: bool
    ban: bool
    forward: bool
    reaction: bool
    image: bool
    audio: bool
    video: bool
    upload_file: bool
    mention: bool
    self_message: bool


@dataclass(frozen=True, slots=True)
class ChatMessage:
    protocol: ChatProtocol
    conversation: Conversation
    sender: Sender
    message_id: str | None
    text: str
    contents: tuple[Content, ...]
    time: float
    capabilities: Capabilities
    event: Event
    _port: ChatPort = field(repr=False, compare=False)

    async def reply(self, *parts: PartLike) -> str | None: ...
    async def send(self, *parts: PartLike) -> str | None: ...
    async def recall(self) -> None: ...
    async def ban(self, user_id: str, seconds: int = 600) -> None: ...
    async def forward(self, nodes: Sequence[ForwardNode | str]) -> str | None: ...
    async def react(self, token: str) -> None: ...
    async def upload_file(self, name: str, path: str) -> None: ...
```

字段与决策:

- 标识一律用 `str`。QQ 是十进制数字串, Satori 是字符串, Telegram 是整数; 门面不假设数值类型,
  原始数值仍在 `event` 里。插件要写数据库时自行转换, 不要依赖门面给出 `int`。
- `sender.name` 是显示名 (群名片优先, 否则昵称), `sender.card` 保留原名片字符串。
- `text` 只拼接文本内容, 不混入 @ 与媒体; 需要完整序列时看 `contents`。
- `contents` 按原消息顺序排列, 复用 melobot 的 `TextContent` / `ImageContent` / `VoiceContent` /
  `AudioContent` / `VideoContent` / `ResourceContent` / `ReferContent`, 另加一个
  `MentionContent(target_id, name)` 表示 @, 不用 `ReferContent` 顶替。`ReferContent` 只出现在入站,
  出站要引用时用 `reply`。
- `message_id` 可空: 有些协议不回消息标识, 或者只在部分场景给。要撤回的插件先看 `capabilities.recall`
  与 `message_id is not None`。
- `event` 是原生 melobot 事件, 只给 QQ 专用插件、检查器与排障用; 普通插件不应读它。
- 视图是快照, 不参与分发。转换结果缓存在事件的 flag 里 (melobot `FlagMixin`), 同一次事件被多个处理流
  匹配时只转换一次, 失败结果也缓存, 避免反复尝试。

## 入站

### 端口注册

端口由启动层安装, 插件不接触:

```python
from lemony_onebot_utils.chat_port import install_ob11_port
from melobot.protocols.onebot.v11 import Adapter

adapter = Adapter()
install_ob11_port(adapter)          # 把 Ob11Port(adapter) 注册到该适配器的协议标识下
bot = Bot("MiraiChan").add_io(io).add_adapter(adapter)
```

注册以 melobot 的 `adapter.protocol` 为键, 例如 `OneBot-v11@Meloland`; 端口的 `protocol` 字段则是门面的
中性枚举。同一协议重复安装抛错。启动时检查每个已绑定适配器都有端口, 没有就记录 warning,
因为这种缺失的表现是 "使用门面的插件全部不响应", 属于静默失败。

### 装饰器

门面提供两类装饰器, 都只做一层包装:

| 门面装饰器 | 底层 | 附加行为 |
| --- | --- | --- |
| `on_message` | `FlowDecorator` + `TextEvent` 检查 | 端口能识别该事件 |
| `on_group_message` | 同上 | 会话是群聊 |
| `on_private_message` | 同上 | 会话是私聊 |
| `on_command` / `on_start_match` / `on_contain_match` / `on_full_match` / `on_end_match` | `melobot.handle` 同名函数 | 追加 "视图可用" 检查, 其余参数透传 |

这些装饰器的 `matcher` / `parser` / `priority` / `block` / `temp` / `decos` 等参数与对应的 melobot
装饰器一致, 只是 checker 里多一层视图判断。

纯文本、无需视图的处理流仍可直接用 melobot 的装饰器; 需要视图的一律走门面, 避免 handler 在没有端口的协议上
被触发后再依赖注入失败。

### 依赖注入

```python
from lemony_chat import ChatMessage, current_message, on_command


@plugin.use
@on_command(".", " ", ["ping"])
async def ping(msg: ChatMessage = current_message()) -> None:
    await msg.reply("pong")
```

`current_message()` 返回一个 `BindDepends`, 从 `FlowCtx` 取当前事件, 按协议找端口并构建视图。
会话中同样有效, 因为 `FlowCtx` 取的是 `SessionCtx` 里保存的事件。取不到事件或端口时抛
`NoMessageContext`, 正常路径下不会发生, 因为装饰器已经过滤过。其他参数照旧用 melobot 的依赖注入。

### 边界情况

- 端口不存在: 装饰器不匹配, handler 不执行, 不是吞异常;
- 端口存在但不是消息事件: `view()` 返回 `None`;
- 匿名群消息: 不提供视图。匿名身份不稳定, 与 `lemony_checkers` 的身份提取口径一致;
- 群临时会话: 归为私聊, 群号只在 `event` 里;
- 未知消息段: 跳过, 不猜语义; 原文保留在 `event`;
- 通知与请求事件: 第一版不支持, 等 `recorder` 与 `checker_manager` 迁移时再定模型。

## 出站

所有动作都是 `ChatMessage` 上的异步方法, 由端口执行。

- `reply`: 引用当前消息再发送, 需要 `capabilities.reply_quote` 与 `message_id`;
- `send`: 发到当前会话, 不带引用;
- `recall`: 撤回当前消息, 需要 `capabilities.recall` 与 `message_id`, 是否有权限由平台决定;
- `ban`: 群聊禁言, 需要 `capabilities.ban`, 私聊调用按能力不足处理;
- `forward`: 合并转发, 需要 `capabilities.forward`; 节点可以是字符串 (bot 自己说) 或 `ForwardNode`;
- `react`: 消息表情回应, 需要 `capabilities.reaction`; 回应标识的含义由协议定义;
- `upload_file`: 上传文件, 需要 `capabilities.upload_file`; 与消息体分开, 因为各协议的文件上传
  不是普通消息段。

`parts` 的每个参数是 `str` 或 `Content`, 由端口转成协议表示; 需要多个部分时逐个传入。

错误类型:

```python
class FacadeError(Exception): ...
class CapabilityUnavailable(FacadeError): ...   # 协议没有这个能力
class DeliveryFailed(FacadeError): ...         # 能力有, 但本次发送失败
class InvalidTarget(FacadeError): ...          # 群号/用户号无法转成该协议的目标
class NoMessageContext(FacadeError): ...       # 当前上下文没有可取视图的事件
```

能力不足时抛 `CapabilityUnavailable`, 不静默降级。降级策略属于插件或配置, 由调用方显式写:
`helper` 在合并转发失败时退回普通消息, 这个判断留在插件里, 门面不替它做。

## 端口契约与包边界

```text
packages/shared/lemony_chat/
├── pyproject.toml
├── readme.md
└── src/lemony_chat/
    ├── __init__.py
    ├── model.py        # Conversation / Sender / ChatMessage / Capabilities / MentionContent
    ├── ports.py        # ChatPort 抽象、注册表、内置能力表
    ├── runtime.py      # current_message、视图缓存、从 FlowCtx 找事件
    ├── decorators.py   # on_message 等
    └── errors.py
```

端口实现与协议包放在一起:

- `lemony_onebot_utils/chat_port.py`: `Ob11Port` 与 `install_ob11_port`;
- 以后的 Milky 适配器包放同名模块 (包名随适配器定);
- Satori / Telegram 同理。

依赖方向:

```text
插件 ──> lemony_chat ──> melobot (core)
  │
  └──> 协议扩展包 ──> lemony_chat
```

`lemony_chat` 只依赖 melobot 核心 (`Event` / `Content` / `FlowDecorator` / `BindDepends`),
不 import 任何具体协议。协议包实现端口, 依赖 `lemony_chat`。插件需要 QQ 专有能力时再依赖协议扩展包,
这部分不算协议无关。

`ChatPort` 的契约:

```python
class ChatPort(ABC):
    protocol: ChatProtocol
    capabilities: Capabilities

    @abstractmethod
    def view(self, event: Event) -> ChatMessage | None: ...

    @abstractmethod
    async def send(self, conversation: Conversation, parts: Sequence[Content]) -> str | None: ...

    @abstractmethod
    async def reply(
        self, conversation: Conversation, message_id: str, parts: Sequence[Content]
    ) -> str | None: ...

    @abstractmethod
    async def recall(self, conversation: Conversation, message_id: str) -> None: ...

    @abstractmethod
    async def ban(self, conversation: Conversation, user_id: str, seconds: int) -> None: ...

    async def forward(self, conversation: Conversation, nodes: Sequence[ForwardNode]) -> str | None:
        raise CapabilityUnavailable(self.protocol, "forward")

    async def react(self, conversation: Conversation, message_id: str, token: str) -> None:
        raise CapabilityUnavailable(self.protocol, "reaction")

    async def upload_file(self, conversation: Conversation, name: str, path: str) -> None:
        raise CapabilityUnavailable(self.protocol, "upload_file")
```

基础动作是抽象方法; 可选动作给默认实现, 直接抛能力不足, 由各端口按自己的能力覆盖。

## OneBot 11 端口

### 入站映射

| v11 段 | 门面内容 | 说明 |
| --- | --- | --- |
| `text` | `TextContent` | 拼接成 `text` |
| `image` | `ImageContent` | `name` 取 `file`, `url` 取 `url` |
| `record` | `VoiceContent` | |
| `video` | `VideoContent` | |
| `at` | `MentionContent` | `target_id` 取 `qq`, 全体成员是 `all` |
| `reply` | `ReferContent` | `flag` 是消息标识, 第一版不展开被引用的内容 |
| `share` | `ResourceContent` | |
| 其他 | 跳过 | 原文在 `event` |

实现时必须遍历 `event.message`, 不要用 `event.contents`: melobot 已经做过一次有损转换, 其中包括把 `at`
变成 `ReferContent` 的行为。

匿名消息不建视图; 群临时会话归为私聊; `message_id` 从 `int` 转 `str`。

### 出站映射

| 门面动作 | v11 实现 |
| --- | --- |
| `reply` / `send` 文本 | `TextSegment`, `reply` 先加 `ReplySegment` |
| 图片 / 音频 / 视频 | `ImageSendSegment` / `RecordSendSegment` / `VideoSendSegment` |
| @ | `AtSegment` |
| 资源链接 | `ShareSegment` |
| `forward` | `NodeSegment` 或 `lemony_onebot_utils.forward.ForwardBuilder` |
| `recall` | `Adapter.delete_msg` |
| `ban` | `Adapter.set_group_ban` |
| `react` | `set_group_reaction` (SnowLuma), 失败退回 `set_msg_emoji_like` (NapCat 等) |
| `upload_file` | `upload_group_file` / `upload_private_file` |

要点:

- 群号与用户号出站时转 `int`, 失败抛 `InvalidTarget`; 入站时统一转 `str`;
- 合并转发的节点上显示的 bot 身份通过 `get_login_info` 获取并缓存, 失败时退回 `Sender(0, bot.name)`,
  与 `helper` 当前行为一致;
- 合并转发的节点数与单节点长度上限沿用 `ForwardBuilder` 的默认值 (100 / 4500), 超限抛
  `DeliveryFailed`, 不自动拆成多条普通消息;
- `react` 的标识沿用 `onebot_ext` 的编号规则: 1 到 3 位数字是 QQ 系统表情编号, 4 位及以上是
  Unicode 码位。其他协议的标识含义不同, 插件需要按 `protocol` 判断, 或者只用自己确定支持的协议;
- `get_forward_msg` 的返回形状差异 (SnowLuma 与 NapCat 不同) 不进门面, 仍由 `forward_strip`
  这类 QQ 专用插件处理; 第一版门面只覆盖发送。

## 能力声明

| 能力 | onebot11 | milky | satori | telegram |
| --- | --- | --- | --- | --- |
| 引用回复 (`reply_quote`) | 有 | 待核对 | 待核对 | 待核对 |
| 撤回 (`recall`) | 有 | 待核对 | 待核对 | 待核对 |
| 群禁言 (`ban`) | 有 | 待核对 | 待核对 | 待核对 |
| 合并转发 (`forward`) | 有 | 待核对 | 待核对 | 待核对 |
| 表情回应 (`reaction`) | 有 (群聊) | 待核对 | 待核对 | 待核对 |
| 图片 / 音频 / 视频 | 有 | 待核对 | 待核对 | 待核对 |
| 上传文件 (`upload_file`) | 有 | 待核对 | 待核对 | 待核对 |
| @ 提及 (`mention`) | 有 | 待核对 | 待核对 | 待核对 |
| bot 自身消息入站 (`self_message`) | 无 (需 `reportSelfMessage`) | 待核对 | 待核对 | 待核对 |

规则:

- 每填一个 "有", 都要有实现端源码或实测证据; 接入新协议时按同一标准补表, 不按直觉填;
- 能力按协议声明。实现端差异 (例如 Lagrange 的 OneBot 11 线已冻结) 不单独建列, 写在该协议的
  端口说明里; 需要精细区分时再给端口加一个实现端字段;
- 插件用 `if msg.capabilities.reaction:` 这类判断决定表现, 不按协议名字猜能力;
- Markdown、内联键盘这类实现端扩展不进门面能力表, QQ 专用插件按 `onebot_ext` 的支持矩阵判断。

## 与 melobot 的关系

- 事件: 原生事件, 不复制、不替换; `ChatMessage` 是投影;
- 内容: 复用 `Content` 子类, 只新增 `MentionContent`;
- 装饰器与会话: 复用 `FlowDecorator` 与 `Session`, 会话内 `current_message()` 有效;
- 检查器: `lemony_checkers` 的 `extract_user(event)` 已经接受通用 `Event` 并按协议分发,
  迁移后的插件传 `msg.event` 即可; 新协议仍需自己的 `adapters/<protocol>.py`;
- 日志与配置: 不变。

## 迁移路线

阶段 0: `lemony_chat` 核心与 `Ob11Port`, 单元测试, 不迁移插件。测试里用假端口覆盖非 QQ 形态
(字符串会话 id、没有 QQ 表情编号、没有合并转发), 防止模型退化成 QQ 专用。

阶段 1: `moelottery` 与 `helper` 试点。前者是纯文本加回复, 后者是回复加合并转发与降级;
验收标准是两个插件目录不再 import v11, 行为不变。

阶段 2: `deeeer` 与 `provenance` (图片、头像、表情回应), `toolbox` (撤回、复读、合并转发),
`mikufans` (链接净化; 卡片解析仍读 `event`)。QQ 专有部分继续留在扩展包, 不在门面里造参数。

阶段 3: Milky 适配器、检查器身份适配与端口, 用阶段 1 与阶段 2 迁移过的插件在 Milky 上复跑,
验证门面是否真的协议中立, 顺便修掉模型里残留的 QQ 假设。

阶段 4: `quote` 与 `forward_strip` (引用、合并转发解析), `checker_manager` (通知事件),
`rebootable`; `recorder` 的消息存储模型单独设计, 不能直接沿用 v11 消息段。

阶段 5: `emergency_alerts` 这类无事件上下文的推送, 先定主动推送接口与多 IO 配置。

阶段 6: Satori 与 Telegram 适配器, 复用阶段 3 的端口注册与身份适配模式。

每个阶段一个提交批次, 插件 import 面、`uv run pytest`、e2e 断言三者一起过。

## 测试

- `lemony_chat`: 假端口加最小事件对象, 覆盖装饰器过滤、`current_message()`、能力异常、
  `reply` / `send` 的参数归一化、视图缓存; 不使用真实 bot 实例;
- `Ob11Port`: 直接构造 v11 事件与段列表, 断言段到内容的映射; 出站用假适配器记录调用,
  断言段序列与参数;
- e2e: 用 `tools/fake_onebot_server.py` 推一条群消息, 断言 bot 发出的 action JSON。
  需要 `send_forward_msg` 等动作时给它补上对应回应;
- 契约测试: 第一版由各端口的测试覆盖同一组用例清单; 第二个协议接入时再抽成参数化套件,
  避免为单一实现过早抽象。

## 未决问题

1. 包名 `lemony_chat` 是否合适, 备选 `lemony_im`; 后者与 `lemony_images` 容易看混。
2. 会话与用户标识用 `str` 之后, `recorder` 与 `lemony_checkers` 现有的 `int` 语义如何迁移,
   等这两个包真正动的时候再定。
3. 能力是否需要按实现端细分 (SnowLuma / NapCat), 第一版按协议声明是否够用。
4. 入站时是否展开被引用消息的内容 (需要额外的 `get_msg` 或对应动作), 还是只保留消息标识。
5. 通知与请求事件的中立模型。
6. 无事件上下文主动推送的接口, 与多 IO / 多适配器配置一起定。
7. `reply` 与 `mention` 在 Satori 与 Telegram 上的对应关系, 接入时确认。
