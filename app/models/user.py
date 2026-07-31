from sqlalchemy import BigInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import AuditMixin, SoftDeleteMixin
from typing import TYPE_CHECKING

from sqlalchemy.orm import Mapped, relationship

if TYPE_CHECKING:
    from app.models.user_agent import UserAgent


class User(
    AuditMixin,
    SoftDeleteMixin,
    Base,
):
    """平台用户 ORM 模型。"""

    __tablename__ = "users"

    __table_args__ = (
        UniqueConstraint(
            "username",
            name="uk_users_username",
        ),
        UniqueConstraint(
            "phone",
            name="uk_users_phone",
        ),
        {
            "comment": "用户表",
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
        },
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=False,
        comment="Snowflake user ID",
    )

    username: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="用户名，可用于登录",
    )

    phone: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        comment="手机号，可用于Web端登录",
    )

    display_name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="用户展示名称",
    )

    email: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="用户邮箱",
    )

    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Web端登录密码哈希，禁止存储明文密码",
    )

    agent: Mapped["UserAgent | None"] = relationship(
        back_populates="user",
        uselist=False,
        lazy="selectin",
    )
