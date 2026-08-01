# 测试策略

## 1. 概述

项目使用 `pytest`。测试覆盖认证、用户与 Agent、OpenClaw 客户端、聊天、会话、附件、Snowflake ID、OpenAPI schema 和配置。当前测试 fixture 在本地 SQLite 文件上手写 schema，并通过 FastAPI dependency override 替换数据库、OpenClaw 和 MinIO。

## 2. 测试目录

| 路径 | 覆盖内容 |
| --- | --- |
| `tests/test_auth.py` | 注册、登录、JWT、当前用户 |
| `tests/test_agent_provisioning.py` | Agent Provision、失败恢复、手动重试 |
| `tests/test_user_agent.py` | 当前用户 Agent 查询 |
| `tests/test_chat.py` | 同步/流式聊天、取消、Agent 状态、错误映射 |
| `tests/test_chat_service.py` | ChatService 状态拦截 |
| `tests/test_conversations.py` | 会话 CRUD、消息持久化、用户隔离 |
| `tests/test_attachments.py` | 上传、读取、删除、附件聊天、PDF 处理 |
| `tests/clients/test_openclaw_client.py` | OpenClaw HTTP 协议、流式解析、错误映射 |
| `tests/core/test_snowflake.py` | Snowflake ID 生成器 |
| `tests/models/test_user_ids.py` | ORM 字段和约束 |
| `tests/test_settings.py` | 配置解析 |
| `tests/test_openapi_schema.py` | OpenAPI 中大整数字符串 |

## 3. Fixture 和 Fake

`tests/conftest.py` 提供：

- session 级 SQLite 文件数据库。
- 手写 `users`、`user_agents`、`conversations`、`conversation_messages`、`attachments`、`message_attachments` schema。
- `FakeOpenClawClient`，用于应用级测试替换 `get_openclaw_client()`。
- `FakeStorageService`，用于附件测试替换 MinIO。
- `get_db` dependency override。

## 4. 当前测试数量

按 `rg "^(async )?def test_" tests` 统计，当前测试用例为 131 个。实际通过数量以本机执行 `pytest` 输出为准。

## 5. 执行命令

```powershell
pytest
```

本次建立文档时已在当前工作区执行，结果为 `179 passed, 2 warnings in 22.58s`。两个 warning 来自第三方库：`fastapi.testclient` 的 Starlette deprecation warning，以及 `fontTools.misc.py23` 的 deprecation warning。

根 README 当前描述了基于 `TEST_DATABASE_URL` 的 MySQL 测试数据库，但当前 `tests/conftest.py` 没有读取该环境变量，实际默认使用 SQLite。建议后续统一 README、fixture 和 pytest marker 文案。

## 6. 重点测试场景

| 场景 | 当前覆盖 |
| --- | --- |
| 注册密码哈希和敏感字段隐藏 | 已覆盖 |
| JWT `sub` 字符串和过期 token | 已覆盖 |
| 注册后 OpenClaw Provision | 已覆盖 |
| OpenClaw fake client | 已覆盖 |
| 普通聊天 | 已覆盖 |
| SSE `start`/`delta`/`done`/`error` | 已覆盖 |
| 取消生成 | 已覆盖 |
| 附件上传和访问隔离 | 已覆盖 |
| PDF 文本提取和图片兜底 | 已覆盖 |
| 权限隔离 | 已覆盖 |
| MinIO mock/fake | 已覆盖 |

## 7. 待加强

- 增加真实 MySQL 集成测试或删除 README 中与当前不一致的 MySQL 测试描述。
- 为 MinIO 读取、删除失败补充错误映射测试。
- 如果引入 Redis 或队列，需要增加多实例流式状态测试。
- 增加 Alembic upgrade/downgrade 的独立验证。
