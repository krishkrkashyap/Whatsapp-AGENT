# SOP Multi-Attachment Checklist Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let admins attach an ordered named photo-checklist to an SOP; SOP-generated tasks then collect one photo per item sequentially over WhatsApp, block completion until all arrive, and forward every photo + a status summary to the SOP admin.

**Architecture:** A new `task_attachments` table holds one pre-created `pending` row per checklist item. A focused `AttachmentService` is the checklist state machine (find active task, record a photo, list remaining, detect completion, forward to admin). The webhook delegates inbound media and `done` handling to it. SOP definitions gain a JSON `attachment_checklist` column copied onto each generated task.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Postgres (prod), SQLite in-memory (unit tests), pytest, OpenWA gateway, React/TS frontend.

## Global Constraints

- Checklist defined on **SOP only** — never on dashboard/WhatsApp one-off tasks.
- Photos are **transient**: stored as base64 only until forwarded, then `media_base64` is nulled. No served image archive, no dashboard gallery.
- Matching is **sequential**: each inbound photo fills the lowest-`item_index` pending row. No captions, no per-photo labeling by the sender.
- Forward recipient = the task's `assigned_by_id` (which for SOP tasks is `sop.admin_id or sop.assigned_to_id`).
- Empty/whitespace checklist ⇒ checklist mode OFF; legacy single-photo `requires_attachment` behavior unchanged.
- Repo is **not** git-initialized. Each "Commit (optional)" step is a no-op unless you run `git init` first; the required action is running the task's tests green.
- pytest is declared in `requirements.txt` but may not be installed — run `pip install -r requirements.txt` once before Task 2.

---

## File Structure

- Create `backend/app/models/task_attachment.py` — `TaskAttachment` model.
- Modify `backend/app/models/task.py` — add `Task.attachment_checklist` column.
- Modify `backend/app/models/sop.py` — add `SOPDefinition.attachment_checklist` column.
- Modify `backend/app/database.py` — register model + migration for the two new columns.
- Create `backend/app/services/attachment_service.py` — checklist state machine + forwarding.
- Modify `backend/app/services/whatsapp.py` — `send_whatsapp_media_base64`.
- Modify `backend/app/services/sop_service.py` — copy checklist onto task + pre-create rows; `update()` allow-list.
- Modify `backend/app/routers/webhook.py` — media extraction + delegate media/`done` to `AttachmentService`.
- Modify `backend/app/routers/sops.py` — surface `attachment_checklist` in list/get responses.
- Modify `backend/app/services/scheduler.py` — retry unforwarded completions on the periodic tick.
- Modify `frontend/src/pages/SOPManage.tsx` — checklist editor in the SOP form.
- Create `backend/tests/test_attachment_service.py`, `backend/tests/test_sop_checklist.py`, `backend/tests/conftest.py`.

---

### Task 1: Data model + migration

**Files:**
- Create: `backend/app/models/task_attachment.py`
- Modify: `backend/app/models/task.py:25-48` (add column inside `Task`)
- Modify: `backend/app/models/sop.py` (add column inside `SOPDefinition`)
- Modify: `backend/app/database.py:73-107` (migration + model import)

**Interfaces:**
- Produces:
  - `TaskAttachment` ORM model, table `task_attachments`, columns:
    `id:str, task_id:str, item_index:int, item_label:str, status:str("pending"|"received"), media_base64:str|None, media_mimetype:str|None, received_at:datetime|None, forwarded_at:datetime|None, created_at:datetime`.
  - `Task.attachment_checklist: str|None` (JSON array text).
  - `SOPDefinition.attachment_checklist: str|None` (JSON array text).

- [ ] **Step 1: Create the model file**

`backend/app/models/task_attachment.py`:
```python
from datetime import datetime, timezone
from sqlalchemy import String, Text, Integer, DateTime, ForeignKey
from sqlalchemy.orm import mapped_column, Mapped
from app.database import Base
import uuid


class TaskAttachment(Base):
    """One row per checklist item on a multi-attachment task.

    Pre-created `pending` when the task is generated; flipped to `received`
    (with the base64 image) as the employee sends each photo. base64 is nulled
    after the photo is forwarded to the admin — these rows are not an archive."""
    __tablename__ = "task_attachments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    item_index: Mapped[int] = mapped_column(Integer)
    item_label: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | received
    media_base64: Mapped[str] = mapped_column(Text, nullable=True)
    media_mimetype: Mapped[str] = mapped_column(String(100), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    forwarded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
```

- [ ] **Step 2: Add `attachment_checklist` to `Task`**

