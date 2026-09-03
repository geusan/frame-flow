"""Add the registered caption font catalog.

Revision ID: 0010
Revises: 0009
"""
from alembic import op
import sqlalchemy as sa


revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "fonts" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "fonts",
        sa.Column("artifact_id", sa.String(64), sa.ForeignKey("artifacts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("profile_version", sa.Integer(), nullable=False),
        sa.Column("supersedes_id", sa.String(64), sa.ForeignKey("fonts.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("display_name", sa.String(160), nullable=False),
        sa.Column("family_name", sa.String(160), nullable=False),
        sa.Column("subfamily_name", sa.String(96), nullable=False),
        sa.Column("postscript_name", sa.String(160), nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.Column("style", sa.String(32), nullable=False),
        sa.Column("size_adjust", sa.Float(), nullable=False),
        sa.Column("baseline_shift", sa.Float(), nullable=False),
        sa.Column("lifecycle", sa.String(32), nullable=False),
        sa.Column("license_name", sa.String(160), nullable=False),
        sa.Column("metrics_json", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("artifact_id", "profile_version", name="uq_font_artifact_profile_version"),
    )
    for column in ("artifact_id", "supersedes_id", "display_name", "family_name", "lifecycle", "updated_at"):
        op.create_index(f"ix_fonts_{column}", "fonts", [column])


def downgrade() -> None:
    if "fonts" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("fonts")
