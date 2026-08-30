"""Expand experiment execution mode for composite executor revisions.

Revision ID: 0007
Revises: 0006
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "experiment_runs",
        "execution_mode",
        existing_type=sa.String(32),
        type_=sa.String(64),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "experiment_runs",
        "execution_mode",
        existing_type=sa.String(64),
        type_=sa.String(32),
        existing_nullable=False,
    )
