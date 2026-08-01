# Darwin Knowledge Platform 后端项目文档

本文档是当前 FastAPI 后端的维护入口。内容以仓库中的 `app/`、`alembic/`、`tests/` 和根目录 `README.md` 为准，规划内容会明确标记为“规划中”“待实现”或“建议方案”。

## 1. 项目简介

Darwin Knowledge Platform Backend 是知识平台的后端服务，当前重点能力是用户注册登录、用户与 OpenClaw Agent 的一对一绑定、会话化聊天、SSE 流式聊天、聊天附件上传与私有对象存储。后端负责把 Web 前端请求转换为安全的领域操作，并在调用 OpenClaw Gateway、MySQL 和 MinIO 时收敛鉴权、事务、错误映射和数据边界。

## 2. 当前已经实现的主要能力

| 能力 | 实现状态 | 关键入口 |
| --- | --- | --- |
| 运行状态检查 | 已实现 | `app/api/endpoints/health.py` |
| 注册、登录、当前用户 | 已实现 | `app/api/endpoints/auth.py` |
| JWT Bearer 鉴权 | 已实现 | `app/api/dependencies.py`, `app/core/security.py` |
| User CRUD | 已实现，当前 `/api/v1/users` 未接入鉴权 | `app/api/endpoints/user.py` |
| UserAgent CRUD 与当前用户 Agent 查询 | 已实现，管理类 `/api/v1/user-agents` 未接入鉴权 | `app/api/endpoints/user_agent.py` |
| 注册后自动创建 OpenClaw Agent | 已实现，失败会保留用户并标记 `failed` | `app/services/agent_provision_service.py` |
| 会话创建、列表、标题更新、软删除、消息历史 | 已实现 | `app/api/endpoints/conversations.py` |
| 普通聊天与 OpenClaw 调用 | 已实现 | `app/api/endpoints/chat.py`, `app/services/chat_service.py` |
| SSE 流式聊天、取消生成 | 已实现，运行态记录保存在进程内存 | `app/services/chat_stream_manager.py` |
| 附件上传、内容读取、删除、消息引用 | 已实现 | `app/api/endpoints/attachments.py`, `app/services/attachment_service.py` |
| PDF 文本提取与图片兜底 | 已实现 | `app/services/attachment_service.py` |
| 全局错误响应 | 已实现 | `app/core/errors.py` |
| 自动化测试 | 已实现，测试 fixture 当前使用 SQLite | `tests/` |

## 3. 系统边界

后端保存平台用户、Agent 绑定、会话、消息和附件元数据；附件二进制保存到私有 MinIO bucket；模型推理、Agent 创建和运行时就绪检查由 OpenClaw Gateway 承担。当前代码没有实现知识库入库流水线、OCR、文件预览、后台管理权限系统、refresh token、会话搜索和异步大文件解析。

## 4. 技术栈

| 类别 | 技术 |
| --- | --- |
| Web 框架 | FastAPI |
| ORM 与迁移 | SQLAlchemy 2.x async, Alembic |
| 生产数据库 | MySQL 8，`mysql+asyncmy` |
| 测试数据库 | SQLite fixture，部分文档/README 中的 MySQL 测试说明与当前测试实现不一致 |
| 对象存储 | MinIO Python SDK |
| OpenClaw 调用 | httpx AsyncClient |
| 鉴权与密码 | PyJWT, pwdlib Argon2 |
| 附件处理 | Pillow, pypdf, PyMuPDF |
| 流式响应 | Server-Sent Events |

## 5. 推荐阅读顺序

项目概览 -> [系统架构](architecture/overview.md) -> [数据库设计](architecture/database.md) -> [聊天模块](modules/chat.md) -> [附件模块](modules/attachments.md) -> [OpenClaw Agent](modules/openclaw-agents.md) -> [错误处理](architecture/error-handling.md) -> [测试策略](architecture/testing.md) -> [后续规划](roadmap/improvements.md)

## 6. 模块文档索引

- [认证模块](modules/auth.md)
- [用户模块](modules/users.md)
- [OpenClaw Agent 模块](modules/openclaw-agents.md)
- [会话模块](modules/conversations.md)
- [聊天模块](modules/chat.md)
- [附件模块](modules/attachments.md)

## 7. 架构文档索引

- [系统架构](architecture/overview.md)
- [数据库设计](architecture/database.md)
- [外部依赖与集成](architecture/external-integrations.md)
- [错误处理](architecture/error-handling.md)
- [测试策略](architecture/testing.md)

## 8. 当前实现状态

当前实现已经具备 Web 聊天后端的核心闭环：用户注册时创建平台用户和 `user_agents` 绑定，OpenClaw 成功返回后保存 `agent_id`；用户登录后通过 Bearer Token 调用聊天、会话和附件接口；聊天请求使用当前用户绑定的 Agent，不接受客户端传入 `agent_id`；带附件聊天会从 MinIO 读取私有对象并转换为 OpenClaw 可接收的文本、图片或文件输入。

需要特别注意：`POST /api/chat` 只有在请求包含 `conversation_id` 时才会持久化用户消息和 assistant 消息；无 `conversation_id` 的聊天只返回答案，不自动创建会话。

## 9. 规划中功能

规划中或建议方案集中维护在 [后续规划](roadmap/improvements.md)。当前重点包括 refresh token、登录失败限制、Agent Provision 重试和状态同步、聊天中断恢复、OCR、附件解析缓存、大文件异步解析、对象生命周期管理、会话搜索、可观测性和管理后台。

## 10. 文档维护约定

1. 文档更新必须跟随代码变更，接口路径、类名、配置项、表名和字段名以代码为准。
2. 尚未实现的能力必须标记为“规划中”“待实现”或“建议方案”。
3. 不在文档中写真实密钥、token、数据库密码、内部路径或 OpenClaw 返回的敏感目录字段。
4. 架构图片优先保存为可编辑 SVG，路径统一放在 `docs/assets/` 下。
5. Mermaid 图应保持小而清晰，复杂流程拆成多张图。
6. 新增模块时，优先复用模块文档的统一结构，并在本文档补充索引。