In `backend/app/models/task.py`, inside `class Task`, after the `bulk_group_id` line (`:48`):
```python
    # JSON array of checklist item names; non-empty => multi-attachment mode.
    # Copied from the originating SOP; not user-editable on one-off tasks.
    attachment_checklist: Mapped[str] = mapped_column(Text, nullable=True)
```

- [ ] **Step 3: Add `attachment_checklist` to `SOPDefinition`**

In `backend/app/models/sop.py`, inside `class SOPDefinition` (next to the other optional columns):
```python
    # JSON array of checklist item names requiring one photo each.
    attachment_checklist: Mapped[str] = mapped_column(Text, nullable=True)
```

- [ ] **Step 4: Register model + migrate columns in `database.py`**

In `backend/app/database.py`, add a migration function after `_migrate_sop_interval` (`:94`):
```python
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
```
In `init_db`, add `task_attachment` to the model import line (`:101`) and call the migration after `_migrate_sop_interval()` (`:106`):
```python
    from app.models import employee, task, conversation, kb_document, escalation, audit_log, pending_registration, system_settings, lid_mapping, sop, department_config, task_attachment  # noqa
```
```python
    _migrate_attachment_checklist()
```

- [ ] **Step 5: Verify it imports and migration is idempotent**

Run: `cd backend && python -c "import app.models.task_attachment, app.models.task, app.models.sop, app.database; print('ok')"`
Expected: prints `ok` (no import error).

- [ ] **Step 6: Commit (optional — see Global Constraints)**
```bash
git add backend/app/models/task_attachment.py backend/app/models/task.py backend/app/models/sop.py backend/app/database.py
git commit -m "feat: task_attachments table + attachment_checklist columns"
```

---

### Task 2: AttachmentService core (state machine)

**Files:**
- Create: `backend/app/services/attachment_service.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_attachment_service.py`

**Interfaces:**
- Consumes: `TaskAttachment`, `Task`, `Employee` from Task 1 / existing models.
- Produces `AttachmentService(db)` with:
  - `get_checklist(task) -> list[str]` (parse JSON, `[]` on null/garbage)
  - `create_checklist_rows(task_id: str, items: list[str]) -> None`
  - `find_active_checklist_task(employee_id: str) -> Task | None`
  - `pending_rows(task_id: str) -> list[TaskAttachment]` (ordered by item_index)
  - `received_rows(task_id: str) -> list[TaskAttachment]` (ordered by item_index)
  - `remaining_items(task_id: str) -> list[str]`
  - `record_media(task, media_base64: str|None, mimetype: str|None) -> tuple[TaskAttachment, int, int]` → (filled row, received_count, total)
  - `is_complete(task_id: str) -> bool`

- [ ] **Step 1: Write the failing tests**

`backend/tests/conftest.py`:
```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
# Import only the models needed for these tests so Base.metadata excludes
# pgvector-backed tables (kb_documents) that SQLite cannot create.
import app.models.employee  # noqa
import app.models.task  # noqa
import app.models.task_attachment  # noqa


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
```

`backend/tests/test_attachment_service.py`:
```python
import json
from app.services.attachment_service import AttachmentService


ITEMS = ["Production Floor", "Cold Room", "Side Wall"]


def test_create_rows_and_remaining(db, make_task):
    task = make_task(json.dumps(ITEMS))
    svc = AttachmentService(db)
    svc.create_checklist_rows(task.id, ITEMS)
    assert svc.remaining_items(task.id) == ITEMS
    assert svc.is_complete(task.id) is False


def test_record_fills_in_order(db, make_task):
    task = make_task(json.dumps(ITEMS))
    svc = AttachmentService(db)
    svc.create_checklist_rows(task.id, ITEMS)

    row, received, total = svc.record_media(task, "BASE64A", "image/jpeg")
    assert (row.item_label, received, total) == ("Production Floor", 1, 3)
    assert row.status == "received" and row.media_base64 == "BASE64A"
    assert svc.remaining_items(task.id) == ["Cold Room", "Side Wall"]

    svc.record_media(task, "BASE64B", "image/jpeg")
    row3, received3, total3 = svc.record_media(task, "BASE64C", "image/jpeg")
    assert (received3, total3) == (3, 3)
    assert svc.is_complete(task.id) is True
    assert svc.remaining_items(task.id) == []


def test_find_active_checklist_task(db, make_task):
    plain = make_task(None)            # no checklist
    cl = make_task(json.dumps(ITEMS))  # checklist task
    svc = AttachmentService(db)
    svc.create_checklist_rows(cl.id, ITEMS)
    found = svc.find_active_checklist_task("emp1")
    assert found is not None and found.id == cl.id


def test_record_with_missing_base64_still_counts(db, make_task):
    task = make_task(json.dumps(["Only Item"]))
    svc = AttachmentService(db)
    svc.create_checklist_rows(task.id, ["Only Item"])
    row, received, total = svc.record_media(task, None, None)
    assert row.status == "received" and (received, total) == (1, 1)
    assert svc.is_complete(task.id) is True


def test_get_checklist_handles_garbage(db, make_task):
    svc = AttachmentService(db)
    assert svc.get_checklist(make_task(None)) == []
    assert svc.get_checklist(make_task("not json")) == []
    assert svc.get_checklist(make_task(json.dumps(ITEMS))) == ITEMS
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `cd backend && pip install -r requirements.txt && python -m pytest tests/test_attachment_service.py -v`
Expected: FAIL — `ModuleNotFoundError: app.services.attachment_service`.

- [ ] **Step 3: Implement the service core**

`backend/app/services/attachment_service.py`:
```python
"""Multi-attachment checklist state machine for SOP-generated tasks."""
import json
import logging
from datetime import datetime, timezone
from sqlalchemy import select
from app.models.task import Task, TaskStatus
from app.models.task_attachment import TaskAttachment

