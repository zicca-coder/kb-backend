"""Add chat attachments.

Revision ID: 20260801_02
Revises: 20260801_01
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260801_02"
down_revision: str | Sequence[str] | None = "20260801_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _has_index(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(
        index["name"] == index_name
        for index in inspector.get_indexes(table_name)
    )


def upgrade() -> None:
    if not _has_table("attachments"):
        op.create_table(
            "attachments",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.BigInteger(), nullable=False),
            sa.Column("conversation_id", sa.String(length=36), nullable=True),
            sa.Column("original_filename", sa.String(length=255), nullable=False),
            sa.Column("bucket_name", sa.String(length=128), nullable=False),
            sa.Column("object_key", sa.String(length=512), nullable=False),
            sa.Column("content_type", sa.String(length=128), nullable=False),
            sa.Column("detected_mime_type", sa.String(length=128), nullable=False),
            sa.Column("extension", sa.String(length=16), nullable=False),
            sa.Column("file_size", sa.BigInteger(), nullable=False),
            sa.Column("sha256", sa.String(length=64), nullable=False),
            sa.Column("category", sa.String(length=32), nullable=False),
            sa.Column(
                "purpose",
                sa.String(length=64),
                nullable=False,
                server_default="chat_attachment",
            ),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="uploading",
            ),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column(
                "created_by",
                sa.String(length=64),
                nullable=False,
                server_default=sa.text("'system'"),
            ),
            sa.Column(
                "created_at",
                mysql.DATETIME(fsp=3),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP(3)"),
            ),
            sa.Column(
                "updated_by",
                sa.String(length=64),
                nullable=False,
                server_default=sa.text("'system'"),
            ),
            sa.Column(
                "updated_at",
                mysql.DATETIME(fsp=3),
                nullable=False,
                server_default=sa.text(
                    "CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)"
                ),
            ),
            sa.Column(
                "is_deleted",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["users.id"],
                name="fk_attachments_user",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["conversation_id"],
                ["conversations.id"],
                name="fk_attachments_conversation",
                ondelete="SET NULL",
                onupdate="RESTRICT",
            ),
            sa.PrimaryKeyConstraint("id", name="pk_attachments"),
            sa.UniqueConstraint("object_key", name="uq_attachments_object_key"),
            mysql_engine="InnoDB",
            mysql_charset="utf8mb4",
            mysql_collate="utf8mb4_0900_ai_ci",
            comment="聊天附件元数据表",
        )
    if not _has_index("attachments", "ix_attachments_user_status_deleted"):
        op.create_index(
            "ix_attachments_user_status_deleted",
            "attachments",
            ["user_id", "status", "is_deleted"],
        )
    if not _has_index("attachments", "ix_attachments_conversation"):
        op.create_index(
            "ix_attachments_conversation",
            "attachments",
            ["conversation_id"],
        )
    if not _has_index("attachments", "ix_attachments_sha256"):
        op.create_index("ix_attachments_sha256", "attachments", ["sha256"])

    if not _has_table("message_attachments"):
        op.create_table(
            "message_attachments",
            sa.Column(
                "id",
                mysql.BIGINT(unsigned=True),
                autoincrement=True,
                nullable=False,
            ),
            sa.Column(
                "message_id",
                mysql.BIGINT(unsigned=True),
                nullable=False,
            ),
            sa.Column("attachment_id", sa.String(length=36), nullable=False),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.Column(
                "created_at",
                mysql.DATETIME(fsp=3),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP(3)"),
            ),
            sa.ForeignKeyConstraint(
                ["message_id"],
                ["conversation_messages.id"],
                name="fk_message_attachments_message",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["attachment_id"],
                ["attachments.id"],
                name="fk_message_attachments_attachment",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.PrimaryKeyConstraint("id", name="pk_message_attachments"),
            sa.UniqueConstraint(
                "message_id",
                "attachment_id",
                name="uk_message_attachments_message_attachment",
            ),
            sa.UniqueConstraint(
                "message_id",
                "sort_order",
                name="uk_message_attachments_message_sort",
            ),
            mysql_engine="InnoDB",
            mysql_charset="utf8mb4",
            mysql_collate="utf8mb4_0900_ai_ci",
            comment="聊天消息附件关联表",
        )
    if not _has_index(
        "message_attachments",
        "ix_message_attachments_attachment",
    ):
        op.create_index(
            "ix_message_attachments_attachment",
            "message_attachments",
            ["attachment_id"],
        )


def downgrade() -> None:
    if _has_table("message_attachments"):
        op.drop_table("message_attachments")
    if _has_table("attachments"):
        op.drop_table("attachments")
