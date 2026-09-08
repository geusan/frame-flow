"""Add persistent Canvas node execution logs.

Revision ID: 0011
Revises: 0010
"""
from alembic import op
import sqlalchemy as sa


revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("canvas_node_runs")}
    if "logs" not in columns:
        with op.batch_alter_table("canvas_node_runs") as batch:
            batch.add_column(sa.Column("logs", sa.JSON(), nullable=False, server_default="[]"))


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("canvas_node_runs")}
    if "logs" in columns:
        with op.batch_alter_table("canvas_node_runs") as batch:
            batch.drop_column("logs")
