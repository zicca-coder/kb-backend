from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.attachment import Attachment
from app.models.message_attachment import MessageAttachment


class AttachmentRepository:
    """Attachment metadata and message-link persistence helpers."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def add(self, attachment: Attachment) -> Attachment:
        self.db.add(attachment)
        await self.db.flush()
        return attachment

    async def get_for_user(
        self,
        *,
        attachment_id: str,
        user_id: int,
    ) -> Attachment | None:
        result = await self.db.execute(
            select(Attachment).where(
                Attachment.id == attachment_id,
                Attachment.user_id == user_id,
                Attachment.is_deleted.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def get_many_for_user(
        self,
        *,
        attachment_ids: list[str],
        user_id: int,
    ) -> list[Attachment]:
        if not attachment_ids:
            return []
        result = await self.db.execute(
            select(Attachment).where(
                Attachment.id.in_(attachment_ids),
                Attachment.user_id == user_id,
                Attachment.is_deleted.is_(False),
            )
        )
        return list(result.scalars().all())

    async def count_message_links(self, *, attachment_id: str) -> int:
        result = await self.db.execute(
            select(func.count(MessageAttachment.id)).where(
                MessageAttachment.attachment_id == attachment_id,
            )
        )
        return result.scalar_one()

    async def add_message_links(
        self,
        *,
        message_id: int,
        attachment_ids: list[str],
    ) -> list[MessageAttachment]:
        links = [
            MessageAttachment(
                message_id=message_id,
                attachment_id=attachment_id,
                sort_order=index,
            )
            for index, attachment_id in enumerate(attachment_ids)
        ]
        self.db.add_all(links)
        await self.db.flush()
        return links

    async def list_for_message_ids(
        self,
        *,
        message_ids: list[int],
    ) -> dict[int, list[MessageAttachment]]:
        if not message_ids:
            return {}
        result = await self.db.execute(
            select(MessageAttachment)
            .options(selectinload(MessageAttachment.attachment))
            .where(MessageAttachment.message_id.in_(message_ids))
            .order_by(
                MessageAttachment.message_id.asc(),
                MessageAttachment.sort_order.asc(),
            )
        )
        grouped: dict[int, list[MessageAttachment]] = {}
        for link in result.scalars().all():
            grouped.setdefault(link.message_id, []).append(link)
        return grouped
