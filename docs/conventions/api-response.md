# API 响应与路由约定

## 统一响应结构

业务接口的响应体一律是：

```json
{ "code": 0, "message": "ok", "data": { "...": "..." } }
```

分页接口：

```json
{
  "code": 0,
  "message": "ok",
  "data": { "items": [], "total": 135, "page": 1, "size": 20 }
}
```

HTTP 状态码保持语义（200 / 201 / 400 / 401 / 403 / 404 / 409 / 422 / 500），body 里的 `code` 用来区分具体的业务错误。错误结构见 [errors.md](errors.md)。

## 基础模型：`app/core/schemas.py`

```python
from pydantic import BaseModel, ConfigDict


class BaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
```

## 响应模型：`app/core/responses.py`

```python
from app.core.schemas import BaseSchema


class ApiResponse[T](BaseSchema):
    code: int = 0
    message: str = "ok"
    data: T | None = None


class Page[T](BaseSchema):
    items: list[T]
    total: int
    page: int
    size: int


def ok[T](data: T) -> ApiResponse[T]:
    return ApiResponse[T](data=data)
```

## 分页参数：`app/core/pagination.py`

```python
from typing import Annotated

from fastapi import Query
from pydantic import Field

from app.core.schemas import BaseSchema


class PageQuery(BaseSchema):
    page: int = Field(1, ge=1)
    size: int = Field(20, ge=1, le=100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size


PageParams = Annotated[PageQuery, Query()]  # FastAPI ≥ 0.115 的 Query Parameter Models
```

## Schema 命名：`app/order/schemas.py`

```python
from datetime import datetime

from app.core.schemas import BaseSchema


class OrderBase(BaseSchema):
    title: str
    amount_cents: int


class OrderCreate(OrderBase):
    pass


class OrderUpdate(BaseSchema):
    title: str | None = None
    amount_cents: int | None = None


class OrderRead(OrderBase):
    id: int
    created_at: datetime
```

## Router 写法：`app/order/router.py`

```python
from fastapi import APIRouter, status

from app.core.exceptions import ERROR_RESPONSES
from app.core.pagination import PageParams
from app.core.responses import ApiResponse, Page, ok
from app.core.security import CurrentUser
from app.order.dependencies import OrderServiceDep, ValidOrder
from app.order.schemas import OrderCreate, OrderRead, OrderUpdate

router = APIRouter(prefix="/orders", tags=["orders"])


@router.get("", responses=ERROR_RESPONSES)
async def list_orders(
    user: CurrentUser, params: PageParams, service: OrderServiceDep
) -> ApiResponse[Page[OrderRead]]:
    orders, total = await service.list(user_id=user.id, offset=params.offset, limit=params.size)
    return ok(Page[OrderRead](
        items=[OrderRead.model_validate(o) for o in orders],
        total=total, page=params.page, size=params.size,
    ))


@router.get("/{order_id}", responses=ERROR_RESPONSES)
async def get_order(order: ValidOrder) -> ApiResponse[OrderRead]:
    return ok(OrderRead.model_validate(order))


@router.post("", status_code=status.HTTP_201_CREATED, responses=ERROR_RESPONSES)
async def create_order(
    user: CurrentUser, body: OrderCreate, service: OrderServiceDep
) -> ApiResponse[OrderRead]:
    order = await service.create(body, user_id=user.id)
    return ok(OrderRead.model_validate(order))


@router.patch("/{order_id}", responses=ERROR_RESPONSES)
async def update_order(
    order: ValidOrder, body: OrderUpdate, service: OrderServiceDep
) -> ApiResponse[OrderRead]:
    order = await service.update(order, body.model_dump(exclude_unset=True))
    return ok(OrderRead.model_validate(order))


@router.delete("/{order_id}", responses=ERROR_RESPONSES)
async def delete_order(order: ValidOrder, service: OrderServiceDep) -> ApiResponse[None]:
    await service.delete(order)
    return ok(None)
```

删除接口返回 200 和 `data: null`，不返回 204，因为 204 不能带 body，和统一响应结构冲突。

## 依赖：`app/order/dependencies.py`

```python
from typing import Annotated

from fastapi import Depends

from app.core.db import SessionDep
from app.core.security import CurrentUser
from app.order.models import Order
from app.order.repository import OrderRepository
from app.order.service import OrderService


async def get_order_service(session: SessionDep) -> OrderService:
    return OrderService(OrderRepository(session))


OrderServiceDep = Annotated[OrderService, Depends(get_order_service)]


async def valid_order(order_id: int, user: CurrentUser, service: OrderServiceDep) -> Order:
    # 不存在或不属于当前用户 → service 抛 OrderNotFound → 404
    return await service.get(order_id, user_id=user.id)


ValidOrder = Annotated[Order, Depends(valid_order)]
```

- 依赖在同一个请求内会被缓存，所以 `valid_order` 和路由里的 `OrderServiceDep` 拿到的是同一个 service 实例，也共用同一个 session。
- 不需要 await 的简单依赖也写成 `async def`。写成同步 `def` 会被放进 threadpool 执行，白白增加开销。

## 挂载前缀：`app/main.py`

```python
from fastapi import APIRouter, FastAPI

from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.order.router import router as order_router


def create_app() -> FastAPI:
    is_prod = settings.ENV == "prod"
    app = FastAPI(
        title=settings.SERVICE_NAME,
        lifespan=lifespan,
        openapi_url=None if is_prod else "/openapi.json",
        docs_url=None if is_prod else "/docs",
        redoc_url=None,
    )
    register_exception_handlers(app)

    api = APIRouter(prefix=f"/{settings.SERVICE_NAME}/v1")
    api.include_router(order_router)
    app.include_router(api)

    @app.get("/health", include_in_schema=False)
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
```

网关按 `/{SERVICE_NAME}` 路由，并且**不剥离前缀**。所以无论本地直连还是经过网关，路径都一样。
