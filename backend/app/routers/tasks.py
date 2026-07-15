"""Tasks router — BUG-5 fix (all statuses), F-3 (dashboard assign), F-5 (history), F-18 (bulk)."""
import logging
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone
from app.database import get_db
from app.services.task_manager import TaskManager
from app.services.audit import AuditService
from app.services.employee_svc import EmployeeService
from app.services.whatsapp import send_whatsapp
from app.routers.auth import verify_token
from app.models.task import TaskStatus, Task, Priority
from app.schemas.task import TaskUpdate
from sqlalchemy import select, func
import io
import csv

logger = logging.getLogger("tasks")
router = APIRouter()

@router.get("/")
def list_tasks(status: str = None, db=Depends(get_db), _user=Depends(verify_token)):
    """BUG-5 + SEC-1 fix: Returns all tasks with optional status filter. Now requires auth."""
    mgr = TaskManager(db)
    if status:
        tasks = mgr.get_all_tasks(status=status)
    else:
        tasks = mgr.get_all_tasks()
    return [{"id": t.id, "title": t.title, "status": t.status.value,
             "priority": t.priority.value, "assigned_to_id": t.assigned_to_id,
             "assigned_by_id": t.assigned_by_id,
             "due_date": str(t.due_date) if t.due_date else None,
             "completed_at": str(t.completed_at) if t.completed_at else None,
             "attachment_url": t.attachment_url,
             "bulk_group_id": t.bulk_group_id,
             "created_at": str(t.assigned_at),
             "description": t.description,
             "requires_attachment": t.requires_attachment,
             "sla_enabled": t.sla_enabled} for t in tasks]

@router.get("/pending")
def list_pending_tasks(db=Depends(get_db), _user=Depends(verify_token)):
    mgr = TaskManager(db)
    tasks = mgr.get_all_pending()
    return [{"id": t.id, "title": t.title, "status": t.status.value,
             "priority": t.priority.value, "assigned_to_id": t.assigned_to_id,
             "due_date": str(t.due_date) if t.due_date else None,
             "created_at": str(t.assigned_at),
             "description": t.description,
             "requires_attachment": t.requires_attachment,
             "sla_enabled": t.sla_enabled} for t in tasks]

@router.get("/count")
def task_count(db=Depends(get_db), _user=Depends(verify_token)):
    mgr = TaskManager(db)
    tasks = mgr.get_all_pending()
    return {"count": len(tasks)}


@router.get("/stats")
def task_stats(db=Depends(get_db), _user=Depends(verify_token)):
    """Whole-DB task counts by status — the stat cards must not count only the
    latest 100 loaded rows (which made Completed show 0)."""
    rows = db.execute(select(Task.status, func.count()).group_by(Task.status)).all()
    by = {s.value: n for s, n in rows}
    return {
        "open": by.get("pending", 0) + by.get("in_progress", 0),
        "done": by.get("done", 0),
        "escalated": by.get("escalated", 0),
        "missed": by.get("missed", 0),
        "blocked": by.get("blocked", 0),
        "total": sum(by.values()),
    }

@router.get("/employee/{employee_id}")
def employee_tasks(employee_id: str, db=Depends(get_db), _user=Depends(verify_token)):
    mgr = TaskManager(db)
    tasks = mgr.get_pending_tasks(employee_id)
    return [{"id": t.id, "title": t.title, "status": t.status.value,
             "priority": t.priority.value, "due_date": str(t.due_date) if t.due_date else None,
             "description": t.description,
             "requires_attachment": t.requires_attachment,
             "sla_enabled": t.sla_enabled}
            for t in tasks]

# F-3: Assign tasks from Dashboard
class DashboardTaskAssign(BaseModel):
    title: str
    description: Optional[str] = None
    priority: str = "medium"
    assigned_to_id: str
    assigned_by_id: str
    due_date: Optional[str] = None
    follow_up_type: str = "none"
    follow_up_interval_hours: Optional[float] = None
    requires_attachment: bool = False
    sla_enabled: bool = True

