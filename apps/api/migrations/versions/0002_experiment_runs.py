"""Add persistent single-run experiment history.

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "experiment_runs" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "experiment_runs",
        sa.Column("canvas_id", sa.String(128), nullable=False),
        sa.Column("node_id", sa.String(128), nullable=False),
        sa.Column("node_key", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("execution_mode", sa.String(32), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("model_alias", sa.String(128), nullable=False),
        sa.Column("exact_model_id", sa.String(255), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("provider_request_id", sa.String(255), nullable=True),
        sa.Column("output_artifact_ids", sa.JSON(), nullable=False),
        sa.Column("output_payload", sa.JSON(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.Column("cache_hit", sa.Boolean(), nullable=False),
        sa.Column("cached_from_id", sa.String(64), nullable=True),
        sa.Column("is_baseline", sa.Boolean(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("canvas_id", "node_id", "node_key", "status", "request_hash", "is_baseline"):
        op.create_index(f"ix_experiment_runs_{column}", "experiment_runs", [column])


def downgrade() -> None:
    if "experiment_runs" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("experiment_runs")
