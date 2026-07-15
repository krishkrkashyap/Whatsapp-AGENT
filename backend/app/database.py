from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from contextlib import contextmanager
from app.config import settings

engine = create_engine(settings.database_url, echo=False)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

class Base(DeclarativeBase):
    pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@contextmanager
def get_db_context():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def _migrate_kb_language_column():
    """Add `language` column to kb_documents if missing (no-alembic migration)."""
    from sqlalchemy import inspect, text as sql_text
    inspector = inspect(engine)
    columns = [c["name"] for c in inspector.get_columns("kb_documents")]
    if "language" not in columns:
        with engine.begin() as conn:
            conn.execute(sql_text("ALTER TABLE kb_documents ADD COLUMN language VARCHAR(20) DEFAULT 'english'"))
        print("Migration: added `language` column to kb_documents.")
    # Backfill language for rows with NULL language
    with engine.begin() as conn:
        result = conn.execute(
            sql_text("UPDATE kb_documents SET language = 'english' WHERE language IS NULL OR language = ''")
        )
        if result.rowcount:
            print(f"Migration: backfilled language for {result.rowcount} rows.")

def _migrate_interval_float():
    """Change follow_up_interval_hours to DOUBLE PRECISION in tasks & follow_ups."""
    from sqlalchemy import inspect, text as sql_text
    for tbl, col in [("tasks", "follow_up_interval_hours"), ("follow_ups", "interval_hours")]:
        inspector = inspect(engine)
        columns = [c["name"] for c in inspector.get_columns(tbl)]
        if col in columns:
            with engine.begin() as conn:
                conn.execute(sql_text(
                    f"ALTER TABLE {tbl} ALTER COLUMN {col} TYPE DOUBLE PRECISION USING {col}::double precision"
                ))
            print(f"Migration: changed {tbl}.{col} to DOUBLE PRECISION.")

def _migrate_employee_preferred_language():
    """Add `preferred_language` column to employees if missing (no-alembic migration)."""
    from sqlalchemy import inspect, text as sql_text
    inspector = inspect(engine)
    columns = [c["name"] for c in inspector.get_columns("employees")]
    if "preferred_language" not in columns:
        with engine.begin() as conn:
            conn.execute(sql_text(
                "ALTER TABLE employees ADD COLUMN preferred_language VARCHAR(20) DEFAULT 'english'"
            ))
        print("Migration: added `preferred_language` column to employees.")

def _migrate_sop_interval():
    """Add interval_hours (sop_definitions) + scheduled_time (sop_executions)
    columns if missing (no-alembic migration). create_all only creates new
    tables, never alters existing ones, so new columns need this."""
    from sqlalchemy import inspect, text as sql_text
    inspector = inspect(engine)

    sop_cols = [c["name"] for c in inspector.get_columns("sop_definitions")]
    if "interval_hours" not in sop_cols:
        with engine.begin() as conn:
            conn.execute(sql_text(
                "ALTER TABLE sop_definitions ADD COLUMN interval_hours DOUBLE PRECISION"
            ))
        print("Migration: added `interval_hours` column to sop_definitions.")

    exec_cols = [c["name"] for c in inspector.get_columns("sop_executions")]
    if "scheduled_time" not in exec_cols:
        with engine.begin() as conn:
            conn.execute(sql_text(
                "ALTER TABLE sop_executions ADD COLUMN scheduled_time VARCHAR(5) DEFAULT ''"
            ))
        print("Migration: added `scheduled_time` column to sop_executions.")

def _migrate_attachment_checklist():
    """Add attachment_checklist columns (tasks, sop_definitions). create_all
    makes the new task_attachments table but never ALTERs existing tables."""
    from sqlalchemy import inspect, text as sql_text
    inspector = inspect(engine)
    for tbl in ("tasks", "sop_definitions"):
        cols = [c["name"] for c in inspector.get_columns(tbl)]
        if "attachment_checklist" not in cols:
            with engine.begin() as conn:
                conn.execute(sql_text(f"ALTER TABLE {tbl} ADD COLUMN attachment_checklist TEXT"))
            print(f"Migration: added `attachment_checklist` column to {tbl}.")

