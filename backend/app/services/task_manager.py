"""Task Manager service — F-1 task selector, F-18 bulk assignment."""
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, update
from app.models.task import Task, FollowUp, Priority, TaskStatus, FollowUpType
from app.models.conversation import ConversationLog, Direction, MessageType
from app.models.employee import Employee
from app.services.employee_svc import EmployeeService
from app.services.whatsapp import send_whatsapp
import uuid
import logging

logger = logging.getLogger("task_manager")

class TaskManager:
    def __init__(self, db):
        self.db = db
        self.emp_svc = EmployeeService(db)

    def assign(
        self,
        admin_id: str,
        target_id: str,
        title: str,
        priority: str = "medium",
        due_date=None,
        follow_up_type: str = "none",
        interval_hours=None,
        description=None,
        attachment_url=None,
        bulk_group_id=None,
        requires_attachment: bool = False,
        sla_enabled: bool = True,
    ):
        follow_up_type = follow_up_type or "none"
        task = Task(
            title=title,
            description=description,
            priority=Priority(priority),
            status=TaskStatus.pending,
            assigned_by_id=admin_id,
            assigned_to_id=target_id,
            due_date=due_date,
            assigned_at=datetime.now(timezone.utc),
            follow_up_type=FollowUpType(follow_up_type),
            follow_up_interval_hours=interval_hours,
            attachment_url=attachment_url,
            bulk_group_id=bulk_group_id,
            requires_attachment=requires_attachment,
            sla_enabled=sla_enabled,
        )
        self.db.add(task)
        self.db.flush()

        if follow_up_type != "none":
            trigger = due_date or datetime.now(timezone.utc) + timedelta(hours=interval_hours or 24)
            fu = FollowUp(
                task_id=task.id,
                type=FollowUpType(follow_up_type),
                next_trigger_at=trigger,
                interval_hours=interval_hours,
            )
            self.db.add(fu)

        self.db.commit()
        self.db.refresh(task)
        return task

    def bulk_assign(self, admin_id: str, target_ids: list, title: str,
                    priority: str = "medium", due_date=None, description=None):
        """F-18: Assign the same task to multiple employees at once."""
        group_id = str(uuid.uuid4())
        tasks = []
        for tid in target_ids:
            task = self.assign(
                admin_id=admin_id,
                target_id=tid,
                title=title,
                priority=priority,
                due_date=due_date,
                description=description,
                bulk_group_id=group_id,
            )
            tasks.append(task)
        return tasks, group_id

    def mark_done(self, employee_id: str, task_id: str = None, task_number: int = None, has_attachment: bool = False):
        """F-1: Enhanced done — supports task_id, numbered selection, or latest. Also checks attachments."""
        task = None
        if task_number is not None:
            # Get employee's pending tasks ordered, pick by number
            pending = self.get_pending_tasks(employee_id)
            if 1 <= task_number <= len(pending):
                task = pending[task_number - 1]
        else:
            query = select(Task).where(
                Task.assigned_to_id == employee_id,
                Task.status.in_([TaskStatus.pending, TaskStatus.in_progress]),
            )
            if task_id:
                query = query.where(Task.id == task_id)
            query = query.order_by(Task.assigned_at.asc()).limit(1)  # BUG-C4 fix: oldest first, not newest

            result = self.db.execute(query)
            task = result.scalar_one_or_none()

        if not task:
            return None, "Not found"

        if task.requires_attachment and not has_attachment:
            return task, "Missing attachment"

        task.status = TaskStatus.done
        task.completed_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(task)
        return task, "Success"

    def get_pending_tasks(self, employee_id: str):
        result = self.db.execute(
            select(Task)
            .where(
                Task.assigned_to_id == employee_id,
                Task.status.in_([TaskStatus.pending, TaskStatus.in_progress]),
            )
            # assigned_at is a stable tiebreaker so numbering ("done 2") doesn't
            # shift between the prompt and the confirmation when priority/due
            # are equal.
            .order_by(Task.priority, Task.due_date, Task.assigned_at)
        )
        return list(result.scalars().all())

    def get_recent_tasks(self, employee_id: str, limit: int = 5):
        """Most recent tasks for an employee regardless of status.

        Used to route an escalation to the right task's assigner even after
        the task is marked done/escalated (when get_pending_tasks is empty),
        so the alert still reaches the assigner instead of every admin.
        """
        result = self.db.execute(
            select(Task)
            .where(Task.assigned_to_id == employee_id)
            .order_by(Task.assigned_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    def get_all_pending(self):
        result = self.db.execute(
            select(Task)
            .where(Task.status.in_([TaskStatus.pending, TaskStatus.in_progress]))
            .order_by(Task.priority, Task.due_date, Task.assigned_at)
        )
        return list(result.scalars().all())

    def get_all_tasks(self, status: str = None, limit: int = 100):
        """F-5: Get all tasks with optional status filter (for task history)."""
        query = select(Task)
        if status:
            query = query.where(Task.status == TaskStatus(status))
        query = query.order_by(Task.assigned_at.desc()).limit(limit)
        result = self.db.execute(query)
        return list(result.scalars().all())

    def get_task_by_id(self, task_id: str):
        result = self.db.execute(select(Task).where(Task.id == task_id))
        return result.scalar_one_or_none()

    def update_task(self, task_id: str, updates: dict) -> Task | None:
        """Update task fields. `updates` dict keys match Task model column names.
        Supports special key `_clear_due_date` to set due_date to None."""
        task = self.get_task_by_id(task_id)
        if not task:
            return None

        if "_clear_due_date" in updates:
            task.due_date = None
            del updates["_clear_due_date"]

        # Map common field names to model columns
        field_map = {
            "title": "title",
            "description": "description",
            "status": "status",
            "priority": "priority",
            "due_date": "due_date",
            "assigned_to_id": "assigned_to_id",
            "requires_attachment": "requires_attachment",
            "sla_enabled": "sla_enabled",
        }
        for key, value in updates.items():
            col = field_map.get(key)
            if col is not None and value is not None:
                if col == "status":
                    setattr(task, col, TaskStatus(value))
                elif col == "priority":
                    setattr(task, col, Priority(value))
                else:
                    setattr(task, col, value)

        self.db.commit()
        self.db.refresh(task)
        return task

    def log_conversation(self, employee_id: str, text: str, direction, msg_type, task_id=None, language=None):
        log = ConversationLog(
            task_id=task_id,
            employee_id=employee_id,
            message_text=text,
            direction=direction,
            message_type=msg_type,
            language=language,
        )
        self.db.add(log)
        self.db.commit()