logger = logging.getLogger("attachment_service")


class AttachmentService:
    def __init__(self, db):
        self.db = db

    def get_checklist(self, task) -> list:
        raw = getattr(task, "attachment_checklist", None)
        if not raw:
            return []
        try:
            items = json.loads(raw)
        except (ValueError, TypeError):
            return []
        return [str(i).strip() for i in items if str(i).strip()] if isinstance(items, list) else []

    def create_checklist_rows(self, task_id: str, items: list) -> None:
        for idx, label in enumerate(items):
            self.db.add(TaskAttachment(task_id=task_id, item_index=idx, item_label=label, status="pending"))
        self.db.commit()

    def pending_rows(self, task_id: str) -> list:
        return list(self.db.execute(
            select(TaskAttachment).where(
                TaskAttachment.task_id == task_id, TaskAttachment.status == "pending"
            ).order_by(TaskAttachment.item_index)
        ).scalars().all())

    def received_rows(self, task_id: str) -> list:
        return list(self.db.execute(
            select(TaskAttachment).where(
                TaskAttachment.task_id == task_id, TaskAttachment.status == "received"
            ).order_by(TaskAttachment.item_index)
        ).scalars().all())

    def remaining_items(self, task_id: str) -> list:
        return [r.item_label for r in self.pending_rows(task_id)]

    def is_complete(self, task_id: str) -> bool:
        return len(self.pending_rows(task_id)) == 0 and len(self.received_rows(task_id)) > 0

    def find_active_checklist_task(self, employee_id: str):
        """Most-recently-assigned pending/in_progress task for this employee that
        still has a pending checklist item."""
        rows = self.db.execute(
            select(Task).where(
                Task.assigned_to_id == employee_id,
                Task.status.in_([TaskStatus.pending, TaskStatus.in_progress]),
            ).order_by(Task.assigned_at.desc())
        ).scalars().all()
        for task in rows:
            if self.pending_rows(task.id):
                return task
        return None

    def record_media(self, task, media_base64, mimetype):
        """Fill the lowest-index pending row. Returns (row, received_count, total)."""
        pending = self.pending_rows(task.id)
        row = pending[0]
        row.status = "received"
        row.media_base64 = media_base64
        row.media_mimetype = mimetype
        row.received_at = datetime.now(timezone.utc)
        if task.status == TaskStatus.pending:
            task.status = TaskStatus.in_progress
        self.db.commit()
        total = len(self.pending_rows(task.id)) + len(self.received_rows(task.id))
        received = len(self.received_rows(task.id))
        return row, received, total
```

- [ ] **Step 4: Run tests, verify pass**

Run: `cd backend && python -m pytest tests/test_attachment_service.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit (optional)**
```bash
git add backend/app/services/attachment_service.py backend/tests/conftest.py backend/tests/test_attachment_service.py
git commit -m "feat: AttachmentService checklist state machine + tests"
```

---

### Task 3: SOP → task checklist copy

**Files:**
- Modify: `backend/app/services/sop_service.py:258-291` (`_create_task_for_sop`) and `:46-68` (`update` allow-list)
- Create: `backend/tests/test_sop_checklist.py`

**Interfaces:**
- Consumes: `AttachmentService.create_checklist_rows`, `AttachmentService.get_checklist`.
- Produces: an SOP whose `attachment_checklist` is non-empty creates a Task with the same `attachment_checklist`, `requires_attachment=True`, and pre-created pending `task_attachments` rows.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_sop_checklist.py`:
```python
import json
from app.services.attachment_service import AttachmentService
from app.models.task_attachment import TaskAttachment


