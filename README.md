# fastapi-agent-conventions

一份写给 AI coding agent 的 **FastAPI + Pydantic v2 后端微服务开发规范**。Claude Code、Codex、Cursor 等工具都能直接读取，人也可以当团队规范来看。

## 包含内容

```
AGENTS.md                      # 主规范（≤ 200 行）：规则、命令、分层边界
CLAUDE.md                      # 只有一行 @AGENTS.md，让 Claude Code 复用同一份内容
docs/conventions/
  api-response.md              # {code, message, data} 统一响应、分页、router/依赖写法
  errors.md                    # AppError、错误码号段、全局 exception handler
  database.md                  # SQLAlchemy 2.0 async、事务边界、repository、Alembic 审阅清单
  testing.md                   # testcontainers + 事务回滚、AsyncClient、dependency_overrides
  tooling.md                   # uv / ruff / mypy strict / CI 配置
```

## 使用方式

把 `AGENTS.md`、`CLAUDE.md` 和 `docs/conventions/` 复制到服务仓库的根目录，然后按项目实际情况调整：

1. 把示例 domain `order` 换成你自己的 domain，并更新 `errors.md` 中的号段分配表。
2. 如果项目用了具体的任务队列、认证方案或 APM，在 AGENTS.md 对应的章节补一行说明。
3. 删掉项目用不到的章节。对每一行都问一句："删掉它，agent 会犯错吗？"

## 核心约定速览

| 主题 | 约定 |
|------|------|
| 运行时 | Python ≥ 3.12，全异步，`async def` 中禁止阻塞 IO |
| 分层 | 按 domain 组织：`router → service → repository`，SQL 只写在 repository |
| ORM | SQLAlchemy 2.0 async，与 Pydantic schema 分离；事务按请求划分，`lazy="raise"` |
| 路由 | `/{service}/v1/{resources}`，前缀由服务自己挂载，网关不剥离 |
| 响应 | `{code, message, data}`，`code=0` 表示成功；分页 `data = {items, total, page, size}` |
| 错误 | HTTP 状态码保持语义 + 5 位整数业务码，按 domain 分号段 |
| 可观测性 | structlog JSON + request_id + OpenTelemetry，日志禁止出现敏感信息 |
| 测试 | 真实 PostgreSQL + 每个测试事务回滚，覆盖率 ≥ 80% |
| 工具 | uv、ruff、mypy strict + pydantic 插件 |

## 设计依据

主要参考了以下项目和资料，并结合团队实际做了取舍：

- [zhanymkanov/fastapi-best-practices](https://github.com/zhanymkanov/fastapi-best-practices)：domain 结构、依赖校验、Alembic 命名
- [fastapi/full-stack-fastapi-template](https://github.com/fastapi/full-stack-fastapi-template)：`Annotated` 依赖别名、工具链
- [polarsource/polar](https://github.com/polarsource/polar)：强制 repository 层、事务边界、`lazy="raise"`，以及 AGENTS.md 的写法
- [FastAPI 官方文档](https://fastapi.tiangolo.com/) 与 release notes：async 规则、yield 依赖的 `scope`
- [Claude Code memory 最佳实践](https://code.claude.com/docs/en/memory)、[agents.md](https://agents.md)：篇幅控制、只写 agent 推断不出的内容

和上述资料的主要差异：

- 使用统一 envelope `{code, message, data}`。业界大项目多数直接返回资源，这里为了对齐团队前端和网关的约定而采用 envelope。
- 删除接口返回 200 + `data: null`，而不是 204，因为 204 不能带 body。
