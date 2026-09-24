# 错误处理

## 错误响应结构

```json
{ "code": 11001, "message": "order not found", "data": null }
```

参数校验失败（422）时，`data` 是字段错误列表：

```json
{
  "code": 10001,
  "message": "validation error",
  "data": [{ "field": "amount_cents", "message": "Input should be greater than 0" }]
}
```

- `message` 面向开发和排查，用户看到的文案由前端根据 `code` 映射。
- 500 只返回通用 message，具体原因记在日志里，排查时用 `X-Request-ID` 关联。

## 错误码规则

- 共 5 位整数，`0` 表示成功。
- `10xxx` 是框架通用码，由 `app/core/exceptions.py` 统一定义。
- 每个 domain 占一个 1000 大小的号段，分配表只维护在 `app/core/exceptions.py` 顶部。新建 domain 时先在表里登记号段。
- 代码里只能引用异常类或常量，不能直接写数字。

| 号段 | 归属 |
|------|------|
| 10000–10999 | 通用（校验、认证、权限、未找到、冲突、限流、内部错误） |
| 11000–11999 | order |
| 12000–12999 | （下一个 domain） |

## 基类与通用码：`app/core/exceptions.py`

```python
"""错误码号段分配：
10xxx  通用
11xxx  order
"""
from enum import IntEnum
from typing import Any, ClassVar

import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.responses import ApiResponse

log = structlog.get_logger()


class CommonCode(IntEnum):
    HTTP_ERROR = 10000
    VALIDATION_ERROR = 10001
    UNAUTHORIZED = 10002
    FORBIDDEN = 10003
    NOT_FOUND = 10004
    CONFLICT = 10005
    TOO_MANY_REQUESTS = 10006
    INTERNAL_ERROR = 10500


class AppError(Exception):
    status_code: ClassVar[int] = status.HTTP_400_BAD_REQUEST
    code: ClassVar[int] = CommonCode.HTTP_ERROR
    message: ClassVar[str] = "bad request"

    def __init__(self, message: str | None = None, *, data: Any = None) -> None:
        self.detail = message or self.message
        self.data = data
        super().__init__(self.detail)


class Unauthorized(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = CommonCode.UNAUTHORIZED
    message = "unauthorized"


class Forbidden(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = CommonCode.FORBIDDEN
    message = "forbidden"


_HTTP_CODE_MAP: dict[int, int] = {
    401: CommonCode.UNAUTHORIZED,
    403: CommonCode.FORBIDDEN,
    404: CommonCode.NOT_FOUND,
    405: CommonCode.HTTP_ERROR,
    409: CommonCode.CONFLICT,
    429: CommonCode.TOO_MANY_REQUESTS,
}

# 用于路由的 responses=，让 OpenAPI 文档展示错误结构
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"model": ApiResponse[Any]} for code in (400, 401, 403, 404, 422)
}


def _error(status_code: int, code: int, message: str, data: Any = None) -> JSONResponse:
    body = ApiResponse[Any](code=code, message=message, data=data)
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return _error(exc.status_code, exc.code, exc.detail, exc.data)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"field": ".".join(str(p) for p in err["loc"][1:]), "message": err["msg"]}
            for err in exc.errors()
        ]
        return _error(422, CommonCode.VALIDATION_ERROR, "validation error", details)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODE_MAP.get(exc.status_code, CommonCode.HTTP_ERROR)
        return _error(exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_error")
        return _error(500, CommonCode.INTERNAL_ERROR, "internal server error")
```

说明：

- handler 注册的是 **Starlette** 的 `HTTPException`，这样框架自己抛出的 404（路由不存在）、405 等也能转换成统一格式。
- `ValueError` 在 validator 中抛出时会变成 422，在 service 中抛出时会变成 500。业务上的判断失败请抛 `AppError` 子类。

## Domain 异常：`app/order/exceptions.py`

```python
from fastapi import status

from app.core.exceptions import AppError


class OrderNotFound(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = 11001
    message = "order not found"


class OrderAlreadyPaid(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = 11002
    message = "order already paid"
```

用法：

```python
# service.py
async def get(self, order_id: int, *, user_id: int) -> Order:
    order = await self.repo.get_by_id(order_id, user_id=user_id)
    if order is None:
        raise OrderNotFound()
    return order
```

## 禁止事项

- 禁止在 service 或 repository 里抛 `fastapi.HTTPException`，service 不应该感知 HTTP。
- 禁止用 `except Exception: pass` 或 `return None` 这种方式吞掉异常。
- 禁止把异常原文、SQL、堆栈放进响应的 `message`。
- 禁止在 router 里自己拼 `{code, message, data}` 返回错误，一律 `raise` 异常。