def test_create_task_copies_checklist(db, make_task, monkeypatch):
    # Build a minimal fake SOP object with the fields _create_task_for_sop reads.
    class FakeSOP:
        id = "sop1"; title = "Daily Clean"; description = None; priority = "medium"
        admin_id = "admin1"; assigned_to_id = "emp1"; requires_attachment = True
        start_time = "09:00"
        attachment_checklist = json.dumps(["Production Floor", "Cold Room"])

    from app.services import sop_service as mod
    # Stop the SOP service from sending WhatsApp / touching unrelated tables.
    monkeypatch.setattr(mod.SOPService, "_notify_employee", lambda *a, **k: None)

    svc = mod.SOPService(db)
    # _get_or_create_execution writes to sop_executions; stub it to a simple obj.
    class Exec: task_id = None; status = "pending"; notified_at = None
    monkeypatch.setattr(svc, "_get_or_create_execution", lambda *a, **k: Exec())

    from datetime import date
    svc._create_task_for_sop(FakeSOP(), date.today(), "09:00")

    rows = db.query(TaskAttachment).order_by(TaskAttachment.item_index).all()
    assert [r.item_label for r in rows] == ["Production Floor", "Cold Room"]
    assert all(r.status == "pending" for r in rows)
```
Add `tasks`+`task_attachments` are already created by the `db` fixture; this test also needs `sop_definitions`/`sop_executions` tables NOT touched because `_get_or_create_execution` is stubbed. The Task insert uses the `tasks` table from conftest.

- [ ] **Step 2: Run test, verify it fails**

Run: `cd backend && python -m pytest tests/test_sop_checklist.py -v`
Expected: FAIL — checklist rows not created (assert on `rows` empty).

- [ ] **Step 3: Implement the copy in `_create_task_for_sop`**

In `backend/app/services/sop_service.py`, inside `_create_task_for_sop`, change the `Task(...)` construction to include the checklist and force `requires_attachment` when a checklist exists, then create the rows after `db.flush()`:
```python
        from app.services.attachment_service import AttachmentService
        checklist = AttachmentService(self.db).get_checklist(sop)

        task = Task(
            title=sop.title,
            description=sop.description,
            priority=Priority(sop.priority),
            status=TaskStatus.pending,
            assigned_by_id=sop.admin_id or sop.assigned_to_id,
            assigned_to_id=sop.assigned_to_id,
            assigned_at=datetime.now(timezone.utc),
            requires_attachment=sop.requires_attachment or bool(checklist),
            attachment_checklist=sop.attachment_checklist if checklist else None,
        )
        self.db.add(task)
        self.db.flush()

        if checklist:
            AttachmentService(self.db).create_checklist_rows(task.id, checklist)
```
(Replace the existing `task = Task(...)`, `self.db.add(task)`, `self.db.flush()` block; keep the lines after it — `execution.task_id = task.id`, etc. — unchanged.)

- [ ] **Step 4: Add `attachment_checklist` to `update()` allow-list**

In `backend/app/services/sop_service.py` `update()`, add `"attachment_checklist"` to the field list (`:52-56`):
```python
        for field in ["title", "description", "department", "frequency", "days_of_week",
                       "day_of_month", "start_time", "end_time", "interval_hours",
                       "assigned_to_id", "admin_id",
                       "requires_attachment", "notify_before_min", "notify_after_min",
                       "admin_notify_after_min", "priority", "status", "attachment_checklist"]:
```
`create()` already passes `data.get(...)` for known keys — add the line in the `SOPDefinition(...)` constructor:
```python
            attachment_checklist=data.get("attachment_checklist"),
