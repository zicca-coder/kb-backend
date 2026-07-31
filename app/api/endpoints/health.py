from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.dependencies import DatabaseDependency
from app.schemas.response import (
    ApiResponse,
    error_response_content,
    success_response,
)


router = APIRouter(
    tags=["运行状态"],
)


@router.get(
    "/",
    response_model=ApiResponse[dict[str, str]],
)
async def root() -> ApiResponse[dict[str, str]]:
    return success_response(
        data={"message": "Darwin Knowledge Platform API"},
        detail="服务访问成功",
    )


@router.get(
    "/health/live",
    response_model=ApiResponse[dict[str, str]],
)
async def check_liveness() -> ApiResponse[dict[str, str]]:
    """进程存活检查，不访问外部依赖。"""

    return success_response(
        data={"status": "alive"},
        detail="服务存活",
    )


@router.get(
    "/health/ready",
    response_model=ApiResponse[dict[str, object]],
)
async def check_readiness(
    db: DatabaseDependency,
) -> ApiResponse[dict[str, object]] | JSONResponse:
    """检查数据库是否已就绪。"""

    try:
        result = await db.execute(text("SELECT 1"))
        result.scalar_one()
        return success_response(
            data={
                "status": "ready",
                "checks": {"database": "ok"},
            },
            detail="服务已就绪",
        )
    except SQLAlchemyError:
        try:
            await db.rollback()
        except SQLAlchemyError:
            pass
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=error_response_content(
                code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="服务尚未就绪",
                data={
                    "status": "unavailable",
                    "checks": {"database": "failed"},
                },
            ),
        )
