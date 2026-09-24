# AGENTS.md

FastAPI + Pydantic v2 后端微服务。全异步，Python ≥ 3.12，SQLAlchemy 2.0 (async) + Alembic，包管理用 uv。
详细示例见 `docs/conventions/`，修改对应领域的代码前先读相关文件。

## 常用命令

```bash
uv sync                                              # 安装依赖（依据 uv.lock）
uv run uvicorn app.main:app --reload                 # 本地启动
uv run ruff check --fix . && uv run ruff format .    # lint + format
uv run mypy app                                      # 类型检查（strict）
uv run pytest tests/<domain>/test_x.py::test_name    # 先跑相关的单个测试
uv run pytest --cov=app --cov-fail-under=80          # 提交前跑全量
uv run alembic revision --autogenerate -m "<slug>"   # 生成迁移
uv run alembic upgrade head                          # 应用迁移
```

提交前 ruff、mypy、pytest 三项必须全部通过。工具配置见 `docs/conventions/tooling.md`，能用工具检查的规则不在本文件重复。

## 目录结构与分层

```
app/
  main.py              # create_app()、lifespan、挂载 /{SERVICE_NAME}/v1、/health、/ready
  core/                # config、db、responses、exceptions、logging、security
  <domain>/
    router.py          # HTTP 层：参数、状态码、schema 转换
    service.py         # 业务逻辑
    repository.py      # 数据访问：所有 SQL 只在这里
    schemas.py         # Pydantic 模型
    models.py          # SQLAlchemy ORM 模型
    exceptions.py      # 本 domain 的 AppError 子类和错误码
    dependencies.py    # Annotated 依赖别名、实体校验依赖
    config.py          # （可选）本 domain 的 BaseSettings
migrations/            # Alembic
tests/<domain>/
```

- 调用方向只能是 `router → service → repository`，禁止反向调用或跨层调用。
- **所有数据库查询都必须写在 `repository.py`**。router 和 service 不能出现 `select()` 或 `session.execute()`。
- router 不写业务逻辑；service 不感知 HTTP，不 import `fastapi`，也不抛 `HTTPException`。
- 跨 domain 调用时以模块形式导入并起别名：`from app.user import service as user_service`，只能调用对方的 service。

## 异步

- 路由、依赖、service、repository 一律用 `async def`。
- `async def` 中禁止任何阻塞调用：`requests`、`time.sleep`、同步 DB driver、同步文件大读写等。HTTP 客户端用 `httpx.AsyncClient`。
- 不得不调用同步 SDK 时，用 `await run_in_threadpool(fn, ...)` 包起来。
- CPU 密集型工作交给任务队列，不要放在请求里执行。

## Pydantic v2

- 只用 v2 API：`model_validate`、`model_dump`、`ConfigDict`、`field_validator`、`model_validator`。禁止使用 `.dict()`、`.from_orm()`、`class Config`、`@validator`。
- 所有 schema 都继承 `app.core.schemas.BaseSchema`，该基类已设置 `from_attributes=True`。
- 命名：`XxxBase` → `XxxCreate` / `XxxUpdate` / `XxxRead`。`Update` 的字段全部可选，默认值为 `None`，更新时用 `model_dump(exclude_unset=True)`。
- ORM 模型和 schema 必须分开，不使用 SQLModel。
- 配置用 `pydantic-settings`，按 domain 拆分各自的 `BaseSettings`，全部从环境变量读取。禁止在代码里硬编码配置值和 secret。

## 数据库

→ 详见 `docs/conventions/database.md`

- 用 SQLAlchemy 2.0 的 typed 写法：`Mapped[...]`、`mapped_column()`。
- 事务由 `SessionDep` 统一管理：请求成功时 commit，出现异常时 rollback。**service 和 repository 里禁止调用 `session.commit()`**；需要拿到自增 id 时用 `await session.flush()`。
- 所有 relationship 都设置 `lazy="raise"`，需要关联数据时在 repository 里显式写 `selectinload` 或 `joinedload`。
- join、聚合、过滤、分页都在 SQL 里完成，不要在 Python 里循环查询（N+1）。
- 修改 `models.py` 后必须生成迁移，并**人工审阅 autogenerate 的结果**：检查改名是否被识别成了删除加新增、server_default 是否正确、索引是否齐全。迁移必须能 downgrade。

## API 约定

→ 详见 `docs/conventions/api-response.md`

