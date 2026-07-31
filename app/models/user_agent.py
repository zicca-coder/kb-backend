from sqlalchemy import BigInteger, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.provisioning import ProvisionStatus
from app.models.base import Base
from app.models.mixins import AuditMixin, BigIntIdMixin, SoftDeleteMixin


class UserAgent(
    BigIntIdMixin,
    AuditMixin,
    SoftDeleteMixin,
    Base,
):
    """One-to-one binding between a platform user and an OpenClaw Agent."""

    __tablename__ = "user_agents"

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            name="uk_user_agents_user_id",
        ),
        UniqueConstraint(
            "agent_id",
            name="uk_user_agents_agent_id",
        ),
        {
            "comment": "Platform user to OpenClaw Agent binding",
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
        },
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "users.id",
            name="fk_user_agents_user",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        nullable=False,
        comment="Platform user ID",
    )

    agent_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        comment="OpenClaw Agent ID",
    )

    runtime_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="shared",
        server_default="shared",
        comment="Runtime mode",
    )

    runtime_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Runtime identifier",
    )

    provision_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ProvisionStatus.PENDING.value,
        server_default=ProvisionStatus.PENDING.value,
        comment="Agent provisioning status",
    )

    provision_error: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
        comment="Agent provisioning failure reason",
    )

    user: Mapped["User"] = relationship(
        back_populates="agent",
        lazy="selectin",
    )
