# 后续规划与改进

本文档只记录当前代码相关的规划和建议，不把尚未实现的能力写成当前能力。

## P0：影响稳定性或数据安全

| 方向 | 状态 | 说明 |
| --- | --- | --- |
| 管理接口鉴权 | 待实现 | `/api/v1/users` 和 `/api/v1/user-agents` 当前未接入 `CurrentUser` 或 RBAC |
| User CRUD 创建逻辑修正 | 待确认 | `UserService.create()` 未设置 `password_hash`，但 ORM 字段非空 |
| 测试数据库说明统一 | 待确认 | README 描述 MySQL 测试库，当前 fixture 使用 SQLite |
| OpenClaw/MinIO 错误脱敏审计 | 建议方案 | 保持 token、内部路径和敏感文件内容不进入日志或响应 |
| 多 worker Snowflake 配置 | 建议方案 | 多实例必须分配唯一 `SNOWFLAKE_WORKER_ID` |

## P1：近期核心功能

| 方向 | 状态 | 说明 |
| --- | --- | --- |
| Refresh Token | 待实现 | 当前只有 Access Token |
| 登录失败限制 | 待实现 | 增加账号/IP 限流和失败计数 |
| Agent Provision 重试 | 待实现 | 注册失败后当前支持手动重试，缺少自动退避重试 |
| Agent 状态同步 | 待实现 | 周期性刷新 `registered`、`warming` 状态 |
| 聊天中断恢复 | 待实现 | 当前取消状态在进程内，重启后无法恢复 |
| 上下文裁剪 | 待实现 | 当前聊天请求没有历史上下文裁剪策略 |
| Token 使用统计 | 待实现 | 当前不记录 prompt/completion token |

## P2：体验和可维护性优化

| 方向 | 状态 | 说明 |
| --- | --- | --- |
| OCR | 待实现 | 扫描件 PDF 和图片文字识别 |
| Word/Excel/PPT 附件 | 待实现 | 当前支持 PDF、文本类和图片 |
| 文件预览 | 待实现 | 当前只有内容下载/内联图片 |
| 大文件异步解析 | 待实现 | 当前上传同步校验并存储 |
| 附件解析缓存 | 待实现 | 当前聊天时从 MinIO 读取并即时解析 |
| 对象生命周期管理 | 待实现 | 清理已软删除或孤儿对象 |
| 会话搜索 | 待实现 | 当前只有列表和消息读取 |
| 会话归档 | 待实现 | 当前只有软删除 |
| 可观测性 | 建议方案 | 增加 request id、OpenClaw latency、MinIO latency、错误率指标 |

## P3：长期演进

| 方向 | 状态 | 说明 |
| --- | --- | --- |
| 管理后台 | 待实现 | 用户、Agent、附件和会话运营视图 |
| 分布式流式状态 | 建议方案 | 使用 Redis 或数据库替代进程内 `ChatStreamManager` |
| Agent Provision 队列化 | 建议方案 | 注册请求不阻塞等待 OpenClaw |
| 审计历史 | 建议方案 | 记录 Agent 状态变化和关键管理操作 |
| 知识库入库流水线 | 规划中 | 当前代码尚未实现知识入库 |

