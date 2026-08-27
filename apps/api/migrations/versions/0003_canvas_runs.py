"""Add persistent Canvas DAG runs.

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = sa.inspect(op.get_bind()).get_table_names()
    if "canvas_runs" not in tables:
        op.create_table(
            "canvas_runs",
            sa.Column("canvas_id", sa.String(128), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("progress", sa.Integer(), nullable=False),
            sa.Column("graph_snapshot", sa.JSON(), nullable=False),
            sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_canvas_runs_canvas_id", "canvas_runs", ["canvas_id"])
        op.create_index("ix_canvas_runs_status", "canvas_runs", ["status"])
    if "canvas_node_runs" not in tables:
        op.create_table(
            "canvas_node_runs",
            sa.Column("run_id", sa.String(64), sa.ForeignKey("canvas_runs.id"), nullable=False),
            sa.Column("canvas_node_id", sa.String(128), nullable=False),
            sa.Column("node_key", sa.String(128), nullable=False),
            sa.Column("ordinal", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("progress", sa.Integer(), nullable=False),
            sa.Column("attempt_count", sa.Integer(), nullable=False),
            sa.Column("provider_request_id", sa.String(255), nullable=True),
            sa.Column("provider_operation_id", sa.String(255), nullable=True),
            sa.Column("request_hash", sa.String(64), nullable=True),
            sa.Column("output_artifact_ids", sa.JSON(), nullable=False),
            sa.Column("output_payload", sa.JSON(), nullable=False),
            sa.Column("duration_ms", sa.Integer(), nullable=False),
            sa.Column("cost_usd", sa.Float(), nullable=False),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        for column in ("run_id", "canvas_node_id", "node_key", "status"):
            op.create_index(f"ix_canvas_node_runs_{column}", "canvas_node_runs", [column])


def downgrade() -> None:
    tables = sa.inspect(op.get_bind()).get_table_names()
    if "canvas_node_runs" in tables:
        op.drop_table("canvas_node_runs")
    if "canvas_runs" in tables:
        op.drop_table("canvas_runs")
