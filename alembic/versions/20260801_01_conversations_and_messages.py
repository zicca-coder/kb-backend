"""Add conversations and persisted chat messages.

Revision ID: 20260801_01
Revises: 20260731_02
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260801_01"
down_revision: str | Sequence[str] | None = "20260731_02"
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
    if not _has_table("conversations"):
        _create_conversations()
    if not _has_index(
        "conversations",
        "ix_conversations_user_deleted_last_message",
    ):
        op.create_index(
            "ix_conversations_user_deleted_last_message",
            "conversations",
            ["user_id", "is_deleted", "last_message_at"],
            unique=False,
        )

    if not _has_table("conversation_messages"):
        _create_conversation_messages()
    if not _has_index(
        "conversation_messages",
        "ix_conversation_messages_conversation_sequence",
    ):
        op.create_index(
            "ix_conversation_messages_conversation_sequence",
            "conversation_messages",
            ["conversation_id", "sequence_no"],
            unique=False,
        )
    if not _has_index(
        "conversation_messages",
        "ix_conversation_messages_request_id",
    ):
        op.create_index(
            "ix_conversation_messages_request_id",
            "conversation_messages",
            ["request_id"],
            unique=False,
        )


def _create_conversations() -> None:
    op.create_table(
        "conversations",
        sa.Column(
            "id",
            sa.String(length=36),
            nullable=False,
            comment="Conversation UUID",
        ),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            nullable=False,
            comment="Owner user ID",
        ),
        sa.Column(
            "title",
            sa.String(length=100),
            nullable=False,
            server_default="新对话",
            comment="Conversation title",
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="active",
            comment="Conversation status",
        ),
        sa.Column(
            "last_message_at",
            mysql.DATETIME(fsp=3),
            nullable=True,
            comment="Last message time for ordering",
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
            name="fk_conversations_user",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_conversations"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        comment="用户聊天会话表",
    )


def _create_conversation_messages() -> None:
    op.create_table(
        "conversation_messages",
        sa.Column(
            "id",
            mysql.BIGINT(unsigned=True),
            autoincrement=True,
            nullable=False,
            comment="主键",
        ),
        sa.Column(
            "conversation_id",
            sa.String(length=36),
            nullable=False,
            comment="Conversation UUID",
        ),
        sa.Column(
            "role",
            sa.String(length=32),
            nullable=False,
            comment="Message role",
        ),
        sa.Column(
            "content",
            sa.Text(),
            nullable=False,
            comment="Message content",
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
            comment="Message status",
        ),
        sa.Column(
            "request_id",
            sa.String(length=36),
            nullable=True,
            comment="Streaming request UUID",
        ),
        sa.Column(
            "sequence_no",
            sa.Integer(),
            nullable=False,
            comment="Message sequence number within conversation",
        ),
        sa.Column(
            "error_message",
            sa.String(length=1000),
            nullable=True,
            comment="Internal safe error summary",
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
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="fk_conversation_messages_conversation",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_conversation_messages"),
        sa.UniqueConstraint(
            "conversation_id",
            "sequence_no",
            name="uk_conversation_messages_conversation_sequence",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        comment="用户聊天消息表",
    )


def downgrade() -> None:
    if _has_table("conversation_messages"):
        op.drop_table("conversation_messages")
    if _has_table("conversations"):
        op.drop_table("conversations")
