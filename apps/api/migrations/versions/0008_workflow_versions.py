"""Add versioned Workflow definitions, annotations, and Draft metadata.

Revision ID: 0008
Revises: 0007
"""
from alembic import op
import sqlalchemy as sa


revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def _column_names(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "canvases" in tables:
        columns = _column_names("canvases")
        additions = (
            ("workflow_definition_id", sa.Column("workflow_definition_id", sa.String(64), nullable=True)),
            ("base_version_id", sa.Column("base_version_id", sa.String(64), nullable=True)),
            ("revision", sa.Column("revision", sa.Integer(), nullable=False, server_default="1")),
            ("draft_contract_json", sa.Column("draft_contract_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'"))),
        )
        for name, column in additions:
            if name not in columns:
                op.add_column("canvases", column)
        if "workflow_definition_id" not in columns:
            op.create_index("ix_canvases_workflow_definition_id", "canvases", ["workflow_definition_id"])

    if "workflow_definitions" not in tables:
        op.create_table(
            "workflow_definitions",
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("draft_canvas_id", sa.String(64), nullable=False),
            sa.Column("current_version_id", sa.String(64), nullable=True),
            sa.Column("tags", sa.JSON(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("draft_canvas_id", name="uq_workflow_definitions_draft_canvas_id"),
        )
        for column in ("name", "status", "draft_canvas_id", "current_version_id", "updated_at"):
            op.create_index(f"ix_workflow_definitions_{column}", "workflow_definitions", [column])

    if "workflow_versions" not in tables:
        op.create_table(
            "workflow_versions",
            sa.Column("workflow_definition_id", sa.String(64), sa.ForeignKey("workflow_definitions.id"), nullable=False),
            sa.Column("version_number", sa.Integer(), nullable=False),
            sa.Column("schema_version", sa.String(64), nullable=False),
            sa.Column("graph_json", sa.JSON(), nullable=False),
            sa.Column("input_schema_json", sa.JSON(), nullable=False),
            sa.Column("bindings_json", sa.JSON(), nullable=False),
            sa.Column("output_schema_json", sa.JSON(), nullable=False),
            sa.Column("content_hash", sa.String(64), nullable=False),
            sa.Column("source_canvas_id", sa.String(64), nullable=False),
            sa.Column("source_canvas_revision", sa.Integer(), nullable=False),
            sa.Column("release_notes", sa.Text(), nullable=False),
            sa.Column("published_by", sa.String(128), nullable=False),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("workflow_definition_id", "version_number", name="uq_workflow_version_number"),
            sa.UniqueConstraint("workflow_definition_id", "source_canvas_id", "source_canvas_revision", name="uq_workflow_canvas_revision"),
        )
        for column in ("workflow_definition_id", "content_hash", "source_canvas_id", "published_at"):
            op.create_index(f"ix_workflow_versions_{column}", "workflow_versions", [column])

    if "workflow_annotations" not in tables:
        op.create_table(
            "workflow_annotations",
            sa.Column("workflow_definition_id", sa.String(64), sa.ForeignKey("workflow_definitions.id"), nullable=False),
            sa.Column("workflow_version_id", sa.String(64), sa.ForeignKey("workflow_versions.id"), nullable=True),
            sa.Column("node_id", sa.String(128), nullable=True),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("position_json", sa.JSON(), nullable=False),
            sa.Column("color", sa.String(32), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("created_by", sa.String(128), nullable=False),
            sa.Column("updated_by", sa.String(128), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        for column in ("workflow_definition_id", "workflow_version_id", "node_id", "updated_at", "deleted_at"):
            op.create_index(f"ix_workflow_annotations_{column}", "workflow_annotations", [column])

    if "canvas_runs" in tables:
        columns = _column_names("canvas_runs")
        additions = (
            ("source_type", sa.Column("source_type", sa.String(32), nullable=False, server_default="CANVAS_DRAFT")),
            ("workflow_definition_id", sa.Column("workflow_definition_id", sa.String(64), nullable=True)),
            ("workflow_version_id", sa.Column("workflow_version_id", sa.String(64), nullable=True)),
            ("input_snapshot", sa.Column("input_snapshot", sa.JSON(), nullable=False, server_default=sa.text("'{}'"))),
            ("model_snapshot", sa.Column("model_snapshot", sa.JSON(), nullable=False, server_default=sa.text("'{}'"))),
            ("compiler_version", sa.Column("compiler_version", sa.String(64), nullable=True)),
        )
        for name, column in additions:
            if name not in columns:
                op.add_column("canvas_runs", column)
        for column in ("source_type", "workflow_definition_id", "workflow_version_id"):
            if column not in columns:
                op.create_index(f"ix_canvas_runs_{column}", "canvas_runs", [column])


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table in ("workflow_annotations", "workflow_versions", "workflow_definitions"):
        if table in tables:
            op.drop_table(table)
    if "canvas_runs" in tables:
        columns = _column_names("canvas_runs")
        for column in ("compiler_version", "model_snapshot", "input_snapshot", "workflow_version_id", "workflow_definition_id", "source_type"):
            if column in columns:
                op.drop_column("canvas_runs", column)
    if "canvases" in tables:
        columns = _column_names("canvases")
        for column in ("draft_contract_json", "revision", "base_version_id", "workflow_definition_id"):
            if column in columns:
                op.drop_column("canvases", column)
