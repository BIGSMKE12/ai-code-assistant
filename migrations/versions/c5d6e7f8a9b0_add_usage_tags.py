"""add cost center and project tag to usage records

Revision ID: c5d6e7f8a9b0
Revises: b7c8d9e0f1a2
Create Date: 2026-10-20 00:00:00.000000

Phase 10: owner-assigned chargeback labels (#484). Both columns are nullable so
historical rows remain valid and aggregate under "untagged". The reversible
downgrade removes the indexes and columns.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c5d6e7f8a9b0"
down_revision = "a4b5c6d7e8f9"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("usage_records", schema=None) as batch_op:
        batch_op.add_column(sa.Column("cost_center", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("project_tag", sa.String(length=64), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_usage_records_cost_center"), ["cost_center"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_usage_records_project_tag"), ["project_tag"], unique=False
        )


def downgrade():
    with op.batch_alter_table("usage_records", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_usage_records_project_tag"))
        batch_op.drop_index(batch_op.f("ix_usage_records_cost_center"))
        batch_op.drop_column("project_tag")
        batch_op.drop_column("cost_center")
