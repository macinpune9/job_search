from datetime import datetime, timezone

from sqlalchemy import DateTime, create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.types import TypeDecorator

from .config import get_settings


class UTCDateTime(TypeDecorator):
    """Stores naive UTC, returns timezone-aware UTC (SQLite drops tzinfo)."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


def make_engine(url: str | None = None):
    url = url or get_settings().database_url
    kwargs = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    eng = create_engine(url, pool_pre_ping=True, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(eng, "connect")
        def _pragmas(dbapi_conn, _):
            dbapi_conn.isolation_level = None  # we emit BEGIN ourselves (see below)
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

        @event.listens_for(eng, "begin")
        def _begin_immediate(conn):
            # Take the write lock up front so concurrent workers queue (honouring `timeout`) instead of failing
            # with SQLITE_BUSY when a stale read snapshot tries to upgrade. PostgreSQL does not need this.
            conn.exec_driver_sql("BEGIN IMMEDIATE")

    return eng


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
