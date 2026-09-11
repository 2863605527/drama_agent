"""initial schema: users + tasks

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        mysql_charset="utf8mb4",
    )
    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("user_prompt", sa.Text(), nullable=False),
        sa.Column("style", sa.String(32), server_default="anime"),
        sa.Column("audio_mode", sa.String(16), server_default="auto"),
        sa.Column("status", sa.String(32), server_default="pending"),
        sa.Column("script_data", sa.JSON(), nullable=True),
        sa.Column("final_video_url", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        mysql_charset="utf8mb4",
    )


def downgrade() -> None:
    op.drop_table("tasks")
    op.drop_table("users")
