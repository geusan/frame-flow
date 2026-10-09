"""Explicit deployment-level table naming and unchanged legacy migration scope.

Names are fixed before ORM import, never switched per customer/request. Historical
Alembic scripts run against their original logical names in a private namespace.
"""
from contextlib import contextmanager
import hashlib
import re
from uuid import uuid4

from sqlalchemy import MetaData, Table, inspect, text


def validate_prefix(prefix):
    if prefix and not re.fullmatch(r"[a-z][a-z0-9_]{0,14}_", prefix):
        raise ValueError("Table prefix must be a lowercase identifier ending in _ (maximum 16 characters)")
    return prefix


_prefix = ""
_frozen = False


def configure_table_prefix(prefix):
    global _prefix
    validate_prefix(prefix)
    if _frozen and prefix != _prefix:
        raise RuntimeError("Database namespace is fixed after ORM import; configure before starting the process")
    _prefix = prefix


def freeze_prefix():
    global _frozen
    _frozen = True
    return _prefix


def table_prefix():
    return _prefix


def table_name(logical):
    return _prefix + logical


class NamespaceMetaData(MetaData):
    def __init__(self, prefix, legacy_factory):
        # Logical index names have the same shape in runtime and migration DDL.
        naming = {"ix": prefix + "ix_%(logical_table)s_%(column_0_name)s",
                  "logical_table": lambda constraint, table: table.name[len(prefix):] if prefix else table.name}
        super().__init__(naming_convention=naming)
        self.prefix, self.legacy_factory = prefix, legacy_factory

    def create_all(self, bind, tables=None, checkfirst=True):
        if self.prefix and getattr(bind, "info", {}).get("core_logical_migrations"):
            if tables is not None:
                raise ValueError("Legacy model creation must use the complete canonical model set")
            return self.legacy_factory().create_all(bind, checkfirst=checkfirst)
        return super().create_all(bind, tables=tables, checkfirst=checkfirst)


class NamespaceTable(Table):
    """Public Table factory hook for legacy scripts creating a mapped table."""
    def create(self, bind, checkfirst=False):
        prefix = getattr(self.metadata, "prefix", "")
        if prefix and getattr(bind, "info", {}).get("core_logical_migrations"):
            logical = self.name[len(prefix):]
            return self.metadata.legacy_factory().tables[logical].create(bind, checkfirst=checkfirst)
        return super().create(bind, checkfirst=checkfirst)


def _identifier(connection, name):
    return connection.dialect.identifier_preparer.quote(name)


def _bounded(name):
    return name if len(name) <= 63 else name[:50] + "_" + hashlib.sha256(name.encode()).hexdigest()[:12]


def _postgres_objects(connection, schema, prefix, *, restoring):
    """Namespace owned constraints/indexes too, avoiding shared-schema collisions."""
    quote = lambda value: _identifier(connection, value)
    constraints = connection.execute(text("""
        SELECT t.relname AS table_name,c.conname FROM pg_constraint c
        JOIN pg_class t ON t.oid=c.conrelid JOIN pg_namespace n ON n.oid=t.relnamespace
        WHERE n.nspname=:schema ORDER BY t.relname,c.conname
    """), {"schema":schema}).mappings().all()
    for row in constraints:
        original = row["conname"]
        target = _bounded(prefix + original) if restoring and not original.startswith(prefix) else original
        if not restoring and original.startswith(prefix):
            target = original[len(prefix):]
        if target != original:
            connection.exec_driver_sql(f"ALTER TABLE {quote(schema)}.{quote(row['table_name'])} RENAME CONSTRAINT {quote(original)} TO {quote(target)}")
    indexes = connection.execute(text("""
        SELECT i.relname FROM pg_index x JOIN pg_class i ON i.oid=x.indexrelid
        JOIN pg_namespace n ON n.oid=i.relnamespace
        WHERE n.nspname=:schema AND NOT EXISTS
        (SELECT 1 FROM pg_constraint c WHERE c.conindid=i.oid AND c.contype IN ('p','u','x'))
    """), {"schema":schema}).scalars().all()
    for original in indexes:
        target = _bounded(prefix + original) if restoring and not original.startswith(prefix) else original
        if not restoring and original.startswith(prefix):
            target = original[len(prefix):]
        if target != original:
            connection.exec_driver_sql(f"ALTER INDEX {quote(schema)}.{quote(original)} RENAME TO {quote(target)}")