- 路径格式为 `/{SERVICE_NAME}/v1/{resources}`。前缀在 `main.py` 里统一挂载，domain 的 router 只写资源前缀，例如 `APIRouter(prefix="/orders", tags=["orders"])`。
- 资源名用复数 + kebab-case；JSON 字段用 snake_case。
- 所有业务接口的响应都是 `ApiResponse[T]`，结构为 `{code, message, data}`，成功时 `code=0`。
- 分页接口返回 `ApiResponse[Page[T]]`，其中 `data` 为 `{items, total, page, size}`。分页参数统一用 `PageParams` 依赖：`page` 从 1 开始，`size` 默认 20，最大 100。
- 用返回类型注解声明响应模型，例如 `-> ApiResponse[OrderRead]`。router 里用 `ok(OrderRead.model_validate(obj))` **显式转换** ORM 对象，不要把 ORM 对象直接塞进 `data`。
- HTTP 状态码保持语义：创建返回 201，删除返回 200 + `data: null`，其余情况对照错误码表。不要一律返回 200。
- 依赖统一用 `Annotated` 别名，例如 `SessionDep`、`CurrentUser`、`OrderServiceDep`，不要在参数里直接写 `= Depends(...)`。
- 需要"按 id 取实体，不存在就 404"时，写成可复用的依赖，放在 `dependencies.py`。
- 可能返回的错误要写在路由的 `responses=` 里，让 OpenAPI 文档可见。

## 错误处理

→ 详见 `docs/conventions/errors.md`

- 业务错误一律 `raise` 某个 domain 的 `AppError` 子类。每个子类要声明 `status_code`、`code`、`message`。
- 错误码是 5 位整数：`0` 表示成功，`10xxx` 为框架通用码，每个 domain 分配一个 1000 大小的号段，分配表维护在 `app/core/exceptions.py`。**禁止在代码里直接写数字错误码。**
- 全局 handler 会把 `AppError`、`HTTPException`、`RequestValidationError` 和未知异常统一转换成 `{code, message, data}`。
  - 422 的 `data` 为 `[{field, message}]`。
  - 500 只返回通用 message，不暴露堆栈或内部信息。
- `message` 面向开发和排查。用户可见的文案由前端根据 `code` 映射。
- 禁止用空的 `except` 吞掉异常。捕获异常后，要么转换成 `AppError`，要么记录日志后重新抛出。

## 认证与鉴权

- 当前用户通过 `CurrentUser` 依赖注入；权限声明用依赖，例如 `Annotated[User, Depends(require_scopes("order:write"))]`。
- 数据权限（租户、归属人过滤）只能放在 repository 方法或依赖里，并且必须带上 `user_id` / `tenant_id` 这类参数。禁止在 router 里临时拼接过滤条件。

## 日志与可观测性

- 使用 `structlog`，输出 JSON。request_id 由 `asgi-correlation-id` 生成并自动绑定到日志；trace_id 由 OpenTelemetry 注入。
- 禁止使用 `print`（ruff 的 T20 规则会检查）。日志用事件名加结构化字段：`log.info("order_created", order_id=order.id)`。
- **日志中禁止出现** token、密码、密钥、完整手机号、身份证号等敏感信息或 PII。

## 测试

→ 详见 `docs/conventions/testing.md`

- 使用真实 PostgreSQL（testcontainers），不要用 SQLite 代替。每个测试在事务里执行，结束后回滚。
- endpoint 测试使用 `httpx.AsyncClient(transport=ASGITransport(app))`。替换依赖用 `app.dependency_overrides`，不要 monkeypatch 内部实现。
- 外部 HTTP 和消息队列要 mock，数据库不要 mock。
- 修复 bug 时必须附带一个能复现该问题的回归测试。
- CI 要求覆盖率 ≥ 80%。

## 后台任务

- 必须可靠执行的任务（发消息、扣款、同步第三方等）走任务队列，由 service 层负责入队。
- `BackgroundTasks` 只能用于丢失也没关系的轻量任务。

## 安全与运维

- `/health`（liveness）和 `/ready`（检查 DB 等依赖）直接挂在 app 上，不带 `/{SERVICE_NAME}/v1` 前缀，也不包 `ApiResponse`。
- 在 `ENV=prod` 时关闭 `/docs`、`/redoc`、`/openapi.json`。
- CORS 只允许白名单来源，不要用 `allow_origins=["*"]` 同时开启 credentials。
- 初始化 DB engine、HTTP client 等资源放在 `lifespan` 里，不要用 `@app.on_event`。
- 依赖用 `uv add` 添加，必须提交 `uv.lock`。禁止用 `pip install`。
- commit 信息遵循 Conventional Commits：`feat:`、`fix:`、`refactor:`、`test:`、`docs:`、`chore:`。

## Agent 工作流

- 动手前先读相关 domain 的现有代码，照着现有模式写，不要自己发明新模式。
- **修改后先跑受影响的单个测试，再跑全量测试**。
- 不要假设 lint、类型检查或测试的失败"本来就存在"，先确认是否由本次改动引起。
- 用户没有明确要求时，不要新增第三方依赖。
- 改了 ORM 模型就必须附带迁移；改了接口就必须同步更新 schema、`responses=` 和测试。
- 只做完成任务所需的最小改动，不要顺手重构不相关的代码。
- 代码注释只解释"为什么这样做"，不要写对话过程或"按用户要求修改"之类的内容。
