# 数据库：SQLAlchemy 2.0 async + Alembic

## Engine 与 Session：`app/core/db.py`

```python
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated

from fastapi import Depends
from sqlalchemy import DateTime, MetaData
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

NAMING_CONVENTION = {
    "ix": "%(column_0_label)s_idx",
    "uq": "%(table_name)s_%(column_0_name)s_key",
    "ck": "%(table_name)s_%(constraint_name)s_check",
    "fk": "%(table_name)s_%(column_0_name)s_fkey",
    "pk": "%(table_name)s_pkey",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {datetime: DateTime(timezone=True)}  # 时间一律带时区（timestamptz）


engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# scope="function"（FastAPI ≥ 0.121）：退出代码在路由函数返回后、响应发送前执行，
# 这样 commit 失败时能正确返回 500。不写 scope 时，退出代码在响应发出之后才执行，
# commit 失败的时候客户端已经收到了 200。
SessionDep = Annotated[AsyncSession, Depends(get_session, scope="function")]
```

- `expire_on_commit=False`：commit 之后仍可读取 ORM 对象的属性，router 转换 schema 时不会触发额外查询。
- engine 的创建和 `await engine.dispose()` 放在 `lifespan` 里管理。上例为了简洁写成了模块级对象。

## 事务规则

- **一个请求对应一个事务**，由 `get_session` 在请求结束时统一 commit 或 rollback。
- service 和 repository 里**禁止** `session.commit()` / `session.rollback()`。需要拿到数据库生成的 id 或默认值时，调用 `await session.flush()`。
- 任务队列的 worker 里没有请求，要自己 `async with SessionFactory() as s, s.begin():` 管理事务边界。

## 模型：`app/order/models.py`

```python
from datetime import datetime

from sqlalchemy import ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class Order(Base):
    __tablename__ = "order"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    amount_cents: Mapped[int]
    paid_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", lazy="raise")
```

- 表名用单数 snake_case。时间字段以 `_at` 结尾，纯日期字段以 `_date` 结尾。
- 金额用整数存最小单位（如 `_cents`）或用 `Numeric`，禁止用 `float`。
- 所有 relationship 都设 `lazy="raise"`，需要关联数据时显式加载。

## Repository：`app/order/repository.py`

```python
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.order.models import Order


class OrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, order_id: int, *, user_id: int) -> Order | None:
        stmt = (
            select(Order)
            .where(Order.id == order_id, Order.user_id == user_id)  # 数据权限必须在这里过滤
            .options(selectinload(Order.items))
        )
        return await self.session.scalar(stmt)

    async def list_by_user(self, user_id: int, *, offset: int, limit: int) -> tuple[list[Order], int]:
        base = select(Order).where(Order.user_id == user_id)
        total = await self.session.scalar(select(func.count()).select_from(base.subquery()))
        rows = await self.session.scalars(base.order_by(Order.id.desc()).offset(offset).limit(limit))
        return list(rows), total or 0

    async def add(self, order: Order) -> Order:
        self.session.add(order)
        await self.session.flush()
        return order
```

- repository 只做数据存取，不做业务判断，也不抛业务异常。返回 `None` 或空列表，由 service 决定怎么处理。
- 有数据权限要求的查询，必须把 `user_id` 或 `tenant_id` 作为**必填**参数，不能设默认值。

## Alembic

`alembic.ini`：

```ini
file_template = %%(year)d-%%(month).2d-%%(day).2d_%%(slug)s
```

`migrations/env.py` 必须 import 所有 domain 的 `models`，否则 autogenerate 看不到这些表。

生成迁移之后逐项检查以下内容：

1. 改名是否被识别成了"删除 + 新增"。如果是，手动改成 `op.alter_column(..., new_column_name=...)`，否则会丢数据。
2. 给已有数据的表加 `NOT NULL` 列时，必须带 `server_default`，或者拆成"加可空列 → 回填数据 → 加约束"三步。
3. `downgrade()` 必须能正确执行，不能留成 `pass`。
4. 大表加索引时用 `postgresql_concurrently=True`，并且放在单独的迁移文件里（这类迁移不能在事务内执行）。
5. 一个迁移只做一件事，slug 要写清楚，例如 `add_order_paid_at`。
