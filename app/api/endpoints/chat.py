import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.api.dependencies import ChatServiceDependency, CurrentUser
from app.core.errors import AppError
from app.schemas.chat import ChatCancelResponse, ChatRequest, ChatResponse
from app.schemas.response import ApiResponse, success_response
from app.services.chat_stream_manager import (
    ChatStreamStatus,
    chat_stream_manager,
)
from app.services.chat_service import PreparedChatRequest, ChatService
from app.utils.sse import format_sse_event

router = APIRouter(prefix="/chat", tags=["chat"])
logger = logging.getLogger("uvicorn.error")

CHAT_STREAM_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


@dataclass(frozen=True, slots=True)
class StreamQueueItem:
    kind: Literal["delta", "error", "done"]
    content: str | None = None


@router.post("", response_model=ApiResponse[ChatResponse])
async def chat(
    payload: ChatRequest,
    http_request: Request,
    current_user: CurrentUser,
    service: ChatServiceDependency,
) -> ApiResponse[ChatResponse] | StreamingResponse:
    logger.debug(
        "进入聊天接口，user_id=%s, stream=%s, message_length=%s",
        current_user.id,
        payload.stream,
        len(payload.message),
    )
    if payload.stream:
        logger.debug("聊天接口准备进入流式模式，user_id=%s", current_user.id)
        record = await chat_stream_manager.create(
            user_id=current_user.id,
            conversation_id=payload.conversation_id,
        )
        try:
            prepared = await service.prepare_chat_for_user(
                user_id=current_user.id,
                message=payload.message,
                conversation_id=payload.conversation_id,
                request_id=record.request_id,
            )
        except Exception:
            await chat_stream_manager.finish(
                request_id=record.request_id,
                status=ChatStreamStatus.FAILED,
            )
            raise
        logger.debug(
            "聊天接口流式请求准备完成，request_id=%s, user_id=%s",
            record.request_id,
            current_user.id,
        )
        return StreamingResponse(
            _chat_event_stream(
                request_id=record.request_id,
                user_id=current_user.id,
                request=http_request,
                service=service,
                prepared=prepared,
            ),
            media_type="text/event-stream",
            headers=CHAT_STREAM_HEADERS,
        )

    logger.debug("聊天接口准备进入同步模式，user_id=%s", current_user.id)
    result = await service.chat_for_user(
        user_id=current_user.id,
        message=payload.message,
        conversation_id=payload.conversation_id,
    )
    logger.debug("聊天接口同步模式调用完成，user_id=%s", current_user.id)
    return success_response(
        data=ChatResponse(answer=result.answer),
        detail="chat success",
    )


@router.post(
    "/{request_id}/cancel",
    response_model=ApiResponse[ChatCancelResponse],
)
async def cancel_chat(
    request_id: str,
    current_user: CurrentUser,
) -> ApiResponse[ChatCancelResponse]:
    logger.debug(
        "进入停止生成接口，request_id=%s, user_id=%s",
        request_id,
        current_user.id,
    )
    status = await chat_stream_manager.cancel(
        request_id=request_id,
        user_id=current_user.id,
    )
    logger.debug(
        "停止生成接口调用完成，request_id=%s, user_id=%s, status=%s",
        request_id,
        current_user.id,
        status.value,
    )
    return success_response(
        data=ChatCancelResponse(
            request_id=request_id,
            status=status.value,
        ),
        detail="已请求停止生成",
    )


