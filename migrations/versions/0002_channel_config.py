"""user channel configs + tasks.channel_config snapshot

Revision ID: 0002_channel_config
Revises: 0001_initial
Create Date: 2026-09-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_channel_config"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 用户运行时模型通道配置（密钥加密后存放）
    op.create_table(
        "user_channel_configs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"),
                  nullable=False, unique=True, index=True),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        mysql_charset="utf8mb4",
    )
    # 任务提交时的通道配置快照，保证在跑任务不受事后改配置影响
    op.add_column("tasks", sa.Column("channel_config", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "channel_config")
    op.drop_table("user_channel_configs")
