from urllib.parse import quote

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import Response

from app.api.dependencies import AttachmentServiceDependency, CurrentUser
from app.core.attachments import AttachmentPurpose
from app.schemas.attachment import AttachmentDetail, AttachmentRead
from app.schemas.response import ApiResponse, success_response

router = APIRouter(prefix="/attachments", tags=["attachments"])


@router.post("", response_model=ApiResponse[AttachmentRead])
async def upload_attachment(
    current_user: CurrentUser,
    service: AttachmentServiceDependency,
    file: UploadFile = File(...),
    conversation_id: str | None = Form(default=None),
    purpose: str = Form(default=AttachmentPurpose.CHAT_ATTACHMENT.value),
) -> ApiResponse[AttachmentRead]:
    if purpose != AttachmentPurpose.CHAT_ATTACHMENT.value:
        from fastapi import status

        from app.core.errors import AppError

        raise AppError(
            code="attachment_purpose_unsupported",
            message="不支持的附件用途",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    attachment = await service.upload_chat_attachment(
        user_id=current_user.id,
        file=file,
        conversation_id=conversation_id,
    )
    return success_response(
        data=AttachmentRead.from_attachment(attachment),
        detail="Upload attachment succeeded",
    )


@router.get("/{attachment_id}", response_model=ApiResponse[AttachmentDetail])
async def get_attachment(
    attachment_id: str,
    current_user: CurrentUser,
    service: AttachmentServiceDependency,
) -> ApiResponse[AttachmentDetail]:
    attachment = await service.get_for_user(
        attachment_id=attachment_id,
        user_id=current_user.id,
    )
    return success_response(
        data=AttachmentDetail.from_attachment(attachment),
        detail="Get attachment succeeded",
    )


@router.get("/{attachment_id}/content")
async def get_attachment_content(
    attachment_id: str,
    current_user: CurrentUser,
    service: AttachmentServiceDependency,
) -> Response:
    attachment, data = await service.get_content_for_user(
        attachment_id=attachment_id,
        user_id=current_user.id,
    )
    disposition_type = (
        "inline" if attachment.category == "image" else "attachment"
    )
    encoded_filename = quote(attachment.original_filename)
    return Response(
        content=data,
        media_type=attachment.content_type,
        headers={
            "Content-Disposition": (
                f"{disposition_type}; filename*=UTF-8''{encoded_filename}"
            ),
            "Cache-Control": "private, max-age=300",
        },
    )


@router.delete(
    "/{attachment_id}",
    response_model=ApiResponse[dict[str, object]],
)
async def delete_attachment(
    attachment_id: str,
    current_user: CurrentUser,
    service: AttachmentServiceDependency,
) -> ApiResponse[dict[str, object]]:
    await service.delete_unlinked_for_user(
        attachment_id=attachment_id,
        user_id=current_user.id,
    )
    return success_response(data={}, detail="Delete attachment succeeded")
