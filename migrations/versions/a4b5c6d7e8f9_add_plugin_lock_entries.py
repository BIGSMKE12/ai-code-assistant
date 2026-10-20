"""add plugin lock entries

Revision ID: a4b5c6d7e8f9
Revises: b7c8d9e0f1a2
Create Date: 2026-10-20 00:00:00.000000

Phase 9: persist the resolved plugin lockfile (issue #395). Each row pins one
plugin for a workspace and is scoped to both the workspace and its owner. The
table is intentionally reversible; ``downgrade`` removes the indexes and table
created here.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a4b5c6d7e8f9"
down_revision = "c7d8e9f0a1b2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "plugin_lock_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("plugin_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=512), nullable=False),
        sa.Column("integrity", sa.String(length=128), nullable=False),
        sa.Column("dependencies", sa.JSON(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "plugin_id", name="uq_plugin_lock_entry"),
    )
    with op.batch_alter_table("plugin_lock_entries", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_plugin_lock_entries_owner_id"), ["owner_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_plugin_lock_entries_plugin_id"), ["plugin_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_plugin_lock_entries_workspace_id"),
            ["workspace_id"],
            unique=False,
        )


def downgrade():
    with op.batch_alter_table("plugin_lock_entries", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_plugin_lock_entries_workspace_id"))
        batch_op.drop_index(batch_op.f("ix_plugin_lock_entries_plugin_id"))
        batch_op.drop_index(batch_op.f("ix_plugin_lock_entries_owner_id"))

    op.drop_table("plugin_lock_entries")