def _migrate_task_sla_enabled():
    """Add tasks.sla_enabled if missing. The column was added to the Task model
    without a migration; create_all never ALTERs existing tables, so every task
    query crashed with 'column tasks.sla_enabled does not exist'."""
    from sqlalchemy import inspect, text as sql_text
    inspector = inspect(engine)
    cols = [c["name"] for c in inspector.get_columns("tasks")]
    if "sla_enabled" not in cols:
        with engine.begin() as conn:
            conn.execute(sql_text(
                "ALTER TABLE tasks ADD COLUMN sla_enabled BOOLEAN NOT NULL DEFAULT true"
            ))
        print("Migration: added `sla_enabled` column to tasks.")


def _migrate_sop_paused_until():
    """Add sop_definitions.paused_until if missing. Drives timed auto-resume of
    paused SOPs; create_all never ALTERs existing tables."""
    from sqlalchemy import inspect, text as sql_text
    cols = [c["name"] for c in inspect(engine).get_columns("sop_definitions")]
    if "paused_until" not in cols:
        with engine.begin() as conn:
            conn.execute(sql_text(
                "ALTER TABLE sop_definitions ADD COLUMN paused_until TIMESTAMPTZ"
            ))
        print("Migration: added `paused_until` column to sop_definitions.")


def _migrate_sop_frequency_hourly():
    """Add 'hourly' to the Postgres `frequency` enum if missing. SQLAlchemy's
    create_all never alters an existing enum type, so a new Frequency member
    needs this. ADD VALUE must run outside a transaction block, so use an
    AUTOCOMMIT connection."""
    from sqlalchemy import text as sql_text
    try:
        with engine.connect() as conn:
            conn = conn.execution_options(isolation_level="AUTOCOMMIT")
            conn.execute(sql_text("ALTER TYPE frequency ADD VALUE IF NOT EXISTS 'hourly'"))
        print("Migration: ensured 'hourly' value on frequency enum.")
    except Exception as e:
        print(f"Migration: frequency enum 'hourly' add skipped/failed: {e}")


def _migrate_employee_on_leave():
    """Add employees.on_leave if missing (self-service leave state)."""
    from sqlalchemy import inspect, text as sql_text
    cols = [c["name"] for c in inspect(engine).get_columns("employees")]
    if "on_leave" not in cols:
        with engine.begin() as conn:
            conn.execute(sql_text(
                "ALTER TABLE employees ADD COLUMN IF NOT EXISTS on_leave BOOLEAN NOT NULL DEFAULT false"
            ))
        print("Migration: added `on_leave` column to employees.")

def _migrate_task_missed_status():
    """Add 'missed' value to the taskstatus enum if absent (SOP daily rollover).
    ALTER TYPE ADD VALUE must run outside a transaction — own AUTOCOMMIT conn."""
    from sqlalchemy import text as sql_text
    with engine.connect() as conn:
        conn.execution_options(isolation_level="AUTOCOMMIT").execute(
            sql_text("ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'missed'")
        )

def init_db():
    from sqlalchemy import text as sql_text
    # Enable pgvector extension (safe to run repeatedly)
    with engine.begin() as conn:
        conn.execute(sql_text("CREATE EXTENSION IF NOT EXISTS vector"))
    from app.models import employee, task, conversation, kb_document, escalation, audit_log, pending_registration, system_settings, lid_mapping, sop, department_config, task_attachment  # noqa
    Base.metadata.create_all(bind=engine)
    # Serialize schema migrations across the 4 uvicorn workers with a Postgres
    # session advisory lock. Without it, two workers race the inspect-then-ALTER
    # migrations and the loser crashes on "column already exists" (the ADD COLUMNs
    # also now use IF NOT EXISTS as a second guard).
    _LOCK_KEY = 778412  # arbitrary app-wide constant
    with engine.connect() as lock_conn:
        lock_conn = lock_conn.execution_options(isolation_level="AUTOCOMMIT")
        lock_conn.execute(sql_text("SELECT pg_advisory_lock(:k)"), {"k": _LOCK_KEY})
        try:
            _migrate_kb_language_column()
            _migrate_interval_float()
            _migrate_employee_preferred_language()
            _migrate_sop_interval()
            _migrate_attachment_checklist()
            _migrate_task_sla_enabled()
            _migrate_sop_frequency_hourly()
            _migrate_sop_paused_until()
            _migrate_task_missed_status()
            _migrate_employee_on_leave()
        finally:
            lock_conn.execute(sql_text("SELECT pg_advisory_unlock(:k)"), {"k": _LOCK_KEY})
    print("Database initialized. Tables created.")