```

- [ ] **Step 5: Run test, verify pass**

Run: `cd backend && python -m pytest tests/test_sop_checklist.py -v`
Expected: PASS.

- [ ] **Step 6: Commit (optional)**
```bash
git add backend/app/services/sop_service.py backend/tests/test_sop_checklist.py
git commit -m "feat: SOP copies attachment checklist onto generated task"
```

---

### Task 4: WhatsApp base64 media sender

**Files:**
- Modify: `backend/app/services/whatsapp.py:106-124` (add new function after `send_whatsapp_with_media`)

**Interfaces:**
- Produces: `send_whatsapp_media_base64(to_number: str, caption: str, media_base64: str, mimetype: str = "image/jpeg") -> str` — returns OpenWA message id or `"error"`/`"dev-mode-sid"`.

- [ ] **Step 1: Implement (no unit test — thin HTTP wrapper, covered by Task 5 via monkeypatch)**

In `backend/app/services/whatsapp.py`, after `send_whatsapp_with_media`:
```python
def send_whatsapp_media_base64(to_number: str, caption: str, media_base64: str,
                               mimetype: str = "image/jpeg") -> str:
    """Send an image to WhatsApp from an in-memory base64 payload (used to
    forward collected checklist photos). OpenWA's send-image accepts `base64`."""
    if not settings.openwa_api_key or not settings.openwa_session_id:
        logger.info(f"[DEV MODE] WhatsApp+b64 -> {to_number}: {caption[:60]}")
        return "dev-mode-sid"
    if not media_base64:
        # Nothing to send as an image — fall back to a text note.
        return send_whatsapp(to_number, caption)
    try:
        resp = httpx.post(
            f"{settings.openwa_base_url}/sessions/{settings.openwa_session_id}/messages/send-image",
            headers=_get_headers(),
            json={"chatId": _to_chat_id(to_number), "caption": caption,
                  "base64": media_base64, "mimetype": mimetype},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})
        return data.get("messageId") or data.get("id", "unknown")
    except Exception as e:
        logger.error(f"OpenWA base64 media send error: {e}")
        return "error"
```

- [ ] **Step 2: Verify import**

Run: `cd backend && python -c "from app.services.whatsapp import send_whatsapp_media_base64; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Commit (optional)**
```bash
git add backend/app/services/whatsapp.py
git commit -m "feat: send_whatsapp_media_base64 for forwarding checklist photos"
```

---

### Task 5: Forwarding on completion + retry

**Files:**
- Modify: `backend/app/services/attachment_service.py` (add `forward_completed`, `retry_unforwarded`)
- Modify: `backend/app/services/scheduler.py:156-195` (`_run_periodic_followups` calls retry)
- Modify: `backend/tests/test_attachment_service.py` (add forwarding tests)

**Interfaces:**
- Consumes: `send_whatsapp`, `send_whatsapp_media_base64`, `EmployeeService.get_by_id`.
- Produces:
  - `AttachmentService.forward_completed(task) -> bool` — sends summary + each received photo to `task.assigned_by_id`'s employee; on full success sets `forwarded_at` and nulls `media_base64`; returns True if every photo forwarded.
  - `AttachmentService.retry_unforwarded() -> int` — re-forwards `done` checklist tasks that still hold unforwarded received rows; returns count retried.

- [ ] **Step 1: Write failing tests (append to `test_attachment_service.py`)**
```python
def test_forward_completed_sends_and_clears(db, make_task, monkeypatch):
    import json
    from app.services import attachment_service as mod
    task = make_task(json.dumps(["Floor", "Wall"]))
    svc = mod.AttachmentService(db)
    svc.create_checklist_rows(task.id, ["Floor", "Wall"])
    svc.record_media(task, "B64A", "image/jpeg")
    svc.record_media(task, "B64B", "image/jpeg")

    sent_images, sent_text = [], []
    monkeypatch.setattr(mod, "send_whatsapp_media_base64",
                        lambda to, cap, b64, mt="image/jpeg": sent_images.append((to, cap, b64)) or "id")
    monkeypatch.setattr(mod, "send_whatsapp", lambda to, body: sent_text.append((to, body)) or "id")
    # Resolve assigner -> a fake employee with a number.
    class Emp: whatsapp_number = "+91999"; name = "Boss"; department = "Ops"; role = "Mgr"
    monkeypatch.setattr(mod.AttachmentService, "_assigner_and_worker",
                        lambda self, t: (Emp(), Emp()))

    ok = svc.forward_completed(task)
    assert ok is True
    assert len(sent_images) == 2 and sent_text  # summary + 2 photos
    rows = svc.received_rows(task.id)
    assert all(r.forwarded_at is not None and r.media_base64 is None for r in rows)


def test_forward_failure_keeps_bytes(db, make_task, monkeypatch):
    import json
    from app.services import attachment_service as mod
    task = make_task(json.dumps(["Floor"]))
    svc = mod.AttachmentService(db)
    svc.create_checklist_rows(task.id, ["Floor"])
    svc.record_media(task, "B64A", "image/jpeg")
    monkeypatch.setattr(mod, "send_whatsapp_media_base64", lambda *a, **k: "error")
    monkeypatch.setattr(mod, "send_whatsapp", lambda *a, **k: "id")
    class Emp: whatsapp_number = "+91999"; name = "Boss"; department = "Ops"; role = "Mgr"
    monkeypatch.setattr(mod.AttachmentService, "_assigner_and_worker",
                        lambda self, t: (Emp(), Emp()))
    ok = svc.forward_completed(task)
    assert ok is False
    row = svc.received_rows(task.id)[0]
    assert row.media_base64 == "B64A" and row.forwarded_at is None
```

