from __future__ import annotations

import os
from datetime import datetime
from decimal import Decimal
from typing import Any, Iterator

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from .domain import utc_now


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./video_canvas.db")
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
_local_sessions = sessionmaker(bind=engine, expire_on_commit=False)


def SessionLocal():
    """Explicit runtime adapter; singleton application objects hold no user state."""
    from .access import require_live_scope
    scope = require_live_scope()
    return scope.adapters.sessions(scope.context) if scope else _local_sessions()


from .database_models import build_models
from .database_namespace import freeze_prefix

globals().update(build_models(freeze_prefix()))


def create_all() -> None:
    with engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            # API and Temporal worker start together in Compose. Serialize schema
            # inspection/DDL so both processes cannot create the same table.
            connection.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": 2026082701})
        Base.metadata.create_all(bind=connection)
        if not connection.execute(WorkspaceRecord.__table__.select().where(WorkspaceRecord.id == "legacy-default")).first():
            connection.execute(WorkspaceRecord.__table__.insert().values(id="legacy-default", name="Local workspace", status="active", created_at=utc_now()))


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
