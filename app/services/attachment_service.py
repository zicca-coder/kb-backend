import base64
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import PurePath
from typing import Any
from uuid import uuid4

from fastapi import UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.attachments import (
    DOCUMENT_EXTENSIONS,
    EXTENSION_MIME_ALLOWLIST,
    IMAGE_EXTENSIONS,
    SAFE_UPLOAD_CONTENT_TYPES,
    SUPPORTED_EXTENSIONS,
    AttachmentCategory,
    AttachmentPurpose,
    AttachmentStatus,
)
from app.core.errors import AppError, ResourceConflictError, ResourceNotFoundError
from app.core.settings import settings
from app.models.attachment import Attachment
from app.repository.attachment_repository import AttachmentRepository
from app.repository.conversation_repository import ConversationRepository
from app.services.conversation_service import ConversationService, SYSTEM_ACTOR
from app.services.storage_service import StorageService

logger = logging.getLogger(__name__)
FILENAME_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._() \-\u4e00-\u9fff]+")
TEXT_SAMPLE_BYTES = 8192
OPENCLAW_RESPONSES_IMAGE_MIME_TYPES = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/webp",
    }
)
OPENCLAW_RESPONSES_FILE_MIME_TYPES = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".json": "application/json",
    ".html": "text/html",
    ".htm": "text/html",
}
CHAT_INLINE_DOCUMENT_EXTENSIONS = frozenset(
    {".pdf", ".txt", ".md", ".csv", ".json", ".html", ".htm"}
)
TEXT_INLINE_DOCUMENT_EXTENSIONS = frozenset(
    {".txt", ".md", ".csv", ".json", ".html", ".htm"}
)


@dataclass(frozen=True, slots=True)
class ValidatedUpload:
    safe_filename: str
    extension: str
    category: AttachmentCategory
    file_size: int
    content_type: str
    detected_mime_type: str
    sha256: str
    data: bytes


