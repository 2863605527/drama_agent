"""episode/logs columns on tasks + assets metadata table

补齐多集续写（parent_id/episode_no/series_title/logs）与个人资产元数据表（assets）。
此前这些结构只靠 db.database.init_db 的 create_all + 幂等 ALTER 建，全新库 alembic
upgrade 到 0002 会缺列缺表；本迁移让「全新库 alembic upgrade head」与老库 init_db
增量补齐得到完全一致的 schema。

Revision ID: 0003_episode_logs_assets
Revises: 0002_channel_config
Create Date: 2026-09-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_episode_logs_assets"
down_revision: Union[str, None] = "0002_channel_config"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- tasks 多集续写与日志持久化列（与 db/models.py Task 对齐）----
    op.add_column("tasks", sa.Column("parent_id", sa.String(64), nullable=True))
    op.add_column("tasks", sa.Column("episode_no", sa.Integer(), nullable=True,
                                     server_default="1"))
    op.add_column("tasks", sa.Column("series_title", sa.String(255), nullable=True))
    op.add_column("tasks", sa.Column("logs", sa.JSON(), nullable=True))
    op.create_index("ix_tasks_parent_id", "tasks", ["parent_id"])

    # ---- 个人资产元数据表（与 db/models.py Asset 对齐）----
    op.create_table(
        "assets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("url", sa.String(512), nullable=False, unique=True, index=True),
        sa.Column("rel_path", sa.String(512), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"),
                  nullable=True, index=True),
        sa.Column("asset_type", sa.String(32), nullable=True, server_default="unknown",
                  index=True),
        sa.Column("source", sa.String(16), nullable=True, server_default="ai", index=True),
        sa.Column("task_id", sa.String(64), nullable=True, index=True),
        sa.Column("mime", sa.String(64), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True, server_default="0"),
        sa.Column("sha256", sa.String(64), nullable=True, index=True),
        sa.Column("ref_count", sa.Integer(), nullable=True, server_default="0", index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        mysql_charset="utf8mb4",
    )


def downgrade() -> None:
    op.drop_table("assets")
    op.drop_index("ix_tasks_parent_id", table_name="tasks")
    op.drop_column("tasks", "logs")
    op.drop_column("tasks", "series_title")
    op.drop_column("tasks", "episode_no")
    op.drop_column("tasks", "parent_id")
