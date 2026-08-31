"""Add immutable project Skill definitions and versions.

Revision ID: 0009
Revises: 0008
"""
from alembic import op
import sqlalchemy as sa


revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "skill_definitions" not in tables:
        op.create_table(
            "skill_definitions",
            sa.Column("skill_key", sa.String(64), nullable=False),
            sa.Column("display_name", sa.String(160), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("lifecycle", sa.String(32), nullable=False),
            sa.Column("current_version_id", sa.String(64), nullable=True),
            sa.Column("source", sa.String(32), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("skill_key", name="uq_skill_definitions_skill_key"),
        )
        for column in ("skill_key", "lifecycle", "current_version_id", "updated_at"):
            op.create_index(f"ix_skill_definitions_{column}", "skill_definitions", [column])

    if "skill_versions" not in tables:
        op.create_table(
            "skill_versions",
            sa.Column("skill_definition_id", sa.String(64), sa.ForeignKey("skill_definitions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("version_number", sa.Integer(), nullable=False),
            sa.Column("schema_version", sa.String(64), nullable=False),
            sa.Column("content_digest", sa.String(64), nullable=False),
            sa.Column("manifest_json", sa.JSON(), nullable=False),
            sa.Column("instruction_body", sa.Text(), nullable=False),
            sa.Column("source_archive_uri", sa.Text(), nullable=True),
            sa.Column("created_by", sa.String(128), nullable=False),
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("skill_definition_id", "version_number", name="uq_skill_version_number"),
            sa.UniqueConstraint("skill_definition_id", "content_digest", name="uq_skill_version_digest"),
        )
        op.create_index("ix_skill_versions_skill_definition_id", "skill_versions", ["skill_definition_id"])
        op.create_index("ix_skill_versions_content_digest", "skill_versions", ["content_digest"])

    if "skill_installations" not in tables:
        op.create_table(
            "skill_installations",
            sa.Column("skill_definition_id", sa.String(64), sa.ForeignKey("skill_definitions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("permission_policy_json", sa.JSON(), nullable=False),
            sa.Column("default_config_json", sa.JSON(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("skill_definition_id", name="uq_skill_installations_definition"),
        )
        op.create_index("ix_skill_installations_skill_definition_id", "skill_installations", ["skill_definition_id"])
        op.create_index("ix_skill_installations_enabled", "skill_installations", ["enabled"])


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table in ("skill_installations", "skill_versions", "skill_definitions"):
        if table in tables:
            op.drop_table(table)

