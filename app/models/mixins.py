from datetime import datetime

from sqlalchemy import Boolean, String, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column


class BigIntIdMixin:
    """MySQL 无符号 BIGINT 自增主键。"""

    id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        primary_key=True,
        autoincrement=True,
        comment="主键",
    )


class AuditMixin:
    """通用审计字段。"""

    created_by: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="system",
        server_default=text("'system'"),
        comment="创建人用户名，系统操作时填写system",
    )

    created_at: Mapped[datetime] = mapped_column(
        mysql.DATETIME(fsp=3),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(3)"),
        comment="创建时间",
    )

    updated_by: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="system",
        server_default=text("'system'"),
        comment="最后更新人用户名，系统操作时填写system",
    )

    updated_at: Mapped[datetime] = mapped_column(
        mysql.DATETIME(fsp=3),
        nullable=False,
        server_default=text(
            "CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)"
        ),
        comment="最后更新时间",
    )


class SoftDeleteMixin:
    """通用软删除字段。"""

    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("0"),
        comment="删除标识：0未删除，1已删除",
    )