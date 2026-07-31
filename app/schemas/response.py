from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel

DataT = TypeVar("DataT")


class ApiResponse(BaseModel, Generic[DataT]):
    """统一 API 响应体。"""

    code: int
    msg: Literal["success", "error"]
    detail: str
    data: DataT


def success_response(
    *,
    data: DataT,
    detail: str,
) -> ApiResponse[DataT]:
    """构造统一成功响应。"""

    return ApiResponse[DataT](
        code=200,
        msg="success",
        detail=detail,
        data=data,
    )


def error_response_content(
    *,
    code: int,
    detail: str,
    data: Any | None = None,
) -> dict[str, Any]:
    """构造可直接交给 JSONResponse 的统一失败响应内容。"""

    return ApiResponse[Any](
        code=code,
        msg="error",
        detail=detail,
        data=[] if data is None else data,
    ).model_dump(mode="json")
