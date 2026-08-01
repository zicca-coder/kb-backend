"""Allow pending user-agent bindings without an external agent ID.

Revision ID: 20260730_01
Revises: 20260730_00
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260730_01"
down_revision: str | Sequence[str] | None = "20260730_00"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "user_agents",
        "agent_id",
        existing_type=sa.String(length=128),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "user_agents",
        "agent_id",
        existing_type=sa.String(length=128),
        nullable=False,
    )
