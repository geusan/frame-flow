"""Add persisted editable Canvas documents.

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "canvases" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "canvases",
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("graph_json", sa.JSON(), nullable=False),
        sa.Column("active_run_id", sa.String(64), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_canvases_updated_at", "canvases", ["updated_at"])


def downgrade() -> None:
    if "canvases" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("canvases")
