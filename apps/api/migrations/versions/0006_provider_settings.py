"""Persist provider integration settings.

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "provider_settings" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "provider_settings",
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("secrets", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider", name="uq_provider_settings_provider"),
    )
    op.create_index("ix_provider_settings_provider", "provider_settings", ["provider"], unique=True)


def downgrade() -> None:
    if "provider_settings" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("provider_settings")
