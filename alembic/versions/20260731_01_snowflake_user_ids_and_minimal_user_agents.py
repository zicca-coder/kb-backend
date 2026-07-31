"""Use Snowflake user IDs and remove OpenClaw internal paths.

Revision ID: 20260731_01
Revises: 20260730_01
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision: str = "20260731_01"
down_revision: str | Sequence[str] | None = "20260730_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INT_MAX = 2_147_483_647


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(
        column["name"] == column_name
        for column in inspector.get_columns(table_name)
    )


def _drop_user_agent_fk() -> None:
    if not _has_table("user_agents"):
        return
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for foreign_key in inspector.get_foreign_keys("user_agents"):
        if (
            foreign_key.get("referred_table") == "users"
            and foreign_key.get("constrained_columns") == ["user_id"]
            and foreign_key.get("name")
        ):
            op.drop_constraint(
                foreign_key["name"],
                "user_agents",
                type_="foreignkey",
            )


def _create_user_agent_fk() -> None:
    if not _has_table("user_agents"):
        return
    op.create_foreign_key(
        "fk_user_agents_user",
        "user_agents",
        "users",
        ["user_id"],
        ["id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )


def upgrade() -> None:
    if not _has_table("users"):
        return

    _drop_user_agent_fk()

    op.alter_column(
        "users",
        "id",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=False,
        autoincrement=False,
    )

    if _has_table("user_agents"):
        op.alter_column(
            "user_agents",
            "user_id",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            existing_nullable=False,
        )
        for column_name in (
            "workspace_path",
            "agent_dir",
            "knowledge_path",
        ):
            if _has_column("user_agents", column_name):
                op.drop_column("user_agents", column_name)

    _create_user_agent_fk()


def downgrade() -> None:
    if not _has_table("users"):
        return

    bind = op.get_bind()
    users_overflow = bind.execute(
        text("SELECT COUNT(*) FROM users WHERE id > :int_max"),
        {"int_max": INT_MAX},
    ).scalar_one()
    user_agents_overflow = 0
    if _has_table("user_agents"):
        user_agents_overflow = bind.execute(
            text("SELECT COUNT(*) FROM user_agents WHERE user_id > :int_max"),
            {"int_max": INT_MAX},
        ).scalar_one()
    if users_overflow or user_agents_overflow:
        raise RuntimeError(
            "Cannot downgrade Snowflake BIGINT user IDs to INTEGER safely"
        )

    _drop_user_agent_fk()

    if _has_table("user_agents"):
        for column_name in (
            "workspace_path",
            "agent_dir",
            "knowledge_path",
        ):
            if not _has_column("user_agents", column_name):
                op.add_column(
                    "user_agents",
                    sa.Column(
                        column_name,
                        sa.String(length=500),
                        nullable=False,
                        server_default="",
                    ),
                )
                op.alter_column(
                    "user_agents",
                    column_name,
                    server_default=None,
                    existing_type=sa.String(length=500),
                )
        op.alter_column(
            "user_agents",
            "user_id",
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            existing_nullable=False,
        )

    op.alter_column(
        "users",
        "id",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=False,
        autoincrement=True,
    )

    _create_user_agent_fk()