- [ ] **Step 2: Run, verify fail**

Run: `cd backend && python -m pytest tests/test_attachment_service.py -k forward -v`
Expected: FAIL — `forward_completed` missing.

- [ ] **Step 3: Implement forwarding**

At the top of `backend/app/services/attachment_service.py` add imports:
```python
from app.services.whatsapp import send_whatsapp, send_whatsapp_media_base64
from app.services.employee_svc import EmployeeService
```
Add methods to `AttachmentService`:
```python
    def _assigner_and_worker(self, task):
        svc = EmployeeService(self.db)
        return svc.get_by_id(task.assigned_by_id), svc.get_by_id(task.assigned_to_id)

    def forward_completed(self, task) -> bool:
        """Forward summary + every received photo to the task's assigner (SOP
        admin). On full success, null base64 and stamp forwarded_at. Idempotent:
        rows already forwarded are skipped."""
        assigner, worker = self._assigner_and_worker(task)
        if not assigner:
            logger.warning("No assigner to forward task %s to", task.id)
            return False

        rows = [r for r in self.received_rows(task.id) if r.forwarded_at is None]
        if not rows:
            return True

        station = f"{getattr(worker, 'department', '?')}/{getattr(worker, 'role', '?')}" if worker else "?"
        worker_name = getattr(worker, "name", "Unknown") if worker else "Unknown"
        done_time = (task.completed_at or datetime.now(timezone.utc)).strftime("%d %b %H:%M")
        lines = [f"✅ *SOP Completed:* {task.title}",
                 f"👤 {worker_name}  ·  🏢 {station}",
                 f"🕒 {done_time}", "", "*Items:*"]
        for r in self.received_rows(task.id):
            t = r.received_at.strftime("%H:%M") if r.received_at else "—"
            lines.append(f"✓ {r.item_label} — {t}")
        send_whatsapp(assigner.whatsapp_number, "\n".join(lines))

        all_ok = True
        for r in rows:
            mid = send_whatsapp_media_base64(
                assigner.whatsapp_number, f"📎 {task.title}: {r.item_label}",
                r.media_base64 or "", r.media_mimetype or "image/jpeg")
            if mid and mid != "error":
                r.forwarded_at = datetime.now(timezone.utc)
                r.media_base64 = None  # free transient bytes
            else:
                all_ok = False
        self.db.commit()
        return all_ok

    def retry_unforwarded(self) -> int:
        """Re-attempt forwarding for done checklist tasks with leftover bytes."""
        rows = self.db.execute(
            select(TaskAttachment).where(
                TaskAttachment.status == "received",
                TaskAttachment.forwarded_at == None,  # noqa: E711
                TaskAttachment.media_base64 != None,  # noqa: E711
            )
        ).scalars().all()
        task_ids = {r.task_id for r in rows}
        retried = 0
        for tid in task_ids:
            task = self.db.execute(select(Task).where(Task.id == tid)).scalar_one_or_none()
            if task and task.status == TaskStatus.done:
                self.forward_completed(task)
                retried += 1
        return retried
```

- [ ] **Step 4: Wire retry into the scheduler**

In `backend/app/services/scheduler.py` `_run_periodic_followups`, after the existing follow-up loop (before the final `logger.info`), add:
```python
        try:
            from app.services.attachment_service import AttachmentService
            AttachmentService(db).retry_unforwarded()
        except Exception as e:
            logger.warning("Attachment forward retry failed: %s", e)
```

- [ ] **Step 5: Run, verify pass**

Run: `cd backend && python -m pytest tests/test_attachment_service.py -v`
Expected: PASS (7 tests).

- [ ] **Step 6: Commit (optional)**
```bash
git add backend/app/services/attachment_service.py backend/app/services/scheduler.py backend/tests/test_attachment_service.py
git commit -m "feat: forward completed checklist photos to SOP admin + retry"
```

---

### Task 6: Webhook wiring (media in, done block)

**Files:**
- Modify: `backend/app/routers/webhook.py:178-227` (`_extract_from_openwa_payload` → also return media) and `:230-391` (handler), `:548-583` (`_handle_task_done`)

**Interfaces:**
- Consumes: `AttachmentService` (Tasks 2/5).
- Produces: inbound media routed to `AttachmentService.record_media`; checklist completion triggers `mark_done` + `forward_completed`; `done` with missing items lists remaining and does not complete.

- [ ] **Step 1: Extend media extraction**

