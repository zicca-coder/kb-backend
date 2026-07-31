"""Add provisioning status and pending default for user agents.

Revision ID: 20260731_02
Revises: 20260731_01
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision: str = "20260731_02"
down_revision: str | Sequence[str] | None = "20260731_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    if not _has_table("user_agents"):
        return

    bind = op.get_bind()
    bind.execute(
        text(
            "UPDATE user_agents "
            "SET provision_status = 'pending' "
            "WHERE provision_status = 'creating'"
        )
    )
    op.alter_column(
        "user_agents",
        "provision_status",
        existing_type=sa.String(length=32),
        existing_nullable=False,
        server_default="pending",
    )


def downgrade() -> None:
    if not _has_table("user_agents"):
        return

    op.alter_column(
        "user_agents",
        "provision_status",
        existing_type=sa.String(length=32),
        existing_nullable=False,
        server_default="creating",
    )
