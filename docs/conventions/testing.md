# 测试

## 原则

- 测试用真实的 PostgreSQL（testcontainers），不要用 SQLite 代替，二者在类型、约束、事务行为上都有差异。
- 每个测试跑在一个外层事务里，测试结束时回滚。测试之间不共享数据。
- 需要 mock 的只有外部 HTTP、消息队列、第三方 SDK；数据库和本服务内部的 service 不 mock。
- 替换依赖统一用 `app.dependency_overrides`，不要 monkeypatch 内部函数。
- 修 bug 必须同时提交回归测试，确保在修复前这个测试能复现失败。
- CI 门槛：`pytest --cov=app --cov-fail-under=80`。

## 目录

```
tests/
  conftest.py          # 数据库容器、session、client、认证 fixture
  factories.py         # 测试数据构造函数
  order/
    test_router.py     # 接口测试：状态码 + 响应结构
    test_service.py    # 业务规则测试
```

## `pyproject.toml`

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "session"
asyncio_default_test_loop_scope = "session"   # 需要 pytest-asyncio ≥ 1.0，所有测试共用一个 event loop
testpaths = ["tests"]
```

## `tests/conftest.py`

```python
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from testcontainers.postgres import PostgresContainer

from app.core.db import Base, get_session
from app.core.security import get_current_user
from app.main import app


@pytest.fixture(scope="session")
async def engine() -> AsyncIterator[AsyncEngine]:
    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as pg:
        engine = create_async_engine(pg.get_connection_url())
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield engine
        await engine.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with engine.connect() as conn:
        trans = await conn.begin()
        # 业务代码里的 commit 只会释放 savepoint，外层事务在测试结束时整体回滚
        s = AsyncSession(bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint")
        try:
            yield s
        finally:
            await s.close()
            await trans.rollback()


@pytest.fixture
async def client(session: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def _session_override() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_current_user] = lambda: FakeUser(id=1)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
```

`FakeUser` 在 `tests/factories.py` 里定义。如果想让测试同时覆盖迁移脚本，可以把 `create_all` 换成在容器上执行 `alembic upgrade head`。

## 接口测试示例：`tests/order/test_router.py`

```python
from httpx import AsyncClient

PREFIX = "/order-service/v1/orders"  # 与测试环境 SERVICE_NAME 一致


async def test_get_order_not_found_returns_404_with_error_code(client: AsyncClient) -> None:
    resp = await client.get(f"{PREFIX}/999")

    assert resp.status_code == 404
    assert resp.json() == {"code": 11001, "message": "order not found", "data": None}


async def test_list_orders_returns_page(client: AsyncClient, order_factory) -> None:
    await order_factory(user_id=1, title="a")

    resp = await client.get(PREFIX, params={"page": 1, "size": 10})

    body = resp.json()
    assert resp.status_code == 200
    assert body["code"] == 0
    assert body["data"]["total"] == 1
    assert body["data"]["items"][0]["title"] == "a"
```

- 测试名用 `test_<行为>_<条件>_<预期>` 的格式。
- 每个接口至少覆盖三类场景：成功、校验失败（422）、业务错误（对应的 `code`）。
- 对错误响应做断言时，要把 HTTP 状态码和 body 里的 `code` 都断言上。