In `_extract_from_openwa_payload`, change the return to a 5-tuple `(body, from_number, has_attachment, raw_chat_id, media)` where `media` is `(base64, mimetype)` or `(None, None)`. Add before the `return`:
```python
    media_obj = data.get("media") if isinstance(data, dict) else None
    media_b64 = media_mime = None
    if isinstance(media_obj, dict):
        media_b64 = media_obj.get("data") or media_obj.get("base64")
        media_mime = media_obj.get("mimetype")
    return (body, from_number, has_attachment, raw_chat_id, (media_b64, media_mime))
```
Also update the early-return stub near the top of the function (`return ("", "", False, "")`) to `return ("", "", False, "", (None, None))`.

- [ ] **Step 2: Update the caller + unpack media**

In `whatsapp_webhook`, the JSON branch (`:264-269`) becomes:
```python
    media = (None, None)
    if "json" in content_type:
        try:
            raw = json.loads(raw_bytes) if raw_bytes else {}
        except Exception:
            raw = {}
        body, from_number, has_attachment, raw_chat_id, media = _extract_from_openwa_payload(raw)
    else:
        form_data = await request.form()
        body = form_data.get("Body", "").strip()
        from_number = form_data.get("From", "").replace("whatsapp:", "")
        num_media = int(form_data.get("NumMedia", 0))
        has_attachment = num_media > 0
```

- [ ] **Step 3: Route media to the checklist BEFORE intent parsing**

In `whatsapp_webhook`, immediately after the employee is resolved and `task_mgr` is created (after `:294`), add:
```python
        # Multi-attachment checklist: an inbound photo fills the next item.
        media_b64, media_mime = media
        if has_attachment:
            from app.services.attachment_service import AttachmentService
            att_svc = AttachmentService(db)
            active = att_svc.find_active_checklist_task(employee.id)
            if active:
                row, received, total = att_svc.record_media(active, media_b64, media_mime)
                if att_svc.is_complete(active.id):
                    active.status = __import__("app.models.task", fromlist=["TaskStatus"]).TaskStatus.done
                    from datetime import datetime as _dt, timezone as _tz
                    active.completed_at = _dt.now(_tz.utc)
                    db.commit()
                    send_whatsapp(employee.whatsapp_number,
                        _t(f"🎉 All {total} photos received for \"{active.title}\". Marked done!", lang))
                    att_svc.forward_completed(active)
                else:
                    nxt = att_svc.remaining_items(active.id)[0]
                    send_whatsapp(employee.whatsapp_number,
                        _t(f"✅ Got \"{row.item_label}\" ({received}/{total}). Next: {nxt}", lang))
                return {"status": "ok", "intent": "CHECKLIST_PHOTO"}
```
(Keep the existing `_emp_for_error = employee` line.)

- [ ] **Step 4: Block `done` when checklist incomplete**

In `_handle_task_done` (`:548`), at the very top after `task_num = extract_task_number(body)`:
```python
    from app.services.attachment_service import AttachmentService
    att_svc = AttachmentService(employee_task_db(task_mgr))
    active = att_svc.find_active_checklist_task(employee.id)
    if active and not has_attachment:
        remaining = att_svc.remaining_items(active.id)
        if remaining:
            send_whatsapp(employee.whatsapp_number,
                _t("⚠️ Still need photos for: " + ", ".join(remaining) +
                   ".\nSend them one at a time.", lang))
            return
```
Add a tiny helper near the other module helpers in `webhook.py` so the service uses the request session that `task_mgr` already holds:
```python
def employee_task_db(task_mgr):
    """The SQLAlchemy session behind a TaskManager (kept private elsewhere)."""
    return task_mgr.db
```

- [ ] **Step 5: Smoke-check import + compile**

Run: `cd backend && python -m py_compile app/routers/webhook.py && python -c "import app.routers.webhook; print('ok')"`
Expected: `ok`.

- [ ] **Step 6: Manual webhook trace (no automated test — needs live session shapes)**

Document in PR notes: send a checklist SOP task to a test number, send N photos one at a time, confirm acks `Got "<item>" (k/N)`, confirm completion message + admin receives summary + N images.

- [ ] **Step 7: Commit (optional)**
```bash
git add backend/app/routers/webhook.py
git commit -m "feat: webhook collects checklist photos + blocks premature done"
```

---

### Task 7: SOP router response passthrough

**Files:**
- Modify: `backend/app/routers/sops.py:34-60` (list) and `:71-89` (get)

**Interfaces:**
- Produces: `attachment_checklist` present in `GET /api/sops` and `GET /api/sops/{id}` JSON so the frontend can render/edit it.

- [ ] **Step 1: Add the field to both responses**

In `list_sops`, add to the per-SOP dict:
```python
            "attachment_checklist": s.attachment_checklist,
```
In `get_sop`, add to the returned dict:
```python
        "attachment_checklist": sop.attachment_checklist,
```

