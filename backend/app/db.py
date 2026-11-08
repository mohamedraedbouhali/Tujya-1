"""Database engine, declarative base and a timezone-aware datetime column type."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, Engine, MetaData, create_engine, event, inspect, text
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator


class Base(DeclarativeBase):
    pass


class UTCDateTime(TypeDecorator[datetime]):
    """Datetime stored in UTC and always returned timezone-aware (SQLite drops the offset)."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime: pass a timezone-aware value")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        return None if value is None else value.replace(tzinfo=UTC)


def utc_now() -> datetime:
    return datetime.now(UTC)


def add_missing_columns(engine: Engine, metadata: MetaData) -> None:
    """Add the columns a model gained after its table was created.

    `create_all` makes missing tables but never changes an existing one. New columns must be
    nullable, so every row already in the table stays valid without a default.
    """
    inspector = inspect(engine)
    quote = engine.dialect.identifier_preparer.quote
    with engine.begin() as connection:
        for table in metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue
            present = {column["name"] for column in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in present:
                    continue
                if not column.nullable:
                    raise RuntimeError(f"cannot add required column {table.name}.{column.name}")
                kind = column.type.compile(dialect=engine.dialect)
                # Names come from our own models, quoted for the database in use.
                connection.execute(
                    text(f"ALTER TABLE {quote(table.name)} ADD COLUMN {quote(column.name)} {kind}")
                )


def make_engine(url: str) -> Engine:
    if not url.startswith("sqlite"):
        return create_engine(url)
    # Requests are served from a thread pool, so one connection is used by several threads.
    engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _enforce_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine
