from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UserRepository:
    """User ORM 持久化操作。"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, user: User) -> User:
        self.db.add(user)
        await self.db.flush()
        return user

    async def get_by_id(self, user_id: int) -> User | None:
        statement = select(User).where(
            User.id == user_id,
            User.is_deleted.is_(False),
        )
        result = await self.db.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_username(
        self,
        username: str,
        *,
        include_deleted: bool = False,
    ) -> User | None:
        statement = select(User).where(User.username == username)
        if not include_deleted:
            statement = statement.where(User.is_deleted.is_(False))
        result = await self.db.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_phone(
        self,
        phone: str,
        *,
        include_deleted: bool = False,
    ) -> User | None:
        statement = select(User).where(User.phone == phone)
        if not include_deleted:
            statement = statement.where(User.is_deleted.is_(False))
        result = await self.db.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_login_account(self, account: str) -> User | None:
        statement = select(User).where(
            User.is_deleted.is_(False),
            or_(
                User.username == account,
                User.phone == account,
            ),
        )
        result = await self.db.execute(statement)
        return result.scalar_one_or_none()

    async def list(self, *, offset: int, limit: int) -> list[User]:
        statement = (
            select(User)
            .where(User.is_deleted.is_(False))
            .order_by(User.id.asc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.db.execute(statement)
        return list(result.scalars().all())

    async def count(self) -> int:
        statement = select(func.count(User.id)).where(
            User.is_deleted.is_(False)
        )
        result = await self.db.execute(statement)
        return result.scalar_one()

    async def update(
        self,
        user: User,
        changes: dict[str, object],
    ) -> User:
        for field_name, value in changes.items():
            setattr(user, field_name, value)
        await self.db.flush()
        return user

    async def soft_delete(
        self,
        user: User,
        *,
        updated_by: str,
    ) -> User:
        user.is_deleted = True
        user.updated_by = updated_by
        await self.db.flush()
        return user
