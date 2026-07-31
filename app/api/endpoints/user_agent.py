from typing import Annotated

from fastapi import APIRouter, Query

from app.api.dependencies import CurrentUser, UserAgentServiceDependency
from app.schemas.response import ApiResponse, success_response
from app.schemas.user_agent import (
    UserAgentCreate,
    UserAgentList,
    UserAgentRead,
    UserAgentUpdate,
)

router = APIRouter(prefix="/user-agents", tags=["用户 Agent"])
current_user_router = APIRouter(
    prefix="/user-agents",
    tags=["用户 Agent"],
)


@current_user_router.get(
    "/me",
    response_model=ApiResponse[UserAgentRead],
)
async def get_my_user_agent(
    current_user: CurrentUser,
    service: UserAgentServiceDependency,
) -> ApiResponse[UserAgentRead]:
    user_agent = UserAgentRead.model_validate(
        await service.get_by_user_id(current_user.id)
    )
    return success_response(
        data=user_agent,
        detail="查询当前用户 Agent 成功",
    )


@router.post(
    "",
    response_model=ApiResponse[UserAgentRead],
)
async def create_user_agent(
    data: UserAgentCreate,
    service: UserAgentServiceDependency,
) -> ApiResponse[UserAgentRead]:
    user_agent = UserAgentRead.model_validate(
        await service.create(data)
    )
    return success_response(data=user_agent, detail="新增用户 Agent 成功")


@router.get("", response_model=ApiResponse[UserAgentList])
async def list_user_agents(
    service: UserAgentServiceDependency,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ApiResponse[UserAgentList]:
    user_agents, total = await service.list(
        offset=offset,
        limit=limit,
    )
    result = UserAgentList(
        items=[
            UserAgentRead.model_validate(user_agent)
            for user_agent in user_agents
        ],
        total=total,
        offset=offset,
        limit=limit,
    )
    return success_response(
        data=result,
        detail="查询用户 Agent 列表成功",
    )


@router.get(
    "/{user_agent_id}",
    response_model=ApiResponse[UserAgentRead],
)
async def get_user_agent(
    user_agent_id: int,
    service: UserAgentServiceDependency,
) -> ApiResponse[UserAgentRead]:
    user_agent = UserAgentRead.model_validate(
        await service.get(user_agent_id)
    )
    return success_response(
        data=user_agent,
        detail="查询用户 Agent 详情成功",
    )


@router.patch(
    "/{user_agent_id}",
    response_model=ApiResponse[UserAgentRead],
)
async def update_user_agent(
    user_agent_id: int,
    data: UserAgentUpdate,
    service: UserAgentServiceDependency,
) -> ApiResponse[UserAgentRead]:
    user_agent = UserAgentRead.model_validate(
        await service.update(user_agent_id, data)
    )
    return success_response(
        data=user_agent,
        detail="更新用户 Agent 成功",
    )


@router.delete(
    "/{user_agent_id}",
    response_model=ApiResponse[dict[str, object]],
)
async def delete_user_agent(
    user_agent_id: int,
    service: UserAgentServiceDependency,
) -> ApiResponse[dict[str, object]]:
    await service.delete(user_agent_id)
    return success_response(data={}, detail="删除用户 Agent 成功")