class AttachmentService:
    """Attachment validation, storage, metadata and chat-reference rules."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        repository: AttachmentRepository | None = None,
        storage: StorageService | None = None,
        conversation_service: ConversationService | None = None,
    ) -> None:
        self.db = db
        self.repository = repository or AttachmentRepository(db)
        self.storage = storage or StorageService()
        self.conversation_service = conversation_service or ConversationService(
            db,
            repository=ConversationRepository(db),
        )

    async def upload_chat_attachment(
        self,
        *,
        user_id: int,
        file: UploadFile,
        conversation_id: str | None = None,
    ) -> Attachment:
        if conversation_id is not None:
            await self.conversation_service.get_for_user(
                conversation_id=conversation_id,
                user_id=user_id,
            )

        validated = await self._validate_upload(file)
        attachment_id = str(uuid4())
        object_key = self._object_key(
            user_id=user_id,
            attachment_id=attachment_id,
            extension=validated.extension,
        )
        attachment = Attachment(
            id=attachment_id,
            user_id=user_id,
            conversation_id=conversation_id,
            original_filename=validated.safe_filename,
            bucket_name=self.storage.bucket_name,
            object_key=object_key,
            content_type=validated.content_type,
            detected_mime_type=validated.detected_mime_type,
            extension=validated.extension,
            file_size=validated.file_size,
            sha256=validated.sha256,
            category=validated.category.value,
            purpose=AttachmentPurpose.CHAT_ATTACHMENT.value,
            status=AttachmentStatus.UPLOADING.value,
            is_deleted=False,
            created_by=SYSTEM_ACTOR,
            updated_by=SYSTEM_ACTOR,
        )

        object_uploaded = False
        try:
            await self.storage.put_object(
                object_key=object_key,
                data=validated.data,
                content_type=validated.content_type,
            )
            object_uploaded = True
            attachment.status = AttachmentStatus.READY.value
            await self.repository.add(attachment)
            await self.db.commit()
            await self.db.refresh(attachment)
        except Exception:
            if self.db.in_transaction():
                await self.db.rollback()
            if not object_uploaded:
                raise AppError(
                    code="attachment_storage_failed",
                    message="附件存储失败，请稍后重试",
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                )
            if object_uploaded:
                try:
                    await self.storage.delete_object(object_key=object_key)
                except Exception as cleanup_exc:
                    logger.warning(
                        "附件上传事务失败后清理对象失败，attachment_id=%s, "
                        "error_type=%s",
                        attachment_id,
                        type(cleanup_exc).__name__,
                    )
            raise
        return attachment

    async def get_for_user(
        self,
        *,
        attachment_id: str,
        user_id: int,
    ) -> Attachment:
        attachment = await self.repository.get_for_user(
            attachment_id=attachment_id,
            user_id=user_id,
        )
        if attachment is None:
            raise ResourceNotFoundError(
                code="attachment_not_found",
                message="附件不存在",
            )
        return attachment

    async def get_content_for_user(
        self,
        *,
        attachment_id: str,
        user_id: int,
    ) -> tuple[Attachment, bytes]:
        attachment = await self.get_for_user(
            attachment_id=attachment_id,
            user_id=user_id,
        )
        if attachment.status != AttachmentStatus.READY.value:
            raise ResourceConflictError(
                code="attachment_not_ready",
                message="附件尚未就绪",
            )
        data = await self.storage.get_object_bytes(
            object_key=attachment.object_key,
        )
        return attachment, data

    async def delete_unlinked_for_user(
        self,
        *,
        attachment_id: str,
        user_id: int,
    ) -> None:
        attachment = await self.get_for_user(
            attachment_id=attachment_id,
            user_id=user_id,
        )
        if await self.repository.count_message_links(
            attachment_id=attachment.id,
        ):
            raise ResourceConflictError(
                code="attachment_already_linked",
                message="附件已关联消息，不能删除",
            )
        try:
            await self.storage.delete_object(object_key=attachment.object_key)
            attachment.is_deleted = True
            attachment.status = AttachmentStatus.DELETED.value
            attachment.updated_by = SYSTEM_ACTOR
            await self.db.commit()
        except Exception:
            if self.db.in_transaction():
                await self.db.rollback()
            raise

    async def validate_chat_attachments(
        self,
        *,
        user_id: int,
        attachment_ids: list[str],
        conversation_id: str | None,
    ) -> list[Attachment]:
        normalized_ids = self._dedupe_stable(attachment_ids)
        if len(normalized_ids) > settings.attachment_max_count:
            raise AppError(
                code="attachment_count_exceeded",
                message=f"单条消息最多支持 {settings.attachment_max_count} 个附件",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        if not normalized_ids:
            return []

        attachments = await self.repository.get_many_for_user(
            attachment_ids=normalized_ids,
            user_id=user_id,
        )
        by_id = {attachment.id: attachment for attachment in attachments}
        ordered: list[Attachment] = []
        for attachment_id in normalized_ids:
            attachment = by_id.get(attachment_id)
            if attachment is None:
                raise ResourceNotFoundError(
                    code="attachment_not_found",
                    message="附件不存在",
                )
            if attachment.status != AttachmentStatus.READY.value:
                raise ResourceConflictError(
                    code="attachment_not_ready",
                    message="附件尚未就绪",
                )
            if attachment.category not in {
                AttachmentCategory.IMAGE.value,
                AttachmentCategory.DOCUMENT.value,
            }:
                raise AppError(
                    code="attachment_type_unsupported",
                    message="不支持的附件类型",
                    status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                )
            if (
                attachment.conversation_id is not None
                and conversation_id is not None
                and attachment.conversation_id != conversation_id
            ):
                raise ResourceConflictError(
                    code="attachment_conversation_mismatch",
                    message="附件不属于当前会话",
                )
            ordered.append(attachment)

        total_size = sum(attachment.file_size for attachment in ordered)
        if total_size > settings.attachment_total_max_size:
            raise AppError(
                code="attachment_total_size_exceeded",
                message="单条消息附件总大小超出限制",
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            )
        return ordered

    async def build_openclaw_chat_content_parts(
        self,
        *,
        message: str,
        attachments: list[Attachment],
    ) -> list[dict[str, Any]]:
        parts: list[dict[str, Any]] = []
        if message:
            parts.append({"type": "text", "text": message})
        for attachment in attachments:
            data = await self.storage.get_object_bytes(
                object_key=attachment.object_key,
            )
            if attachment.category == AttachmentCategory.IMAGE.value:
                encoded = base64.b64encode(data).decode("ascii")
                parts.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": (
                                f"data:{attachment.content_type};base64,"
                                f"{encoded}"
                            ),
                        },
                    }
                )
                continue
            if attachment.extension == ".pdf":
                parts.extend(
                    self._pdf_content_parts(
                        filename=attachment.original_filename,
                        data=data,
                    )
                )
                continue
            elif attachment.extension in TEXT_INLINE_DOCUMENT_EXTENSIONS:
                text = self._document_text_part(
                    filename=attachment.original_filename,
                    extension=attachment.extension,
                    data=data,
                )
            else:
                continue
            parts.append(
                {
                    "type": "text",
                    "text": text,
                }
            )
        return parts

    async def build_openclaw_responses_content_parts(
        self,
        *,
        message: str,
        attachments: list[Attachment],
    ) -> list[dict[str, Any]]:
        parts: list[dict[str, Any]] = []
        if message:
            parts.append({"type": "input_text", "text": message})
        else:
            parts.append(
                {
                    "type": "input_text",
                    "text": "请阅读并总结附件内容。",
                }
            )
        for attachment in attachments:
            data = await self.storage.get_object_bytes(
                object_key=attachment.object_key,
            )
            encoded = base64.b64encode(data).decode("ascii")
            if attachment.category == AttachmentCategory.IMAGE.value:
                parts.append(
                    {
                        "type": "input_image",
                        "source": {
                            "type": "base64",
                            "media_type": attachment.content_type,
                            "data": encoded,
                        },
                    }
                )
            else:
                parts.append(
                    {
                        "type": "input_file",
                        "source": {
                            "type": "base64",
                            "media_type": self._responses_file_media_type(
                                attachment,
                            ),
                            "filename": attachment.original_filename,
                            "data": encoded,
                        },
                    }
                )
        return parts

    @staticmethod
    def has_document_attachment(attachments: list[Attachment]) -> bool:
        return any(
            attachment.category == AttachmentCategory.DOCUMENT.value
            for attachment in attachments
        )

    @staticmethod
    def requires_responses_endpoint(attachments: list[Attachment]) -> bool:
        return any(
            attachment.category == AttachmentCategory.DOCUMENT.value
            and attachment.extension not in CHAT_INLINE_DOCUMENT_EXTENSIONS
            for attachment in attachments
        )

    @staticmethod
    def _responses_file_media_type(attachment: Attachment) -> str:
        return OPENCLAW_RESPONSES_FILE_MIME_TYPES.get(
            attachment.extension,
            attachment.content_type,
        )

    @staticmethod
    def _document_text_part(
        *,
        filename: str,
        extension: str,
        data: bytes,
    ) -> str:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("utf-8", errors="replace")
        language = extension.removeprefix(".") or "text"
        text = AttachmentService._truncate_text(text)
        return (
            f"\n\n附件文件名：{filename}\n"
            f"附件内容：\n```{language}\n{text}\n```"
        )

    @staticmethod
    def _pdf_content_parts(
        *,
        filename: str,
        data: bytes,
    ) -> list[dict[str, Any]]:
        text, extracted_char_count = AttachmentService._extract_pdf_text(data)
        should_render = (
            extracted_char_count < settings.attachment_pdf_text_min_chars
        )
        if should_render:
            render_notice = (
                "已将 PDF 前几页渲染为图片一并发送，"
                "请结合图片内容回答。"
            )
            if text:
                text = f"{text}\n\n{render_notice}"
            else:
                text = (
                    "未能从 PDF 中提取到足够的可读文本。"
                    "这个 PDF 可能是扫描件或图片型 PDF，"
                    f"{render_notice}"
                )

        text = AttachmentService._truncate_text(text)
        parts: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": (
                    f"\n\n附件文件名：{filename}\n"
                    f"附件类型：PDF\n"
                    f"附件内容：\n```text\n{text}\n```"
                ),
            }
        ]
        if should_render:
            for image_data in AttachmentService._render_pdf_pages(data):
                encoded = base64.b64encode(image_data).decode("ascii")
                parts.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{encoded}",
                        },
                    }
                )
        return parts

    @staticmethod
    def _extract_pdf_text(data: bytes) -> tuple[str, int]:
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise AppError(
                code="attachment_pdf_parser_unavailable",
                message="PDF 解析组件不可用",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            ) from exc

        try:
            reader = PdfReader(BytesIO(data), strict=False)
            if reader.is_encrypted:
                decrypt_result = reader.decrypt("")
                if decrypt_result == 0:
                    raise ValueError("encrypted PDF requires password")
            page_count = min(len(reader.pages), settings.attachment_pdf_max_pages)
            page_texts: list[str] = []
            for index in range(page_count):
                extracted = reader.pages[index].extract_text() or ""
                extracted = extracted.strip()
                if extracted:
                    page_texts.append(f"[第 {index + 1} 页]\n{extracted}")
        except Exception as exc:
            raise AppError(
                code="attachment_pdf_unreadable",
                message="PDF 文件无法读取，请换成可复制文本的 PDF 或先转成文本",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            ) from exc

        text = "\n\n".join(page_texts)
        return text, len(re.sub(r"\s+", "", text))

    @staticmethod
    def _render_pdf_pages(data: bytes) -> list[bytes]:
        try:
            import fitz
        except ImportError as exc:
            raise AppError(
                code="attachment_pdf_renderer_unavailable",
                message="PDF 页面渲染组件不可用",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            ) from exc

        try:
            rendered: list[bytes] = []
            with fitz.open(stream=data, filetype="pdf") as document:
                page_count = min(
                    len(document),
                    settings.attachment_pdf_render_max_pages,
                )
                matrix = fitz.Matrix(
                    settings.attachment_pdf_render_zoom,
                    settings.attachment_pdf_render_zoom,
                )
                for index in range(page_count):
                    page = document.load_page(index)
                    pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                    rendered.append(pixmap.tobytes("png"))
            return rendered
        except Exception as exc:
            raise AppError(
                code="attachment_pdf_render_failed",
                message="PDF 页面渲染失败，请换成可复制文本的 PDF 或图片",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            ) from exc

    @staticmethod
    def _truncate_text(text: str) -> str:
        limit = settings.attachment_inline_text_max_chars
        if len(text) <= limit:
            return text
        return (
            text[:limit]
            + f"\n\n[内容已截断，仅保留前 {limit} 个字符。]"
        )

    async def link_attachments_to_message(
        self,
        *,
        message_id: int,
        attachments: list[Attachment],
    ) -> None:
        if not attachments:
            return
        await self.repository.add_message_links(
            message_id=message_id,
            attachment_ids=[attachment.id for attachment in attachments],
        )

    async def _validate_upload(self, file: UploadFile) -> ValidatedUpload:
        safe_filename = self._safe_filename(file.filename)
        extension = PurePath(safe_filename).suffix.lower()
        if extension not in SUPPORTED_EXTENSIONS:
            raise AppError(
                code="attachment_type_unsupported",
                message="不支持的文件类型",
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            )

        category = (
            AttachmentCategory.IMAGE
            if extension in IMAGE_EXTENSIONS
            else AttachmentCategory.DOCUMENT
        )
        max_size = (
            settings.attachment_image_max_size
            if category == AttachmentCategory.IMAGE
            else settings.attachment_document_max_size
        )
        data = await file.read(max_size + 1)
        if not data:
            raise AppError(
                code="attachment_empty",
                message="文件内容不能为空",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        if len(data) > max_size:
            raise AppError(
                code="attachment_too_large",
                message="文件大小超出限制",
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            )

        detected = self._detect_mime(data, extension)
        self._reject_dangerous_content(data)
        self._validate_content_type(
            extension=extension,
            upload_content_type=file.content_type,
            detected_mime_type=detected,
        )
        if category == AttachmentCategory.IMAGE:
            self._verify_image(data, detected)

        return ValidatedUpload(
            safe_filename=safe_filename,
            extension=extension,
            category=category,
            file_size=len(data),
            content_type=detected,
            detected_mime_type=detected,
            sha256=hashlib.sha256(data).hexdigest(),
            data=data,
        )

    @staticmethod
    def _dedupe_stable(values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result

    @staticmethod
    def _safe_filename(filename: str | None) -> str:
        raw_name = PurePath(filename or "attachment").name.strip()
        if not raw_name or raw_name in {".", ".."}:
            raw_name = "attachment"
        safe = FILENAME_UNSAFE_CHARS.sub("_", raw_name).strip(" .")
        if not safe:
            safe = "attachment"
        return safe[:255]

    @staticmethod
    def _object_key(
        *,
        user_id: int,
        attachment_id: str,
        extension: str,
    ) -> str:
        now = datetime.utcnow()
        return (
            f"chat-attachments/{user_id}/{now:%Y}/{now:%m}/"
            f"{attachment_id}{extension}"
        )

    @staticmethod
    def _detect_mime(data: bytes, extension: str) -> str:
        if data.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return "image/webp"
        if data.startswith(b"%PDF-"):
            return "application/pdf"
        if extension == ".json":
            try:
                json.loads(data.decode("utf-8-sig"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise AppError(
                    code="attachment_mime_mismatch",
                    message="文件内容与类型不匹配",
                    status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                ) from exc
            return "application/json"
        if extension in {".html", ".htm"}:
            try:
                data[:TEXT_SAMPLE_BYTES].decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise AppError(
                    code="attachment_mime_mismatch",
                    message="文件内容与类型不匹配",
                    status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                ) from exc
            return "text/html"
        if extension in DOCUMENT_EXTENSIONS:
            try:
                data[:TEXT_SAMPLE_BYTES].decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise AppError(
                    code="attachment_mime_mismatch",
                    message="文件内容与类型不匹配",
                    status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                ) from exc
            return "text/plain"
        raise AppError(
            code="attachment_mime_mismatch",
            message="文件内容与类型不匹配",
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        )

    @staticmethod
    def _reject_dangerous_content(data: bytes) -> None:
        leading = data[:512].lstrip().lower()
        dangerous_magic = (
            data.startswith(b"MZ"),
            data.startswith(b"\x7fELF"),
            data.startswith(b"PK\x03\x04"),
            leading.startswith(b"<svg"),
        )
        if any(dangerous_magic):
            raise AppError(
                code="attachment_type_unsupported",
                message="不支持的文件类型",
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            )

    @staticmethod
    def _validate_content_type(
        *,
        extension: str,
        upload_content_type: str | None,
        detected_mime_type: str,
    ) -> None:
        allowed = EXTENSION_MIME_ALLOWLIST[extension]
        if detected_mime_type not in allowed:
            raise AppError(
                code="attachment_mime_mismatch",
                message="文件内容与类型不匹配",
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            )
        supplied = (upload_content_type or "").split(";", 1)[0].strip().lower()
        if supplied in SAFE_UPLOAD_CONTENT_TYPES:
            return
        if supplied not in allowed:
            raise AppError(
                code="attachment_mime_mismatch",
                message="文件内容与类型不匹配",
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            )

    @staticmethod
    def _verify_image(data: bytes, detected_mime_type: str) -> None:
        try:
            from PIL import Image
        except ImportError:
            return

        try:
            from io import BytesIO

            Image.MAX_IMAGE_PIXELS = settings.attachment_image_max_pixels
            with Image.open(BytesIO(data)) as image:
                if image.format is None:
                    raise ValueError("unknown image format")
                width, height = image.size
                if width * height > settings.attachment_image_max_pixels:
                    raise ValueError("image pixel count exceeded")
                if detected_mime_type == "image/jpeg" and image.format != "JPEG":
                    raise ValueError("jpeg format mismatch")
                if detected_mime_type == "image/png" and image.format != "PNG":
                    raise ValueError("png format mismatch")
                if detected_mime_type == "image/webp" and image.format != "WEBP":
                    raise ValueError("webp format mismatch")
                image.verify()
        except Exception as exc:
            raise AppError(
                code="attachment_mime_mismatch",
                message="文件内容与类型不匹配",
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            ) from exc
