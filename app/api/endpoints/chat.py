from fastapi import APIRouter

from app.api.dependencies import ChatServiceDependency, CurrentUser
from app.schemas.chat import ChatRequest, ChatResponse
from app.schemas.response import ApiResponse, success_response

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ApiResponse[ChatResponse])
async def chat(
    request: ChatRequest,
    current_user: CurrentUser,
    service: ChatServiceDependency,
) -> ApiResponse[ChatResponse]:
    result = await service.chat_for_user(
        user_id=current_user.id,
        message=request.message,
    )
    return success_response(
        data=ChatResponse(answer=result.answer),
        detail="chat success",
    )
