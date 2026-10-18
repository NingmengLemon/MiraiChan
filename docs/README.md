# 文档索引

- `roadmap.md`: 还没做的点子与已知技术债

- `melobot/`: melobot 框架机制说明 (基于 3.5.0)
  - `overview.md`: 架构与特性概览
  - `preprocess-mechanism.md`: checker / matcher / parser 预处理机制
- `development/`: 本仓库的开发约定
  - `testing.md`: 测试的放置与运行
  - `logging.md`: 日志约定与 debug 开关
  - `plugins.md`: 插件开发的坑 (命令参数切分等)
- `deployment/`: 部署与运维
  - `runbook.md`: 部署步骤、上线插件、升级与替换旧实例
  - `legacy-migration.md`: 从旧实例迁移的对照与步骤
  - systemd unit 模板在仓库根的 `deploy/` 下
- `discussions/`: 设计讨论、评审与现场记录, gitignored, 不随仓库分发
