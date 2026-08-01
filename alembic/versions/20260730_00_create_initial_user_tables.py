"""Create initial user and user-agent tables.

Revision ID: 20260730_00
Revises:
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260730_00"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
            autoincrement=True,
            nullable=False,
            comment="User ID",
        ),
        sa.Column(
            "username",
            sa.String(length=64),
            nullable=False,
            comment="用户名，可用于登录",
        ),
        sa.Column(
            "phone",
            sa.String(length=32),
            nullable=True,
            comment="手机号，可用于Web端登录",
        ),
        sa.Column(
            "display_name",
            sa.String(length=128),
            nullable=False,
            comment="用户展示名称",
        ),
        sa.Column(
            "email",
            sa.String(length=255),
            nullable=True,
            comment="用户邮箱",
        ),
        sa.Column(
            "password_hash",
            sa.String(length=255),
            nullable=False,
            comment="Web端登录密码哈希，禁止存储明文密码",
        ),
        sa.Column(
            "created_by",
            sa.String(length=64),
            nullable=False,
            server_default=sa.text("'system'"),
            comment="创建人用户名，系统操作时填写system",
        ),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
            comment="创建时间",
        ),
        sa.Column(
            "updated_by",
            sa.String(length=64),
            nullable=False,
            server_default=sa.text("'system'"),
            comment="最后更新人用户名，系统操作时填写system",
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text(
                "CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)"
            ),
            comment="最后更新时间",
        ),
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
            comment="删除标识：0未删除，1已删除",
        ),
        sa.UniqueConstraint("username", name="uk_users_username"),
        sa.UniqueConstraint("phone", name="uk_users_phone"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        comment="用户表",
    )

    op.create_table(
        "user_agents",
        sa.Column(
            "id",
            mysql.BIGINT(unsigned=True),
            primary_key=True,
            autoincrement=True,
            nullable=False,
            comment="主键",
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            nullable=False,
            comment="Platform user ID",
        ),
        sa.Column(
            "agent_id",
            sa.String(length=128),
            nullable=False,
            comment="OpenClaw Agent ID",
        ),
        sa.Column(
            "workspace_path",
            sa.String(length=500),
            nullable=False,
            comment="OpenClaw workspace path",
        ),
        sa.Column(
            "agent_dir",
            sa.String(length=500),
            nullable=False,
            comment="OpenClaw agent directory",
        ),
        sa.Column(
            "knowledge_path",
            sa.String(length=500),
            nullable=False,
            comment="OpenClaw knowledge path",
        ),
        sa.Column(
            "runtime_type",
            sa.String(length=32),
            nullable=False,
            server_default="shared",
            comment="Runtime mode",
        ),
        sa.Column(
            "runtime_id",
            sa.String(length=255),
            nullable=True,
            comment="Runtime identifier",
        ),
        sa.Column(
            "provision_status",
            sa.String(length=32),
            nullable=False,
            server_default="creating",
            comment="Agent provisioning status",
        ),
        sa.Column(
            "provision_error",
            sa.String(length=1000),
            nullable=True,
            comment="Agent provisioning failure reason",
        ),
        sa.Column(
            "created_by",
            sa.String(length=64),
            nullable=False,
            server_default=sa.text("'system'"),
            comment="创建人用户名，系统操作时填写system",
        ),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
            comment="创建时间",
        ),
        sa.Column(
            "updated_by",
            sa.String(length=64),
            nullable=False,
            server_default=sa.text("'system'"),
            comment="最后更新人用户名，系统操作时填写system",
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text(
                "CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)"
            ),
            comment="最后更新时间",
        ),
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
            comment="删除标识：0未删除，1已删除",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_agents_user",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.UniqueConstraint("user_id", name="uk_user_agents_user_id"),
        sa.UniqueConstraint("agent_id", name="uk_user_agents_agent_id"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        comment="Platform user to OpenClaw Agent binding",
    )


def downgrade() -> None:
    op.drop_table("user_agents")
    op.drop_table("users")
