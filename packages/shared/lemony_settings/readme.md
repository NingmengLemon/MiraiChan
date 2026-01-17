用户发送消息
    ↓
melobot 接收事件
    ↓
Checker 检查 (BlockerChecker.check)
    ├─ 是 Owner? → 直接通过
    ├─ 匹配命令规则? → 按 behavior 处理
    ├─ 匹配群组规则? → 按 behavior 处理
    ├─ 匹配私聊规则? → 按 behavior 处理
    └─ 默认 → 按 whitelist/blacklist 处理
    ↓
[如果拒绝]
    ├─ 静默拒绝? → 事件丢弃
    └─ 发送拒绝消息 → 事件丢弃
    ↓
[如果通过]
    ↓
执行处理函数