@contextmanager
def logical_migration_namespace(connection, mapping, *, prefix, adopt_legacy=False):
    """Run the existing histories transactionally without changing their files.

The caller must hold an installation migration lock and an active transaction.
Only explicitly owned tables enter the private scope; unrelated public objects
remain untouched. The entire staging/upgrade/rename rolls back on failure.
"""
    validate_prefix(prefix)
    if not prefix:
        yield
        return
    if not connection.in_transaction():
        raise RuntimeError("Namespace migrations require an explicit transaction")
    quote = lambda value: _identifier(connection, value)
    postgres = connection.dialect.name == "postgresql"
    schema = connection.execute(text("SELECT current_schema()")).scalar_one() if postgres else None
    existing = set(inspect(connection).get_table_names(schema=schema))
    owned = {}
    for logical, physical in mapping.items():
        if physical in existing:
            owned[logical] = physical
        elif adopt_legacy and logical in existing:
            owned[logical] = logical
        if not postgres and logical in existing and owned.get(logical) != logical:
            raise RuntimeError("SQLite logical-name collision; namespace migration refused")
    staging = prefix + "migration_" + uuid4().hex[:12]
    original_path = None
    previous = connection.info.get("core_logical_migrations")
    legacy_alter_table = None
    try:
        if postgres:
            original_path = connection.execute(text("SHOW search_path")).scalar_one()
            connection.exec_driver_sql(f"CREATE SCHEMA {quote(staging)}")
            for logical, physical in owned.items():
                connection.exec_driver_sql(f"ALTER TABLE {quote(schema)}.{quote(physical)} SET SCHEMA {quote(staging)}")
                if physical != logical:
                    connection.exec_driver_sql(f"ALTER TABLE {quote(staging)}.{quote(physical)} RENAME TO {quote(logical)}")
            _postgres_objects(connection, staging, prefix, restoring=False)
            connection.execute(text("SELECT set_config('search_path', :path, true)"), {"path":quote(staging)})
        else:
            legacy_alter_table = connection.exec_driver_sql("PRAGMA legacy_alter_table").scalar_one()
            connection.exec_driver_sql("PRAGMA legacy_alter_table=OFF")
            for logical, physical in owned.items():
                if physical != logical:
                    connection.exec_driver_sql(f"ALTER TABLE {quote(physical)} RENAME TO {quote(logical)}")
        connection.info["core_logical_migrations"] = True
        yield
        actual = set(inspect(connection).get_table_names(schema=staging if postgres else None))
        if postgres:
            unknown = actual - set(mapping)
            if unknown:
                raise RuntimeError("Migration created an unowned table")
            _postgres_objects(connection, staging, prefix, restoring=True)
        else:
            connection.exec_driver_sql("PRAGMA legacy_alter_table=OFF")
        for logical, physical in mapping.items():
            if logical not in actual:
                continue
            location = f"{quote(staging)}." if postgres else ""
            connection.exec_driver_sql(f"ALTER TABLE {location}{quote(logical)} RENAME TO {quote(physical)}")
            if postgres:
                connection.exec_driver_sql(f"ALTER TABLE {quote(staging)}.{quote(physical)} SET SCHEMA {quote(schema)}")
        if postgres:
            connection.execute(text("SELECT set_config('search_path', :path, true)"), {"path":original_path})
            connection.exec_driver_sql(f"DROP SCHEMA {quote(staging)}")
    finally:
        if legacy_alter_table is not None:
            connection.exec_driver_sql(f"PRAGMA legacy_alter_table={int(legacy_alter_table)}")
        if previous is None:
            connection.info.pop("core_logical_migrations", None)
        else:
            connection.info["core_logical_migrations"] = previous
