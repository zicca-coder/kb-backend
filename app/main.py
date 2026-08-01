import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from app.api.api_router import api_router
from app.core.database import engine
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.settings import settings

logger = logging.getLogger("uvicorn.error")

@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:

    base_url = f"http://{settings.app_host}:{settings.app_port}"

    """应用启动和关闭生命周期。"""
    logger.info("Swagger 文档：%s%s", base_url, settings.docs_url)
    logger.info("ReDoc 文档：%s%s", base_url, settings.redoc_url)
    yield

    await engine.dispose()


def create_app() -> FastAPI:
    """创建并组装 FastAPI 应用。"""

    configure_logging(settings)

    application = FastAPI(
        title=settings.app_name,
        debug=settings.app_debug,
        lifespan=lifespan,
    )

    register_exception_handlers(application)
    application.include_router(api_router)

    return application


app = create_app()

@app.middleware("http")
async def add_utf8_charset(request: Request, call_next):
    response = await call_next(request)

    content_type = response.headers.get("content-type", "")
    if (
        content_type.startswith("application/json")
        and "charset=" not in content_type.lower()
    ):
        response.headers["content-type"] = "application/json; charset=utf-8"

    return response
