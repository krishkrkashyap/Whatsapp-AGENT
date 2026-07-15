"""Multi-attachment checklist state machine for SOP-generated tasks."""
import json
import logging
from datetime import datetime, timezone
from sqlalchemy import select
from app.models.task import Task, TaskStatus
from app.models.task_attachment import TaskAttachment
from app.services.whatsapp import send_whatsapp, send_whatsapp_attachment
from app.services.whatsapp import _default_filename, _MIME_EXT
from app.services.employee_svc import EmployeeService

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
        """Fill the lowest-index pending row. Returns (row, received_count, total).
        Raises ValueError if there are no pending items (caller should gate on
        find_active_checklist_task / is_complete first)."""
        pending = self.pending_rows(task.id)
        if not pending:
            raise ValueError(f"No pending checklist items for task {task.id}")
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

        all_received = self.received_rows(task.id)
        rows = [r for r in all_received if r.forwarded_at is None]
        if not rows:
            return True

        # Send the summary only on the FIRST forward attempt (no row forwarded
        # yet). A partial-failure retry must not re-send the summary to the admin.
        first_attempt = all(r.forwarded_at is None for r in all_received)
        if first_attempt:
            station = f"{getattr(worker, 'department', '?')}/{getattr(worker, 'role', '?')}" if worker else "?"
            worker_name = getattr(worker, "name", "Unknown") if worker else "Unknown"
            done_time = (task.completed_at or datetime.now(timezone.utc)).strftime("%d %b %H:%M")
            lines = [f"✅ *SOP Completed:* {task.title}",
                     f"👤 {worker_name}  ·  🏢 {station}",
                     f"🕒 {done_time}", "", "*Items:*"]
            for r in all_received:
                t = r.received_at.strftime("%H:%M") if r.received_at else "—"
                lines.append(f"✓ {r.item_label} — {t}")
            send_whatsapp(assigner.whatsapp_number, "\n".join(lines))

        all_ok = True
        for r in rows:
            # Route by type: photos as images, xlsx/pdf/docs as documents.
            mime = r.media_mimetype or "image/jpeg"
            ext = _MIME_EXT.get((mime or "").split(";")[0].strip())
            fname = f"{r.item_label}.{ext}" if ext else None
            mid = send_whatsapp_attachment(
                assigner.whatsapp_number, f"📎 {task.title}: {r.item_label}",
                r.media_base64 or "", mime, fname)
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
