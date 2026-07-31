import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.schemas.response import error_response_content

logger = logging.getLogger(__name__)


class OpenClawError(Exception):
    """OpenClaw client base exception."""


class OpenClawConfigurationError(OpenClawError):
    """OpenClaw client configuration is invalid."""


class OpenClawConnectionError(OpenClawError):
    """Cannot connect to OpenClaw Gateway."""


class OpenClawTimeoutError(OpenClawError):
    """Backend timed out while waiting for OpenClaw Gateway."""


class OpenClawAuthenticationError(OpenClawError):
    """OpenClaw Gateway authentication failed."""


class OpenClawConflictError(OpenClawError):
    """OpenClaw Agent configuration conflicts with the request."""


class OpenClawRequestError(OpenClawError):
    """OpenClaw rejected the request."""


class OpenClawResponseError(OpenClawError):
    """OpenClaw returned an invalid or unsuccessful response."""


class OpenClawRuntimeNotReadyError(OpenClawResponseError):
    """OpenClaw Agent exists but runtime is not ready for chat."""


class AppError(Exception):
    """可安全映射为 HTTP 响应的应用错误。"""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int,
        details: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details
        self.headers = headers


class ResourceNotFoundError(AppError):
    """请求的领域资源不存在。"""

    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(
            code=code,
            message=message,
            status_code=status.HTTP_404_NOT_FOUND,
        )


class ResourceConflictError(AppError):
    """领域资源违反唯一性或状态约束。"""

    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(
            code=code,
            message=message,
            status_code=status.HTTP_409_CONFLICT,
        )


class AuthenticationError(AppError):
    """请求未通过身份认证。"""

    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(
            code=code,
            message=message,
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"},
        )


def _validation_details(
    exc: RequestValidationError,
) -> list[dict[str, Any]]:
    """将校验上下文中的异常值转换成 JSON 安全字符串。"""

    details: list[dict[str, Any]] = []
    for error in exc.errors():
        normalized = dict(error)
        context = normalized.get("ctx")
        if isinstance(context, dict):
            normalized["ctx"] = {
                key: str(value)
                for key, value in context.items()
            }
        details.append(normalized)
    return details


def register_exception_handlers(app: FastAPI) -> None:
    """注册全局应用错误和请求校验错误处理器。"""

    @app.exception_handler(AppError)
    async def handle_app_error(
        _request: Request,
        exc: AppError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_response_content(
                code=exc.status_code,
                detail=exc.message,
                data=exc.details,
            ),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=error_response_content(
                code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="请求参数校验失败",
                data=_validation_details(exc),
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        _request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        detail = (
            exc.detail
            if isinstance(exc.detail, str)
            else "请求处理失败"
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=error_response_content(
                code=exc.status_code,
                detail=detail,
            ),
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        logger.exception(
            "未处理的服务端异常: %s %s",
            request.method,
            request.url.path,
            exc_info=exc,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_response_content(
                code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="服务器内部错误",
            ),
        )
