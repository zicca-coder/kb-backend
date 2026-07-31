from typing import NoReturn

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ResourceConflictError, ResourceNotFoundError
from app.models.user_agent import UserAgent
from app.repository.user_agent_repository import UserAgentRepository
from app.repository.user_repository import UserRepository
from app.schemas.user_agent import UserAgentCreate, UserAgentUpdate

SYSTEM_ACTOR = "system"


class UserAgentService:
    """UserAgent 业务规则与事务边界。"""

    def __init__(
        self,
        db: AsyncSession,
        repository: UserAgentRepository | None = None,
        user_repository: UserRepository | None = None,
    ) -> None:
        self.db = db
        self.repository = repository or UserAgentRepository(db)
        self.user_repository = user_repository or UserRepository(db)

    @staticmethod
    def _normalize_string(value: str) -> str:
        return value.strip()

    @staticmethod
    def _normalize_optional_string(value: str | None) -> str | None:
        return value.strip() if value is not None else None

    async def _get_or_raise(
        self,
        user_agent_id: int,
    ) -> UserAgent:
        user_agent = await self.repository.get_by_id(user_agent_id)
        if user_agent is None:
            raise ResourceNotFoundError(
                code="user_agent_not_found",
                message=f"用户 Agent 映射 {user_agent_id} 不存在",
            )
        return user_agent

    async def _ensure_user_exists(self, user_id: int) -> None:
        if await self.user_repository.get_by_id(user_id) is None:
            raise ResourceNotFoundError(
                code="user_not_found",
                message=f"用户 {user_id} 不存在",
            )

    async def _ensure_identity_available(
        self,
        *,
        user_id: int | None = None,
        agent_id: str | None = None,
        exclude_user_agent_id: int | None = None,
    ) -> None:
        if user_id is not None:
            existing = await self.repository.get_by_user_id(
                user_id,
                include_deleted=True,
            )
            if (
                existing is not None
                and existing.id != exclude_user_agent_id
            ):
                raise ResourceConflictError(
                    code="user_agent_user_conflict",
                    message="该用户已绑定 Agent",
                )

        if agent_id is not None:
            existing = await self.repository.get_by_agent_id(
                agent_id,
                include_deleted=True,
            )
            if (
                existing is not None
                and existing.id != exclude_user_agent_id
            ):
                raise ResourceConflictError(
                    code="user_agent_id_conflict",
                    message="Agent ID 已存在",
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
            code="user_agent_conflict",
            message="用户或 Agent ID 已存在绑定关系",
        ) from exc

    async def create(self, data: UserAgentCreate) -> UserAgent:
        await self._ensure_user_exists(data.user_id)

        agent_id = self._normalize_optional_string(data.agent_id)
        await self._ensure_identity_available(
            user_id=data.user_id,
            agent_id=agent_id,
        )

        user_agent = UserAgent(
            user_id=data.user_id,
            agent_id=agent_id,
            runtime_type=data.runtime_type,
            runtime_id=self._normalize_optional_string(data.runtime_id),
            provision_status=data.provision_status,
            provision_error=self._normalize_optional_string(
                data.provision_error
            ),
            is_deleted=False,
            created_by=SYSTEM_ACTOR,
            updated_by=SYSTEM_ACTOR,
        )

        try:
            await self.repository.create(user_agent)
            await self._commit()
            await self.db.refresh(user_agent)
        except IntegrityError as exc:
            await self._raise_integrity_conflict(exc)
        except Exception:
            if self.db.in_transaction():
                await self.db.rollback()
            raise
        return user_agent

    async def list(
        self,
        *,
        offset: int,
        limit: int,
    ) -> tuple[list[UserAgent], int]:
        return (
            await self.repository.list(offset=offset, limit=limit),
            await self.repository.count(),
        )

    async def get(self, user_agent_id: int) -> UserAgent:
        return await self._get_or_raise(user_agent_id)

    async def get_by_user_id(self, user_id: int) -> UserAgent:
        user_agent = await self.repository.get_by_user_id(user_id)
        if user_agent is None:
            raise ResourceNotFoundError(
                code="user_agent_not_found",
                message="User agent not found",
            )
        return user_agent

    async def update(
        self,
        user_agent_id: int,
        data: UserAgentUpdate,
    ) -> UserAgent:
        user_agent = await self._get_or_raise(user_agent_id)
        changes = data.model_dump(exclude_unset=True)
        if not changes:
            return user_agent

        if "user_id" in changes:
            await self._ensure_user_exists(changes["user_id"])

        string_fields = ("agent_id",)
        for field_name in string_fields:
            if field_name in changes:
                changes[field_name] = self._normalize_string(
                    changes[field_name]
                )

        for field_name in ("runtime_id", "provision_error"):
            if field_name in changes:
                changes[field_name] = self._normalize_optional_string(
                    changes[field_name]
                )

        await self._ensure_identity_available(
            user_id=changes.get("user_id"),
            agent_id=changes.get("agent_id"),
            exclude_user_agent_id=user_agent_id,
        )
        changes["updated_by"] = SYSTEM_ACTOR

        try:
            await self.repository.update(user_agent, changes)
            await self._commit()
            await self.db.refresh(user_agent)
        except IntegrityError as exc:
            await self._raise_integrity_conflict(exc)
        except Exception:
            if self.db.in_transaction():
                await self.db.rollback()
            raise
        return user_agent

    async def delete(self, user_agent_id: int) -> None:
        user_agent = await self._get_or_raise(user_agent_id)
        try:
            await self.repository.soft_delete(
                user_agent,
                updated_by=SYSTEM_ACTOR,
            )
            await self._commit()
        except Exception:
            if self.db.in_transaction():
                await self.db.rollback()
            raise