- [ ] **Step 2: Verify**

Run: `cd backend && python -m py_compile app/routers/sops.py && echo ok`
Expected: `ok`.

- [ ] **Step 3: Commit (optional)**
```bash
git add backend/app/routers/sops.py
git commit -m "feat: expose attachment_checklist in SOP API responses"
```

---

### Task 8: Frontend SOP checklist editor

**Files:**
- Modify: `frontend/src/pages/SOPManage.tsx`

**Interfaces:**
- Consumes: `attachment_checklist` from the SOP API (Task 7). Sends it back as a JSON string on save (matches the `Text` column / `get_checklist` parser).

- [ ] **Step 1: Add `attachment_checklist` to the `SOP` interface**
```typescript
  attachment_checklist: string | null
```

- [ ] **Step 2: Seed form state in `openCreate` and `openEdit`**

In `openCreate`'s `setForm({...})` add:
```typescript
      attachment_checklist: [] as string[],
```
In `openEdit`'s `setForm({...})` add (parse the stored JSON string to an array):
```typescript
      attachment_checklist: (() => {
        try { const a = JSON.parse(sop.attachment_checklist || '[]'); return Array.isArray(a) ? a : [] }
        catch { return [] }
      })(),
```

- [ ] **Step 3: Serialize on save**

In `save()`, after the existing null-coercions, add:
```typescript
      // Checklist: drop blanks; send JSON string or null when empty.
      const items = (payload.attachment_checklist || [])
        .map((s: string) => (s || '').trim()).filter(Boolean)
      payload.attachment_checklist = items.length ? JSON.stringify(items) : null
```

- [ ] **Step 4: Add the editor UI**

After the "Requires photo attachment" checkbox block (before the Cancel/Create buttons), insert:
```tsx
              <div>
                <label className="text-sm font-medium text-gray-700">Photo checklist (one per item)</label>
                <p className="text-xs text-gray-400 mb-1">Staff must send a photo for each item, in order. Leave empty for a single optional photo.</p>
                {(form.attachment_checklist || []).map((item: string, i: number) => (
                  <div key={i} className="flex gap-2 mb-1">
                    <input value={item}
                      onChange={e => setForm((f: any) => {
                        const arr = [...(f.attachment_checklist || [])]; arr[i] = e.target.value
                        return { ...f, attachment_checklist: arr }
                      })}
                      placeholder={`Item ${i + 1} (e.g. Cold Room)`}
                      className="flex-1 border rounded-lg p-2 text-sm" />
                    <button type="button"
                      onClick={() => setForm((f: any) => ({
                        ...f, attachment_checklist: (f.attachment_checklist || []).filter((_: string, j: number) => j !== i)
                      }))}
                      className="px-2 text-red-500 hover:bg-red-50 rounded">✕</button>
                  </div>
                ))}
                <button type="button"
                  onClick={() => setForm((f: any) => ({ ...f, attachment_checklist: [...(f.attachment_checklist || []), ''] }))}
                  className="text-sm text-indigo-600 hover:underline mt-1">+ Add checklist item</button>
              </div>
```

- [ ] **Step 5: Typecheck (if node_modules present)**

Run: `cd frontend && npm i && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 6: Commit (optional)**
```bash
git add frontend/src/pages/SOPManage.tsx
git commit -m "feat: SOP form attachment checklist editor"
```

---

## Self-Review

**Spec coverage:**
- Named checklist on SOP → Tasks 1, 3, 7, 8. ✓
- Sequential collection → Tasks 2, 6. ✓
- Block completion until all received → Task 6 step 4. ✓
- Transient storage + null after forward → Task 5 `forward_completed`. ✓
- Forward to assigner/SOP admin → Task 5. ✓
- Retry on failure → Task 5 `retry_unforwarded` + scheduler hook. ✓
- Legacy single-photo path unchanged → checklist branch only fires when `find_active_checklist_task` returns non-None. ✓
- Migration idempotent → Task 1 step 4 guards on column presence. ✓

**Placeholder scan:** No TBD/TODO; every code step shows full code.

**Type consistency:** `get_checklist`, `create_checklist_rows`, `record_media (row, received, total)`, `find_active_checklist_task`, `forward_completed(bool)`, `retry_unforwarded(int)`, `send_whatsapp_media_base64(to, caption, b64, mimetype)` used consistently across Tasks 2/3/5/6.

**Note on `__import__` in Task 6 step 3:** uses `app.models.task.TaskStatus`. If preferred, add `from app.models.task import TaskStatus` to webhook imports and use `TaskStatus.done` directly — functionally identical; the executing agent may simplify.
