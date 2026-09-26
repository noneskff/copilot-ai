from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy import text
from sqlalchemy.pool import StaticPool
from config import DATABASE_URL

# check_same_thread=False is required for FastAPI's background tasks + SQLite.
# StaticPool is used automatically by SQLAlchemy for in-memory DBs in tests.
_connect_args = {"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args=_connect_args,
    poolclass=StaticPool if DATABASE_URL == "sqlite://" else None,
)


def create_db_and_tables() -> None:
    """Create all SQLModel tables if they don't exist, then run lightweight migrations."""
    SQLModel.metadata.create_all(engine)
    _run_migrations()


def _run_migrations() -> None:
    """
    Add any columns that were introduced after initial table creation.
    SQLite supports ALTER TABLE ADD COLUMN safely (idempotent checks included).
    """
    migrations = [
        ("repository", "scan_metadata", "TEXT"),
        ("issue", "file_path", "TEXT"),
        ("issue", "line_number", "INTEGER"),
        ("issue", "evidence", "TEXT"),
        ("issue", "suggested_fix", "TEXT"),
        ("issue", "confidence", "REAL"),
    ]
    with engine.connect() as conn:
        for table, column, col_type in migrations:
            rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
            existing = {r[1] for r in rows}
            if column not in existing:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
                conn.commit()


def get_session():
    """FastAPI dependency for a database session."""
    with Session(engine) as session:
        yield session