@router.post("/assign")
def assign_task_from_dashboard(req: DashboardTaskAssign, db=Depends(get_db), _user=Depends(verify_token)):
    """F-3: Assign task from admin dashboard."""
    try:
        mgr = TaskManager(db)
        due = None
        if req.due_date:
            try:
                due = datetime.fromisoformat(req.due_date.replace("Z", "+00:00"))
            except Exception:
                pass

        task = mgr.assign(
            admin_id=req.assigned_by_id,
            target_id=req.assigned_to_id,
            title=req.title,
            priority=req.priority,
            due_date=due,
            description=req.description,
            follow_up_type=req.follow_up_type,
            interval_hours=req.follow_up_interval_hours,
            requires_attachment=req.requires_attachment,
            sla_enabled=req.sla_enabled,
        )

        # Notify the employee via WhatsApp (non-blocking — log failure, dont crash)
        try:
            emp_svc = EmployeeService(db)
            target = emp_svc.get_by_id(req.assigned_to_id)
            assigner = emp_svc.get_by_id(req.assigned_by_id)
            if target:
                follow_up_note = ""
                if req.follow_up_type == "periodic" and req.follow_up_interval_hours:
                    mins = int(req.follow_up_interval_hours * 60)
                    follow_up_note = f"\n🔄 Follow-up: every {mins} minutes"
                send_whatsapp(target.whatsapp_number,
                    f"📋 *New Task Assigned (via Dashboard)*\n\n"
                    f"From: {assigner.name if assigner else 'Admin'}\n"
                    f"Task: {task.title}\n"
                    f"Priority: {task.priority.value.upper()}"
                    f"{follow_up_note}\n\n"
                    f"Reply 'done' when complete.")
        except Exception as wa_err:
            logger.warning(f"WhatApp notify failed for task {task.id}: {wa_err}")

        AuditService(db).log(
            action="task.assign", resource_type="task", resource_id=task.id,
            actor_name=_user, details={"title": task.title, "assigned_to": req.assigned_to_id}
        )

        return {"id": task.id, "title": task.title, "status": task.status.value, "sla_enabled": task.sla_enabled}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Task assign failed: {e}")
        raise HTTPException(500, f"Failed to assign task: {str(e)}")

class TaskStatusUpdate(BaseModel):
    status: str  # pending / in_progress / done / blocked / escalated

@router.put("/{task_id}/status")
def update_task_status(task_id: str, req: TaskStatusUpdate, db=Depends(get_db), _user=Depends(verify_token)):
    """F-NEW: Admin changes task status from frontend. Notifies assigned employee via WhatsApp."""
    try:
        mgr = TaskManager(db)
        task = mgr.get_task_by_id(task_id)
        if not task:
            raise HTTPException(404, "Task not found")

        old_status = task.status.value
        new_status = req.status
        if new_status not in ("pending", "in_progress", "done", "blocked", "escalated"):
            raise HTTPException(400, f"Invalid status: {new_status}")

        task.status = TaskStatus(new_status)
        if new_status == "done":
            task.completed_at = datetime.now(timezone.utc)
        db.commit()

        # Notify via WhatsApp (non-blocking)
        try:
            emp_svc = EmployeeService(db)
            target = emp_svc.get_by_id(task.assigned_to_id)
            if target:
                status_emoji = {"pending": "📋", "in_progress": "🔄", "done": "✅", "blocked": "🚫", "escalated": "⚠️"}
                emoji = status_emoji.get(new_status, "📋")
                send_whatsapp(target.whatsapp_number,
                    f"{emoji} *Task Status Updated:* \"{task.title}\"\n"
                    f"Status: {old_status} → {new_status.upper()}\n"
                    f"Updated by: {_user}")
        except Exception as wa_err:
            logger.warning(f"WhatsApp notify failed for status change on task {task_id}: {wa_err}")

        AuditService(db).log(
            action="task.update_status", resource_type="task", resource_id=task_id,
            actor_name=_user, details={"old_status": old_status, "new_status": new_status}
        )

        return {"id": task.id, "title": task.title, "status": task.status.value}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Task status update failed for {task_id}: {e}")
        raise HTTPException(500, f"Failed to update status: {str(e)}")

