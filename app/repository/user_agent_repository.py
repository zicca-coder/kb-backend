from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_agent import UserAgent


class UserAgentRepository:
    """UserAgent ORM 持久化操作。"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, user_agent: UserAgent) -> UserAgent:
        self.db.add(user_agent)
        await self.db.flush()
        return user_agent

    async def get_by_id(
        self,
        user_agent_id: int,
    ) -> UserAgent | None:
        statement = select(UserAgent).where(
            UserAgent.id == user_agent_id,
            UserAgent.is_deleted.is_(False),
        )
        result = await self.db.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_user_id(
        self,
        user_id: int,
        *,
        include_deleted: bool = False,
    ) -> UserAgent | None:
        statement = select(UserAgent).where(UserAgent.user_id == user_id)
        if not include_deleted:
            statement = statement.where(UserAgent.is_deleted.is_(False))
        result = await self.db.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_agent_id(
        self,
        agent_id: str,
        *,
        include_deleted: bool = False,
    ) -> UserAgent | None:
        statement = select(UserAgent).where(UserAgent.agent_id == agent_id)
        if not include_deleted:
            statement = statement.where(UserAgent.is_deleted.is_(False))
        result = await self.db.execute(statement)
        return result.scalar_one_or_none()

    async def list(
        self,
        *,
        offset: int,
        limit: int,
    ) -> list[UserAgent]:
        statement = (
            select(UserAgent)
            .where(UserAgent.is_deleted.is_(False))
            .order_by(UserAgent.id.asc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.db.execute(statement)
        return list(result.scalars().all())

    async def count(self) -> int:
        statement = select(func.count(UserAgent.id)).where(
            UserAgent.is_deleted.is_(False)
        )
        result = await self.db.execute(statement)
        return result.scalar_one()

    async def update(
        self,
        user_agent: UserAgent,
        changes: dict[str, object],
    ) -> UserAgent:
        for field_name, value in changes.items():
            setattr(user_agent, field_name, value)
        await self.db.flush()
        return user_agent

    async def soft_delete(
        self,
        user_agent: UserAgent,
        *,
        updated_by: str,
    ) -> UserAgent:
        user_agent.is_deleted = True
        user_agent.updated_by = updated_by
        await self.db.flush()
        return user_agent
