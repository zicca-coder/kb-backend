from typing import Annotated

from fastapi import APIRouter, Query

from app.api.dependencies import UserServiceDependency
from app.schemas.response import ApiResponse, success_response
from app.schemas.user import UserCreate, UserList, UserRead, UserUpdate

router = APIRouter(prefix="/users", tags=["用户"])


@router.post(
    "",
    response_model=ApiResponse[UserRead],
)
async def create_user(
    data: UserCreate,
    service: UserServiceDependency,
) -> ApiResponse[UserRead]:
    user = UserRead.model_validate(await service.create(data))
    return success_response(data=user, detail="新增用户成功")


@router.get("", response_model=ApiResponse[UserList])
async def list_users(
    service: UserServiceDependency,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ApiResponse[UserList]:
    users, total = await service.list(offset=offset, limit=limit)
    result = UserList(
        items=[UserRead.model_validate(user) for user in users],
        total=total,
        offset=offset,
        limit=limit,
    )
    return success_response(data=result, detail="查询用户列表成功")


@router.get("/{user_id}", response_model=ApiResponse[UserRead])
async def get_user(
    user_id: int,
    service: UserServiceDependency,
) -> ApiResponse[UserRead]:
    user = UserRead.model_validate(await service.get(user_id))
    return success_response(data=user, detail="查询用户详情成功")


@router.patch("/{user_id}", response_model=ApiResponse[UserRead])
async def update_user(
    user_id: int,
    data: UserUpdate,
    service: UserServiceDependency,
) -> ApiResponse[UserRead]:
    user = UserRead.model_validate(
        await service.update(user_id, data)
    )
    return success_response(data=user, detail="更新用户成功")


@router.delete(
    "/{user_id}",
    response_model=ApiResponse[dict[str, object]],
)
async def delete_user(
    user_id: int,
    service: UserServiceDependency,
) -> ApiResponse[dict[str, object]]:
    await service.delete(user_id)
    return success_response(data={}, detail="删除用户成功")
