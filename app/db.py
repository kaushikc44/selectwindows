# app/db.py
from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.models import Base

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

# No Alembic in this project — create_all() only creates missing *tables*,
# it never alters an existing one. New nullable columns/enum values added to
# app/models.py after the first deploy need an explicit, idempotent patch
# here so real data in already-existing tables is never touched or dropped.
_SCHEMA_PATCHES = [
    "ALTER TABLE items ADD COLUMN IF NOT EXISTS sill_height_mm INTEGER",
    "ALTER TABLE quotes ADD COLUMN IF NOT EXISTS agent_notes TEXT",
    "ALTER TYPE quote_status ADD VALUE IF NOT EXISTS 'changes_requested'",
    # Postgres has no CREATE TYPE IF NOT EXISTS — on a brand-new DB,
    # create_all() already created this type from the Python enum, so the
    # DO block below just needs to swallow the resulting duplicate_object
    # error rather than actually create anything twice.
    """
    DO $$ BEGIN
        CREATE TYPE worker_role AS ENUM ('tradie', 'sales', 'owner');
    EXCEPTION
        WHEN duplicate_object THEN null;
    END $$;
    """,
    "ALTER TABLE workers ADD COLUMN IF NOT EXISTS role worker_role NOT NULL DEFAULT 'tradie'",
    # Backfill from the old is_owner boolean before dropping it — guarded
    # so this is a no-op on a fresh DB that never had is_owner at all (the
    # Phase F migration replaces is_owner with role; only a DB that lived
    # through Phase E has both columns at this point in the patch sequence).
    """
    DO $$ BEGIN
        IF EXISTS (
            SELECT FROM information_schema.columns
            WHERE table_name = 'workers' AND column_name = 'is_owner'
        ) THEN
            UPDATE workers SET role = 'owner' WHERE is_owner = true;
        END IF;
    END $$;
    """,
    "ALTER TABLE workers DROP COLUMN IF EXISTS is_owner",
    "ALTER TABLE quotes ADD COLUMN IF NOT EXISTS assigned_tradie_id VARCHAR(36) REFERENCES workers(id)",
    "ALTER TABLE quotes ADD COLUMN IF NOT EXISTS scheduled_date VARCHAR(20)",
    "ALTER TYPE quote_status ADD VALUE IF NOT EXISTS 'scheduled'",
    "ALTER TYPE quote_status ADD VALUE IF NOT EXISTS 'missed'",
    "ALTER TABLE quotes ADD COLUMN IF NOT EXISTS readiness_score INTEGER",
]


def create_all() -> None:
    Base.metadata.create_all(bind=engine)
    if engine.dialect.name == "postgresql":
        # ALTER TYPE ... ADD VALUE can't be used in the same transaction it
        # runs in, so these run autocommit rather than under engine.begin().
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            for statement in _SCHEMA_PATCHES:
                conn.execute(text(statement))


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