@router.put("/{task_id}")
def update_task(task_id: str, req: TaskUpdate, db=Depends(get_db), _user=Depends(verify_token)):
    """Update any task fields. Admin can edit all fields. Assigned employee can only change status."""
    try:
        mgr = TaskManager(db)
        task = mgr.get_task_by_id(task_id)
        if not task:
            raise HTTPException(404, "Task not found")

        # Build update dict from non-None fields
        updates = {}
        change_summary = []

        # Track old values for notification
        old_values = {
            "title": task.title,
            "status": task.status.value,
            "priority": task.priority.value,
            "due_date": str(task.due_date.date()) if task.due_date else None,
            "description": task.description,
            "assigned_to_id": task.assigned_to_id,
            "requires_attachment": task.requires_attachment,
        }

        if req.title is not None and req.title != task.title:
            updates["title"] = req.title
            change_summary.append(f"Title: {old_values['title']} → {req.title}")
        if req.description is not None and req.description != task.description:
            updates["description"] = req.description
            change_summary.append(f"Description updated")
        if req.status is not None and req.status != task.status.value:
            if req.status not in ("pending", "in_progress", "done", "blocked", "escalated"):
                raise HTTPException(400, f"Invalid status: {req.status}")
            updates["status"] = req.status
            change_summary.append(f"Status: {old_values['status']} → {req.status}")
        if req.priority is not None and req.priority != task.priority.value:
            if req.priority not in ("high", "medium", "low"):
                raise HTTPException(400, f"Invalid priority: {req.priority}")
            updates["priority"] = req.priority
            change_summary.append(f"Priority: {old_values['priority']} → {req.priority}")
        if req.assigned_to_id is not None and req.assigned_to_id != task.assigned_to_id:
            updates["assigned_to_id"] = req.assigned_to_id
            change_summary.append(f"Assignee changed")
        if req.requires_attachment is not None and req.requires_attachment != task.requires_attachment:
            updates["requires_attachment"] = req.requires_attachment
            change_summary.append(f"Attachment proof: {'ON' if req.requires_attachment else 'OFF'}")
        if req.sla_enabled is not None and req.sla_enabled != task.sla_enabled:
            updates["sla_enabled"] = req.sla_enabled
            change_summary.append(f"SLA: {'ON' if req.sla_enabled else 'OFF'}")
        if req.clear_due_date:
            updates["_clear_due_date"] = True
            change_summary.append(f"Due date: {old_values['due_date'] or 'none'} → cleared")
        elif req.due_date is not None:
            # Compare by date only
            new_due_str = str(req.due_date.date())
            if new_due_str != old_values["due_date"]:
                updates["due_date"] = req.due_date
                change_summary.append(f"Due date: {old_values['due_date'] or 'none'} → {new_due_str}")

        if not updates:
            return {"id": task.id, "title": task.title, "message": "No changes"}

        # If completed_at should be set/cleared based on status
        if updates.get("status") == "done":
            task.completed_at = datetime.now(timezone.utc)
        elif updates.get("status") and updates["status"] != "done" and task.completed_at:
            task.completed_at = None

        updated = mgr.update_task(task_id, updates)
        if not updated:
            raise HTTPException(500, "Failed to update task")

        # Notify assigned employee via WhatsApp (non-blocking)
        try:
            emp_svc = EmployeeService(db)
            target = emp_svc.get_by_id(updated.assigned_to_id)
            if target:
                changes_str = "\n".join(change_summary) if change_summary else "Fields updated"
                send_whatsapp(target.whatsapp_number,
                    f"📝 *Task Updated:* \"{updated.title}\"\n"
                    f"By: {_user}\n\n"
                    f"{changes_str}")
        except Exception as wa_err:
            logger.warning(f"WhatsApp notify failed for task update {task_id}: {wa_err}")

        AuditService(db).log(
            action="task.update", resource_type="task", resource_id=task_id,
            actor_name=_user, details={"updates": list(updates.keys())}
        )

        return {"id": updated.id, "title": updated.title, "status": updated.status.value,
                "priority": updated.priority.value, "sla_enabled": updated.sla_enabled, "message": "Updated"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Task update failed for {task_id}: {e}")
        raise HTTPException(500, f"Failed to update task: {str(e)}")

# F-18: Bulk assign
class BulkAssignRequest(BaseModel):
    title: str
    description: Optional[str] = None
    priority: str = "medium"
    assigned_by_id: str
    assigned_to_ids: List[str]
    due_date: Optional[str] = None
    requires_attachment: bool = False

@router.post("/bulk-assign")
def bulk_assign(req: BulkAssignRequest, db=Depends(get_db), _user=Depends(verify_token)):
    """F-18: Assign the same task to multiple employees."""
    try:
        mgr = TaskManager(db)
        due = None
        if req.due_date:
            try:
                due = datetime.fromisoformat(req.due_date.replace("Z", "+00:00"))
            except Exception:
                pass

        tasks, group_id = mgr.bulk_assign(
            admin_id=req.assigned_by_id,
            target_ids=req.assigned_to_ids,
            title=req.title,
            priority=req.priority,
            due_date=due,
            description=req.description,
        )
        # Update bulk tasks with attachment requirement
        if req.requires_attachment:
            for t in tasks:
                t.requires_attachment = True
            db.commit()

        # Notify each employee (non-blocking)
        emp_svc = EmployeeService(db)
        assigner = emp_svc.get_by_id(req.assigned_by_id)
        for task in tasks:
            try:
                target = emp_svc.get_by_id(task.assigned_to_id)
                if target:
                    send_whatsapp(target.whatsapp_number,
                        f"📋 *New Task (Bulk Assigned)*\n\n"
                        f"From: {assigner.name if assigner else 'Admin'}\n"
                        f"Task: {task.title}\n"
                        f"Priority: {task.priority.value.upper()}\n\n"
                        f"Reply 'done' when complete.")
            except Exception as wa_err:
                logger.warning(f"WhatsApp notify failed for bulk task {task.id}: {wa_err}")

        AuditService(db).log(
            action="task.bulk_assign", resource_type="task",
            actor_name=_user, details={"title": req.title, "count": len(tasks), "group_id": group_id}
        )

        return {"status": "success", "assigned": len(tasks), "group_id": group_id}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Bulk assign failed: {e}")
        raise HTTPException(500, f"Failed to bulk assign: {str(e)}")

@router.get("/export")
def export_tasks(db=Depends(get_db), _user=Depends(verify_token)):
    """SEC-1 fix: Task CSV export now requires auth."""
    from sqlalchemy import select
    from app.models.task import Task
    tasks = list(db.execute(select(Task)).scalars().all())

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Title", "Status", "Priority", "Assigned To", "Due Date", "Created At", "Completed At"])
    for t in tasks:
        writer.writerow([t.id, t.title, t.status.value, t.priority.value, t.assigned_to_id,
                         str(t.due_date) if t.due_date else "", str(t.assigned_at),
                         str(t.completed_at) if t.completed_at else ""])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=tasks_export.csv"}
    )
