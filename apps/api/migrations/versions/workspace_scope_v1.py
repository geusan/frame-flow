"""Add ownership metadata without changing immutable graphs or run snapshots."""
from alembic import op
import sqlalchemy as sa

revision = "ws_scope_v1"
down_revision = "0012"
branch_labels = None
depends_on = None

OWNED_TABLES = (
    "reference_assets", "reference_sets", "definitions", "formats", "generation_briefs",
    "runs", "node_runs", "artifacts", "artifact_edges", "experiment_runs", "provider_costs",
    "provider_cost_observations", "canvases", "workflow_definitions", "workflow_versions",
    "workflow_annotations", "canvas_runs", "canvas_node_runs", "fonts", "skill_definitions",
    "skill_versions", "skill_installations", "audit_events",
)


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "workspaces" not in inspector.get_table_names():
        op.create_table("workspaces", sa.Column("id", sa.String(64), primary_key=True),
                        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
                        sa.Column("name", sa.String(255), nullable=False), sa.Column("status", sa.String(32), nullable=False))
    workspaces = sa.table("workspaces", sa.column("id"), sa.column("created_at"), sa.column("name"), sa.column("status"))
    if not bind.execute(sa.select(workspaces.c.id).where(workspaces.c.id == "legacy-default")).first():
        from datetime import datetime, timezone
        bind.execute(workspaces.insert().values(id="legacy-default", created_at=datetime.now(timezone.utc), name="Local workspace", status="active"))
    for name in OWNED_TABLES:
        inspector = sa.inspect(bind)
        if "workspace_id" not in {column["name"] for column in inspector.get_columns(name)}:
            with op.batch_alter_table(name) as batch:
                batch.add_column(sa.Column("workspace_id", sa.String(64), nullable=True))
            table = sa.table(name, sa.column("workspace_id"))
            bind.execute(table.update().values(workspace_id="legacy-default"))
            with op.batch_alter_table(name) as batch:
                batch.alter_column("workspace_id", existing_type=sa.String(64), nullable=False, server_default="legacy-default")
                batch.create_foreign_key(f"fk_{name}_workspace", "workspaces", ["workspace_id"], ["id"])
                batch.create_index(f"ix_{name}_workspace_id", ["workspace_id"])
    for name,column_name,column_type,default in (
        ("runs","access_context_json",sa.JSON(),"{}"), ("canvas_runs","access_context_json",sa.JSON(),"{}"),
        ("experiment_runs","credential_scope",sa.String(64),"local"), ("provider_costs","credential_scope",sa.String(64),"local"),
    ):
        if column_name not in {column["name"] for column in sa.inspect(bind).get_columns(name)}:
            with op.batch_alter_table(name) as batch:
                batch.add_column(sa.Column(column_name,column_type,nullable=False,server_default=default))
    replacements = {
        "reference_assets": (["canonical_url"], "uq_reference_workspace_url"),
        "skill_definitions": (["skill_key"], "uq_skill_workspace_key"),
        "skill_installations": (["skill_definition_id"], "uq_skill_workspace_installation"),
        "provider_costs": (["provider", "provider_request_id"], "uq_provider_cost_request"),
    }
    for table_name, (old_columns, constraint_name) in replacements.items():
        unique = sa.inspect(bind).get_unique_constraints(table_name)
        old = next((row for row in unique if row["column_names"] == old_columns), None)
        if old:
            convention = {"uq": "uq_%(table_name)s_%(column_0_name)s"}
            with op.batch_alter_table(table_name, naming_convention=convention) as batch:
                batch.drop_constraint(old["name"] or f"uq_{table_name}_{old_columns[0]}", type_="unique")
                batch.create_unique_constraint(constraint_name, ["workspace_id", *(["credential_scope"] if table_name=="provider_costs" else []), *old_columns])


def downgrade():
    raise RuntimeError("Workspace ownership downgrade requires a reviewed backup restore; refusing destructive automatic downgrade")
