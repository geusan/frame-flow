"""Add provider receipts; historical Run/Artifact snapshots remain untouched."""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    columns = {c["name"] for c in inspector.get_columns("experiment_runs")}
    indexes = {i["name"] for i in inspector.get_indexes("experiment_runs")}
    tables = set(inspector.get_table_names())
    with op.batch_alter_table("experiment_runs") as batch:
        for name in ("billing_run_id", "billing_node_run_id"):
            if name not in columns:
                batch.add_column(sa.Column(name, sa.String(64), nullable=True))
            if f"ix_experiment_runs_{name}" not in indexes:
                batch.create_index(f"ix_experiment_runs_{name}", [name])
        if "cost_summary" not in columns:
            batch.add_column(sa.Column("cost_summary", sa.JSON(), nullable=False, server_default="{}"))
    if "provider_costs" not in tables:
        op.create_table(
            "provider_costs",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("experiment_id", sa.String(64), nullable=True),
            sa.Column("run_id", sa.String(64), nullable=True),
            sa.Column("node_run_id", sa.String(64), nullable=True),
            sa.Column("provider", sa.String(32), nullable=False),
            sa.Column("operation", sa.String(128), nullable=False),
            sa.Column("requested_model", sa.String(255), nullable=False),
            sa.Column("model", sa.String(255), nullable=False),
            sa.Column("provider_request_id", sa.String(512), nullable=True),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("outcome", sa.String(32), nullable=False),
            sa.Column("amount_usd", sa.Numeric(24, 12), nullable=True),
            sa.Column("usage", sa.JSON(), nullable=False),
            sa.Column("pricing", sa.JSON(), nullable=False),
            sa.Column("reason", sa.String(255), nullable=True),
            sa.UniqueConstraint("provider", "provider_request_id", name="uq_provider_cost_request"),
        )
        for column in ("experiment_id", "run_id", "node_run_id", "provider", "status"):
            op.create_index(f"ix_provider_costs_{column}", "provider_costs", [column])
    if "provider_cost_observations" not in tables:
        op.create_table(
            "provider_cost_observations",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("cost_id", sa.String(64), sa.ForeignKey("provider_costs.id"), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
        )
        op.create_index("ix_provider_cost_observations_cost_id", "provider_cost_observations", ["cost_id"])



def downgrade():
    op.drop_table("provider_cost_observations")
    op.drop_table("provider_costs")
    with op.batch_alter_table("experiment_runs") as batch:
        batch.drop_index("ix_experiment_runs_billing_node_run_id")
        batch.drop_index("ix_experiment_runs_billing_run_id")
        batch.drop_column("cost_summary")
        batch.drop_column("billing_node_run_id")
        batch.drop_column("billing_run_id")