async def _chat_event_stream(
    *,
    request_id: str,
    user_id: int,
    request: Request,
    service: ChatService,
    prepared: PreparedChatRequest,
):
    queue: asyncio.Queue[StreamQueueItem] = asyncio.Queue()

    async def produce() -> None:
        try:
            initial_status = await chat_stream_manager.get_status_for_user(
                request_id=request_id,
                user_id=user_id,
            )
            if initial_status == ChatStreamStatus.CANCELLING:
                return
            async for delta in service.stream_prepared_chat(
                prepared=prepared,
            ):
                record_cancelled = (
                    await chat_stream_manager.get_status_for_user(
                        request_id=request_id,
                        user_id=user_id,
                    )
                )
                if record_cancelled == ChatStreamStatus.CANCELLING:
                    return
                await queue.put(StreamQueueItem("delta", delta))
        except asyncio.CancelledError:
            raise
        except AppError as exc:
            logger.warning(
                "OpenClaw stream failed, request_id=%s, code=%s",
                request_id,
                exc.code,
            )
            await queue.put(StreamQueueItem("error", exc.message))
        except Exception as exc:
            logger.exception(
                "Unexpected chat stream failure, request_id=%s",
                request_id,
                exc_info=exc,
            )
            await queue.put(StreamQueueItem("error", "OpenClaw 服务异常"))
        finally:
            with suppress(asyncio.CancelledError):
                await queue.put(StreamQueueItem("done"))

    producer = asyncio.create_task(produce())
    await chat_stream_manager.set_task(
        request_id=request_id,
        task=producer,
    )

    stream_status = ChatStreamStatus.COMPLETED
    try:
        logger.debug("流式聊天准备发送start事件，request_id=%s", request_id)
        yield format_sse_event("start", {"request_id": request_id})
        while True:
            if await request.is_disconnected():
                logger.debug(
                    "流式聊天检测到客户端断开，request_id=%s",
                    request_id,
                )
                await chat_stream_manager.cancel(
                    request_id=request_id,
                    user_id=user_id,
                )
                stream_status = ChatStreamStatus.CANCELLED
                break

            try:
                item = await asyncio.wait_for(queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                status = await chat_stream_manager.get_status_for_user(
                    request_id=request_id,
                    user_id=user_id,
                )
                if status == ChatStreamStatus.CANCELLING:
                    stream_status = ChatStreamStatus.CANCELLED
                    logger.debug(
                        "流式聊天准备发送cancelled事件，request_id=%s",
                        request_id,
                    )
                    yield format_sse_event(
                        "cancelled",
                        {"request_id": request_id},
                    )
                    break
                continue

            status = await chat_stream_manager.get_status_for_user(
                request_id=request_id,
                user_id=user_id,
            )
            if status == ChatStreamStatus.CANCELLING:
                stream_status = ChatStreamStatus.CANCELLED
                logger.debug(
                    "流式聊天准备发送cancelled事件，request_id=%s",
                    request_id,
                )
                yield format_sse_event(
                    "cancelled",
                    {"request_id": request_id},
                )
                break

            if item.kind == "delta" and item.content is not None:
                logger.debug(
                    "流式聊天准备发送delta事件，request_id=%s, "
                    "content_length=%s",
                    request_id,
                    len(item.content),
                )
                yield format_sse_event(
                    "delta",
                    {
                        "request_id": request_id,
                        "content": item.content,
                    },
                )
                continue

            if item.kind == "error":
                stream_status = ChatStreamStatus.FAILED
                logger.debug(
                    "流式聊天准备发送error事件，request_id=%s",
                    request_id,
                )
                yield format_sse_event(
                    "error",
                    {
                        "request_id": request_id,
                        "code": "OPENCLAW_STREAM_ERROR",
                        "message": item.content or "OpenClaw 服务异常",
                    },
                )
                break

            if item.kind == "done":
                if producer.cancelled():
                    stream_status = ChatStreamStatus.CANCELLED
                    logger.debug(
                        "流式聊天准备发送cancelled事件，request_id=%s",
                        request_id,
                    )
                    yield format_sse_event(
                        "cancelled",
                        {"request_id": request_id},
                    )
                    break
                logger.debug(
                    "流式聊天准备发送done事件，request_id=%s",
                    request_id,
                )
                yield format_sse_event(
                    "done",
                    {
                        "request_id": request_id,
                        "finish_reason": "stop",
                    },
                )
                break
    except asyncio.CancelledError:
        await chat_stream_manager.cancel(
            request_id=request_id,
            user_id=user_id,
        )
        stream_status = ChatStreamStatus.CANCELLED
        raise
    finally:
        if stream_status == ChatStreamStatus.CANCELLED:
            await chat_stream_manager.cancel(
                request_id=request_id,
                user_id=user_id,
            )
        if not producer.done():
            producer.cancel()
            with suppress(asyncio.CancelledError):
                await producer
        await chat_stream_manager.finish(
            request_id=request_id,
            status=stream_status,
        )
