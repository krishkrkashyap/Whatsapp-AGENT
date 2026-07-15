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
    assert row3.item_label == "Side Wall"
    assert (received3, total3) == (3, 3)
    assert svc.is_complete(task.id) is True
    assert svc.remaining_items(task.id) == []


def test_find_active_checklist_task(db, make_task):
    plain = make_task(None)            # no checklist
    cl = make_task(json.dumps(ITEMS))  # checklist task
    svc = AttachmentService(db)
    svc.create_checklist_rows(cl.id, ITEMS)
    found = svc.find_active_checklist_task("emp1")
    assert found is not None and found.id == cl.id and found.id != plain.id


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


def test_record_media_raises_when_no_pending(db, make_task):
    import pytest
    task = make_task(json.dumps(["Only"]))
    svc = AttachmentService(db)
    svc.create_checklist_rows(task.id, ["Only"])
    svc.record_media(task, "X", "image/jpeg")  # fills the only item
    with pytest.raises(ValueError):
        svc.record_media(task, "Y", "image/jpeg")  # nothing left


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


def test_partial_retry_does_not_resend_summary(db, make_task, monkeypatch):
    import json
    from app.services import attachment_service as mod
    task = make_task(json.dumps(["Floor", "Wall"]))
    svc = mod.AttachmentService(db)
    svc.create_checklist_rows(task.id, ["Floor", "Wall"])
    svc.record_media(task, "B64A", "image/jpeg")
    svc.record_media(task, "B64B", "image/jpeg")

    sent_text = []
    monkeypatch.setattr(mod, "send_whatsapp", lambda to, body: sent_text.append(body) or "id")
    class Emp: whatsapp_number = "+91999"; name = "Boss"; department = "Ops"; role = "Mgr"
    monkeypatch.setattr(mod.AttachmentService, "_assigner_and_worker",
                        lambda self, t: (Emp(), Emp()))

    # First attempt: second photo fails -> summary sent once, one row forwarded.
    calls = {"n": 0}
    def flaky(to, cap, b64, mt="image/jpeg"):
        calls["n"] += 1
        return "id" if calls["n"] == 1 else "error"
    monkeypatch.setattr(mod, "send_whatsapp_media_base64", flaky)
    assert svc.forward_completed(task) is False
    assert len(sent_text) == 1  # summary sent exactly once

    # Retry: remaining photo now succeeds -> NO new summary, row forwarded.
    monkeypatch.setattr(mod, "send_whatsapp_media_base64", lambda *a, **k: "id")
    assert svc.forward_completed(task) is True
    assert len(sent_text) == 1  # still only the original summary
    assert all(r.forwarded_at is not None and r.media_base64 is None
               for r in svc.received_rows(task.id))
