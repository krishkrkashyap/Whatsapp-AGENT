import json
from app.services.attachment_service import AttachmentService
from app.services.sop_service import SOPService
from app.models.task_attachment import TaskAttachment


def test_normalize_checklist():
    n = SOPService._normalize_checklist
    # Python list (API/import callers) -> canonical JSON string
    assert n(["Floor", " Cold Room ", ""]) == json.dumps(["Floor", "Cold Room"])
    # already-JSON string (frontend) -> re-canonicalized, blanks dropped
    assert n('["Floor", "Wall"]') == json.dumps(["Floor", "Wall"])
    # empties / garbage / non-list -> None
    assert n(None) is None
    assert n("") is None
    assert n("not json") is None
    assert n("{\"a\",\"b\"}") is None  # postgres-array literal, not valid JSON
    assert n([]) is None
    assert n(123) is None
    # round-trips through AttachmentService.get_checklist

    class _T:
        attachment_checklist = n(["Floor", "Wall"])
    assert AttachmentService(None).get_checklist(_T()) == ["Floor", "Wall"]


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
