import logging
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.dependencies import ConversationServiceDependency, CurrentUser
from app.schemas.conversation import (
    ConversationCreate,
    ConversationId,
    ConversationList,
    ConversationRead,
    ConversationUpdate,
)
from app.schemas.conversation_message import (
    ConversationMessageList,
    ConversationMessageRead,
)
from app.schemas.response import ApiResponse, success_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post("", response_model=ApiResponse[ConversationRead])
async def create_conversation(
    current_user: CurrentUser,
    service: ConversationServiceDependency,
    data: ConversationCreate | None = None,
) -> ApiResponse[ConversationRead]:
    logger.debug("进入会话创建接口，user_id=%s", current_user.id)
    conversation = ConversationRead.model_validate(
        await service.create_for_user(
            user_id=current_user.id,
            title=data.title if data is not None else None,
        )
    )
    return success_response(data=conversation, detail="Create conversation succeeded")


@router.get("", response_model=ApiResponse[ConversationList])
async def list_conversations(
    current_user: CurrentUser,
    service: ConversationServiceDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query()] = None,
) -> ApiResponse[ConversationList]:
    logger.debug(
        "进入会话列表接口，user_id=%s, limit=%s, cursor=%s",
        current_user.id,
        limit,
        cursor,
    )
    conversations, next_cursor = await service.list_for_user(
        user_id=current_user.id,
        limit=limit,
        cursor=cursor,
    )
    return success_response(
        data=ConversationList(
            items=[
                ConversationRead.model_validate(conversation)
                for conversation in conversations
            ],
            next_cursor=next_cursor,
        ),
        detail="List conversations succeeded",
    )


@router.get("/{conversation_id}", response_model=ApiResponse[ConversationRead])
async def get_conversation(
    conversation_id: ConversationId,
    current_user: CurrentUser,
    service: ConversationServiceDependency,
) -> ApiResponse[ConversationRead]:
    conversation = ConversationRead.model_validate(
        await service.get_for_user(
            conversation_id=conversation_id,
            user_id=current_user.id,
        )
    )
    return success_response(data=conversation, detail="Get conversation succeeded")


@router.get(
    "/{conversation_id}/messages",
    response_model=ApiResponse[ConversationMessageList],
)
async def list_conversation_messages(
    conversation_id: ConversationId,
    current_user: CurrentUser,
    service: ConversationServiceDependency,
) -> ApiResponse[ConversationMessageList]:
    messages = await service.list_messages_for_user(
        conversation_id=conversation_id,
        user_id=current_user.id,
    )
    return success_response(
        data=ConversationMessageList(
            items=[
                ConversationMessageRead.model_validate(message)
                for message in messages
            ]
        ),
        detail="List conversation messages succeeded",
    )


@router.patch("/{conversation_id}", response_model=ApiResponse[ConversationRead])
async def update_conversation(
    conversation_id: ConversationId,
    data: ConversationUpdate,
    current_user: CurrentUser,
    service: ConversationServiceDependency,
) -> ApiResponse[ConversationRead]:
    conversation = ConversationRead.model_validate(
        await service.update_title(
            conversation_id=conversation_id,
            user_id=current_user.id,
            title=data.title,
        )
    )
    return success_response(data=conversation, detail="Update conversation succeeded")


@router.delete(
    "/{conversation_id}",
    response_model=ApiResponse[dict[str, object]],
)
async def delete_conversation(
    conversation_id: ConversationId,
    current_user: CurrentUser,
    service: ConversationServiceDependency,
) -> ApiResponse[dict[str, object]]:
    await service.soft_delete(
        conversation_id=conversation_id,
        user_id=current_user.id,
    )
    return success_response(data={}, detail="Delete conversation succeeded")
