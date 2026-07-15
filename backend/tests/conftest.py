import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
# Import only the models needed for these tests so Base.metadata excludes
# pgvector-backed tables (kb_documents) that SQLite cannot create.
import app.models.employee  # noqa
import app.models.task  # noqa
import app.models.task_attachment  # noqa
import app.models.sop  # noqa


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        engine,
        tables=[
            Base.metadata.tables["employees"],
            Base.metadata.tables["tasks"],
            Base.metadata.tables["follow_ups"],
            Base.metadata.tables["task_attachments"],
            Base.metadata.tables["sop_definitions"],
        ],
    )
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


@pytest.fixture
def make_task(db):
    from app.models.task import Task, Priority, TaskStatus
    from datetime import datetime, timezone
    def _make(checklist_json=None):
        t = Task(
            title="Cleaning", priority=Priority.medium, status=TaskStatus.pending,
            assigned_by_id="admin1", assigned_to_id="emp1",
            assigned_at=datetime.now(timezone.utc),
            requires_attachment=True, attachment_checklist=checklist_json,
        )
        db.add(t); db.commit(); db.refresh(t)
        return t
    return _make
