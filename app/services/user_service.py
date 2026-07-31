from typing import NoReturn

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ResourceConflictError, ResourceNotFoundError
from app.core.snowflake import SnowflakeGenerator, get_snowflake_generator
from app.models.user import User
from app.repository.user_repository import UserRepository
from app.schemas.user import UserCreate, UserUpdate

SYSTEM_ACTOR = "system"


class UserService:
    """User 业务规则与事务边界。"""

    def __init__(
        self,
        db: AsyncSession,
        repository: UserRepository | None = None,
        snowflake_generator: SnowflakeGenerator | None = None,
    ) -> None:
        self.db = db
        self.repository = repository or UserRepository(db)
        self.snowflake_generator = (
            snowflake_generator or get_snowflake_generator()
        )

    @staticmethod
    def _normalize_username(username: str) -> str:
        return username.strip().lower()

    @staticmethod
    def _normalize_phone(phone: str | None) -> str | None:
        return phone.strip() if phone is not None else None

    @staticmethod
    def _normalize_email(email: str | None) -> str | None:
        return email.strip().lower() if email is not None else None

    @staticmethod
    def _normalize_display_name(display_name: str) -> str:
        return display_name.strip()

    async def _get_or_raise(self, user_id: int) -> User:
        user = await self.repository.get_by_id(user_id)
        if user is None:
            raise ResourceNotFoundError(
                code="user_not_found",
                message=f"用户 {user_id} 不存在",
            )
        return user

    async def _ensure_identity_available(
        self,
        *,
        username: str | None = None,
        phone: str | None = None,
        exclude_user_id: int | None = None,
    ) -> None:
        if username is not None:
            existing = await self.repository.get_by_username(
                username,
                include_deleted=True,
            )
            if existing is not None and existing.id != exclude_user_id:
                raise ResourceConflictError(
                    code="username_conflict",
                    message="用户名已存在",
                )

        if phone is not None:
            existing = await self.repository.get_by_phone(
                phone,
                include_deleted=True,
            )
            if existing is not None and existing.id != exclude_user_id:
                raise ResourceConflictError(
                    code="phone_conflict",
                    message="手机号已存在",
                )

    async def _commit(self) -> None:
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self._raise_integrity_conflict(exc)
        except Exception:
            await self.db.rollback()
            raise

    async def _raise_integrity_conflict(
        self,
        exc: IntegrityError,
    ) -> NoReturn:
        await self.db.rollback()
        raise ResourceConflictError(
            code="user_conflict",
            message="用户名或手机号已存在",
        ) from exc

    async def create(self, data: UserCreate) -> User:
        username = self._normalize_username(data.username)
        phone = self._normalize_phone(data.phone)
        email = self._normalize_email(
            str(data.email) if data.email is not None else None
        )
        await self._ensure_identity_available(
            username=username,
            phone=phone,
        )

        user = User(
            id=self.snowflake_generator.next_id(),
            username=username,
            phone=phone,
            display_name=self._normalize_display_name(data.display_name),
            email=email,
            is_deleted=False,
            created_by=SYSTEM_ACTOR,
            updated_by=SYSTEM_ACTOR,
        )

        try:
            await self.repository.create(user)
            await self._commit()
            await self.db.refresh(user)
        except IntegrityError as exc:
            await self._raise_integrity_conflict(exc)
        except Exception:
            if self.db.in_transaction():
                await self.db.rollback()
            raise
        return user

    async def list(
        self,
        *,
        offset: int,
        limit: int,
    ) -> tuple[list[User], int]:
        return (
            await self.repository.list(offset=offset, limit=limit),
            await self.repository.count(),
        )

    async def get(self, user_id: int) -> User:
        return await self._get_or_raise(user_id)

    async def update(self, user_id: int, data: UserUpdate) -> User:
        user = await self._get_or_raise(user_id)
        changes = data.model_dump(exclude_unset=True)
        if not changes:
            return user

        if "username" in changes:
            changes["username"] = self._normalize_username(changes["username"])
        if "phone" in changes:
            changes["phone"] = self._normalize_phone(changes["phone"])
        if "email" in changes:
            email = changes["email"]
            changes["email"] = self._normalize_email(
                str(email) if email is not None else None
            )
        if "display_name" in changes:
            changes["display_name"] = self._normalize_display_name(
                changes["display_name"]
            )

        await self._ensure_identity_available(
            username=changes.get("username"),
            phone=changes.get("phone"),
            exclude_user_id=user_id,
        )
        changes["updated_by"] = SYSTEM_ACTOR

        try:
            await self.repository.update(user, changes)
            await self._commit()
            await self.db.refresh(user)
        except IntegrityError as exc:
            await self._raise_integrity_conflict(exc)
        except Exception:
            if self.db.in_transaction():
                await self.db.rollback()
            raise
        return user

    async def delete(self, user_id: int) -> None:
        user = await self._get_or_raise(user_id)
        try:
            await self.repository.soft_delete(
                user,
                updated_by=SYSTEM_ACTOR,
            )
            await self._commit()
        except Exception:
            if self.db.in_transaction():
                await self.db.rollback()
            raise
