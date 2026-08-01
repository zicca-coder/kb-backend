import logging
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.dependencies import (
    AgentProvisioningServiceDependency,
    CurrentUser,
    UserAgentServiceDependency,
)
from app.schemas.response import ApiResponse, success_response
from app.schemas.user_agent import (
    UserAgentCreate,
    UserAgentList,
    UserAgentPublicRead,
    UserAgentRead,
    UserAgentUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/user-agents", tags=["user agents"])
current_user_router = APIRouter(
    prefix="/user-agents",
    tags=["user agents"],
)


@current_user_router.get(
    "/me",
    response_model=ApiResponse[UserAgentPublicRead],
)
async def get_my_user_agent(
    current_user: CurrentUser,
    service: UserAgentServiceDependency,
) -> ApiResponse[UserAgentPublicRead]:
    logger.debug(
        "进入当前用户Agent查询接口，准备调用查询服务，user_id=%s",
        current_user.id,
    )
    user_agent = UserAgentPublicRead.model_validate(
        await service.get_by_user_id(current_user.id)
    )
    logger.debug(
        "当前用户Agent查询服务调用完成，user_id=%s, provision_status=%s",
        current_user.id,
        user_agent.provision_status,
    )
    return success_response(
        data=user_agent,
        detail="Get current user Agent succeeded",
    )


@current_user_router.post(
    "/me/provision",
    response_model=ApiResponse[UserAgentPublicRead],
)
async def provision_my_user_agent(
    current_user: CurrentUser,
    service: AgentProvisioningServiceDependency,
) -> ApiResponse[UserAgentPublicRead]:
    logger.debug(
        "进入当前用户Agent创建接口，准备调用创建服务，user_id=%s",
        current_user.id,
    )
    user_agent = UserAgentPublicRead.model_validate(
        await service.provision_for_user(
            user_id=current_user.id,
            manual_retry=True,
        )
    )
    logger.debug(
        "当前用户Agent创建服务调用完成，user_id=%s, provision_status=%s",
        current_user.id,
        user_agent.provision_status,
    )
    detail = (
        "Agent provisioning completed"
        if user_agent.provision_status != "failed"
        else "Agent provisioning failed"
    )
    return success_response(data=user_agent, detail=detail)


@router.post(
    "",
    response_model=ApiResponse[UserAgentRead],
)
async def create_user_agent(
    data: UserAgentCreate,
    service: UserAgentServiceDependency,
) -> ApiResponse[UserAgentRead]:
    logger.debug(
        "进入Agent绑定创建接口，准备调用创建服务，user_id=%s, "
        "agent_id_present=%s",
        data.user_id,
        data.agent_id is not None,
    )
    user_agent = UserAgentRead.model_validate(await service.create(data))
    logger.debug(
        "Agent绑定创建服务调用完成，user_agent_id=%s, user_id=%s",
        user_agent.id,
        user_agent.user_id,
    )
    return success_response(
        data=user_agent,
        detail="Create user Agent succeeded",
    )


@router.get("", response_model=ApiResponse[UserAgentList])
async def list_user_agents(
    service: UserAgentServiceDependency,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ApiResponse[UserAgentList]:
    logger.debug(
        "进入Agent绑定列表接口，准备调用列表服务，offset=%s, limit=%s",
        offset,
        limit,
    )
    user_agents, total = await service.list(
        offset=offset,
        limit=limit,
    )
    logger.debug(
        "Agent绑定列表服务调用完成，total=%s, returned=%s",
        total,
        len(user_agents),
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
        detail="List user Agents succeeded",
    )


@router.get(
    "/{user_agent_id}",
    response_model=ApiResponse[UserAgentRead],
)
async def get_user_agent(
    user_agent_id: int,
    service: UserAgentServiceDependency,
) -> ApiResponse[UserAgentRead]:
    logger.debug(
        "进入Agent绑定详情接口，准备调用查询服务，user_agent_id=%s",
        user_agent_id,
    )
    user_agent = UserAgentRead.model_validate(
        await service.get(user_agent_id)
    )
    logger.debug(
        "Agent绑定详情查询服务调用完成，user_agent_id=%s",
        user_agent_id,
    )
    return success_response(
        data=user_agent,
        detail="Get user Agent succeeded",
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
    logger.debug(
        "进入Agent绑定更新接口，准备调用更新服务，user_agent_id=%s",
        user_agent_id,
    )
    user_agent = UserAgentRead.model_validate(
        await service.update(user_agent_id, data)
    )
    logger.debug(
        "Agent绑定更新服务调用完成，user_agent_id=%s",
        user_agent_id,
    )
    return success_response(
        data=user_agent,
        detail="Update user Agent succeeded",
    )


@router.delete(
    "/{user_agent_id}",
    response_model=ApiResponse[dict[str, object]],
)
async def delete_user_agent(
    user_agent_id: int,
    service: UserAgentServiceDependency,
) -> ApiResponse[dict[str, object]]:
    logger.debug(
        "进入Agent绑定删除接口，准备调用删除服务，user_agent_id=%s",
        user_agent_id,
    )
    await service.delete(user_agent_id)
    logger.debug(
        "Agent绑定删除服务调用完成，user_agent_id=%s",
        user_agent_id,
    )
    return success_response(data={}, detail="Delete user Agent succeeded")
