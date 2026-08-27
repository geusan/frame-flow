"""Add normalized artifact lineage edges.

Revision ID: 0004
Revises: 0003
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    tables = sa.inspect(connection).get_table_names()
    if "artifact_edges" not in tables:
        op.create_table(
            "artifact_edges",
            sa.Column("parent_artifact_id", sa.String(64), sa.ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("child_artifact_id", sa.String(64), sa.ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("role", sa.String(64), nullable=False),
            sa.Column("ordinal", sa.Integer(), nullable=False),
            sa.Column("operation_id", sa.String(64), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "parent_artifact_id",
                "child_artifact_id",
                "role",
                "ordinal",
                name="uq_artifact_edges_relation",
            ),
        )
        op.create_index("ix_artifact_edges_parent_artifact_id", "artifact_edges", ["parent_artifact_id"])
        op.create_index("ix_artifact_edges_child_artifact_id", "artifact_edges", ["child_artifact_id"])
        op.create_index("ix_artifact_edges_operation_id", "artifact_edges", ["operation_id"])

    artifacts = sa.table(
        "artifacts",
        sa.column("id", sa.String()),
        sa.column("input_artifact_ids", sa.JSON()),
        sa.column("producer_node_run_id", sa.String()),
        sa.column("metadata_json", sa.JSON()),
    )
    edges = sa.table(
        "artifact_edges",
        sa.column("id", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("parent_artifact_id", sa.String()),
        sa.column("child_artifact_id", sa.String()),
        sa.column("role", sa.String()),
        sa.column("ordinal", sa.Integer()),
        sa.column("operation_id", sa.String()),
        sa.column("metadata_json", sa.JSON()),
    )
    rows = connection.execute(sa.select(artifacts)).mappings().all()
    known_ids = {str(row["id"]) for row in rows}
    existing = {
        (str(row.parent_artifact_id), str(row.child_artifact_id), str(row.role), int(row.ordinal))
        for row in connection.execute(sa.select(
            edges.c.parent_artifact_id,
            edges.c.child_artifact_id,
            edges.c.role,
            edges.c.ordinal,
        ))
    }
    inserts: list[dict[str, object]] = []
    for row in rows:
        raw_inputs = row["input_artifact_ids"] or []
        input_ids = json.loads(raw_inputs) if isinstance(raw_inputs, str) else raw_inputs
        raw_metadata = row["metadata_json"] or {}
        metadata = json.loads(raw_metadata) if isinstance(raw_metadata, str) else raw_metadata
        roles = metadata.get("input_artifact_roles") or {}
        operation_id = (
            row["producer_node_run_id"]
            or metadata.get("experiment_id")
            or (metadata.get("capture") or {}).get("operation")
            or metadata.get("operation")
        )
        for ordinal, parent_id in enumerate(dict.fromkeys(input_ids)):
            parent_id = str(parent_id)
            role = str(roles.get(parent_id) or "input")[:64]
            relation = (parent_id, str(row["id"]), role, ordinal)
            if parent_id not in known_ids or relation in existing:
                continue
            inserts.append({
                "id": f"edge_{uuid.uuid4().hex[:18]}",
                "created_at": datetime.now(timezone.utc),
                "parent_artifact_id": parent_id,
                "child_artifact_id": str(row["id"]),
                "role": role,
                "ordinal": ordinal,
                "operation_id": str(operation_id)[:64] if operation_id else None,
                "metadata_json": {"backfilled_by": "migration.0004"},
            })
            existing.add(relation)
    if inserts:
        connection.execute(sa.insert(edges), inserts)


def downgrade() -> None:
    if "artifact_edges" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("artifact_edges")
