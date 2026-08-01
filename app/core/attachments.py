from enum import StrEnum


class AttachmentCategory(StrEnum):
    IMAGE = "image"
    DOCUMENT = "document"


class AttachmentPurpose(StrEnum):
    CHAT_ATTACHMENT = "chat_attachment"


class AttachmentStatus(StrEnum):
    UPLOADING = "uploading"
    READY = "ready"
    FAILED = "failed"
    DELETED = "deleted"


IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp"})
DOCUMENT_EXTENSIONS = frozenset(
    {".pdf", ".txt", ".md", ".csv", ".json", ".html", ".htm"}
)
SUPPORTED_EXTENSIONS = IMAGE_EXTENSIONS | DOCUMENT_EXTENSIONS

EXTENSION_MIME_ALLOWLIST: dict[str, frozenset[str]] = {
    ".jpg": frozenset({"image/jpeg"}),
    ".jpeg": frozenset({"image/jpeg"}),
    ".png": frozenset({"image/png"}),
    ".webp": frozenset({"image/webp"}),
    ".pdf": frozenset({"application/pdf"}),
    ".txt": frozenset({"text/plain"}),
    ".md": frozenset({"text/plain", "text/markdown"}),
    ".csv": frozenset({"text/plain", "text/csv", "application/csv"}),
    ".json": frozenset({"application/json", "text/plain"}),
    ".html": frozenset({"text/html", "text/plain"}),
    ".htm": frozenset({"text/html", "text/plain"}),
}

SAFE_UPLOAD_CONTENT_TYPES = frozenset(
    {
        "application/octet-stream",
        "binary/octet-stream",
        "",
    }
)

CHAT_ATTACHMENT_PREVIEW_URL = "/api/attachments/{attachment_id}/content"
