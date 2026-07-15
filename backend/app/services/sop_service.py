"""SOP Service — manages SOP definitions and their scheduled execution."""
import logging
from datetime import datetime, timezone, date, timedelta
from sqlalchemy import select, and_, text
from app.models.sop import SOPDefinition, SOPExecution, SOPStatus, Frequency
from app.models.task import Task, TaskStatus, Priority, FollowUp, FollowUpType
from app.models.employee import Employee
from app.services.whatsapp import send_whatsapp
from app.services.employee_svc import EmployeeService
from app.database import get_db_context

logger = logging.getLogger("sop_service")


class SOPService:
    def __init__(self, db):
        self.db = db
        self.emp_svc = EmployeeService(db)

    # ── CRUD ────────────────────────────────────────────────────────────────

    @staticmethod
    def _normalize_checklist(v):
        """Coerce a checklist value to the canonical JSON-array STRING the
        TEXT column stores (and AttachmentService.get_checklist parses).

        Accepts a Python list (API/import callers) OR an already-JSON string
        (frontend). Anything else, or an empty result, becomes None. This
        prevents a raw list from being adapted by psycopg2 into a Postgres
        array literal (`{a,b}`) that get_checklist cannot parse."""
        import json
        if v is None or v == "":
            return None
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
            except Exception:
                return None
            v = parsed
        if isinstance(v, (list, tuple)):
            items = [str(x).strip() for x in v if str(x).strip()]
            return json.dumps(items) if items else None
        return None

    def create(self, data: dict) -> SOPDefinition:
        freq = Frequency(data.get("frequency", "daily"))
        interval = data.get("interval_hours")
        # Hourly SOPs are driven by interval_hours; default to every 1h when the
        # admin didn't specify a step.
        if freq == Frequency.hourly and not interval:
            interval = 1.0
        sop = SOPDefinition(
            title=data["title"],
            description=data.get("description"),
            department=data["department"],
            frequency=freq,
            days_of_week=data.get("days_of_week"),
            day_of_month=data.get("day_of_month"),
            start_time=data["start_time"],
            end_time=data.get("end_time"),
            interval_hours=interval,
            assigned_to_id=data["assigned_to_id"],
            admin_id=data.get("admin_id"),
            requires_attachment=data.get("requires_attachment", False),
            attachment_checklist=self._normalize_checklist(data.get("attachment_checklist")),
            notify_before_min=data.get("notify_before_min", 5),
            notify_after_min=data.get("notify_after_min", 5),
            admin_notify_after_min=data.get("admin_notify_after_min", 15),
            priority=data.get("priority", "medium"),
        )
        self.db.add(sop)
        self.db.commit()
        self.db.refresh(sop)
        return sop

    def update(self, sop_id: str, data: dict) -> SOPDefinition | None:
        sop = self.db.execute(select(SOPDefinition).where(SOPDefinition.id == sop_id))
        sop = sop.scalar_one_or_none()
        if not sop:
            return None

        for field in ["title", "description", "department", "frequency", "days_of_week",
                       "day_of_month", "start_time", "end_time", "interval_hours",
                       "assigned_to_id", "admin_id",
                       "requires_attachment", "notify_before_min", "notify_after_min",
                       "admin_notify_after_min", "priority", "status", "attachment_checklist",
                       "paused_until"]:
            if field in data:
                if field == "frequency":
                    setattr(sop, field, Frequency(data[field]))
                elif field == "status":
                    from app.models.sop import SOPStatus
                    setattr(sop, field, SOPStatus(data[field]))
                elif field == "attachment_checklist":
                    setattr(sop, field, self._normalize_checklist(data[field]))
                elif field == "paused_until":
                    setattr(sop, field, self._parse_dt(data[field]))
                else:
                    setattr(sop, field, data[field])

        # Resuming clears any pending auto-resume timestamp.
        if sop.status == SOPStatus.active:
            sop.paused_until = None

        # Hourly without a step → default every 1h (mirrors create()).
        if sop.frequency == Frequency.hourly and not sop.interval_hours:
            sop.interval_hours = 1.0

        self.db.commit()
        self.db.refresh(sop)
        return sop

    @staticmethod
    def _parse_dt(value):
        """Parse an ISO datetime string (or pass through datetime/None) as a
        timezone-AWARE datetime. A naive value (no tz/Z) is interpreted in the
        app timezone (Asia/Kolkata), not UTC — otherwise a naive IST 'resume at'
        was treated as UTC and auto-resumed ~5.5h off."""
        if not value:
            return None
        dt = value if isinstance(value, datetime) else None
        if dt is None:
            try:
                dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                return None
        if dt.tzinfo is None:
            from app.config import settings
            try:
                from zoneinfo import ZoneInfo
                dt = dt.replace(tzinfo=ZoneInfo(settings.app_timezone))
            except Exception:
                dt = dt.replace(tzinfo=timezone.utc)
        return dt

    def bulk_set_status(self, status: str, paused_until=None,
                        departments=None, sop_ids=None) -> int:
        """Pause/resume many SOPs at once. Match by department list and/or explicit
        ids (union). Resuming clears paused_until. Returns count changed."""
        from app.models.sop import SOPStatus
        new_status = SOPStatus(status)
        conds = []
        if departments:
            conds.append(SOPDefinition.department.in_(list(departments)))
        if sop_ids:
            conds.append(SOPDefinition.id.in_(list(sop_ids)))
        if not conds:
            return 0
        from sqlalchemy import or_
        rows = self.db.execute(
            select(SOPDefinition).where(or_(*conds))
        ).scalars().all()
        pu = self._parse_dt(paused_until) if new_status == SOPStatus.paused else None
        for sop in rows:
            sop.status = new_status
            sop.paused_until = pu
        self.db.commit()
        return len(rows)

    def delete(self, sop_id: str) -> bool:
        sop = self.db.execute(select(SOPDefinition).where(SOPDefinition.id == sop_id))
        sop = sop.scalar_one_or_none()
        if not sop:
            return False
        from sqlalchemy import delete as sa_delete
        # sop_executions FK sop_id with no ondelete — clear children first or the
        # delete raises ForeignKeyViolation. Tasks are left as historical record.
        self.db.execute(sa_delete(SOPExecution).where(SOPExecution.sop_id == sop_id))
        self.db.delete(sop)
        self.db.commit()
        return True

    def get_by_id(self, sop_id: str) -> SOPDefinition | None:
        result = self.db.execute(select(SOPDefinition).where(SOPDefinition.id == sop_id))
        return result.scalar_one_or_none()

    def list_all(self, department: str = None) -> list:
        query = select(SOPDefinition).order_by(SOPDefinition.department, SOPDefinition.start_time)
        if department:
            query = query.where(SOPDefinition.department == department)
        result = self.db.execute(query)
        return list(result.scalars().all())

    def get_departments(self) -> list:
        """Return departments that have active SOPs with counts."""
        sql = text("""
            SELECT s.department, COUNT(*) as count,
                   COUNT(*) FILTER (WHERE s.status = 'active') as active_count
            FROM sop_definitions s
            GROUP BY s.department
            ORDER BY s.department
        """)
        rows = self.db.execute(sql).fetchall()
        return [{"department": r[0], "count": r[1], "active_count": r[2]} for r in rows]

    # ── Execution / Scheduling ─────────────────────────────────────────────

    @staticmethod
    def _should_run_today(sop: SOPDefinition, today: date) -> bool:
        """Check if SOP should trigger today based on its frequency.

        NOTE: no longer gates on last_triggered_date — interval SOPs fire
        multiple times per day, and per-slot duplicate suppression is handled
        by the (sop_id, date, scheduled_time) execution key instead."""
        if sop.status != SOPStatus.active:
            return False

        weekday = today.weekday()  # 0=Mon, 6=Sun

        if sop.frequency == Frequency.daily:
            return True
        elif sop.frequency == Frequency.hourly:
            # Fires every day; the actual fire times come from _trigger_slots,
            # which steps interval_hours from start_time to end_time.
            return True
        elif sop.frequency == Frequency.weekday:
            return weekday < 5  # Mon-Fri
        elif sop.frequency == Frequency.weekly:
            if sop.days_of_week is None:
                return weekday == 0  # Default to Monday
            # Bitmask check: bit 0=Mon(1), 1=Tue(2), 2=Wed(4), 3=Thu(8), 4=Fri(16), 5=Sat(32), 6=Sun(64)
            return bool(sop.days_of_week & (1 << weekday))
        elif sop.frequency == Frequency.monthly:
            if sop.day_of_month is None:
                return False
            return today.day == sop.day_of_month

        return False

    @staticmethod
    def _now_local() -> datetime:
        """Current time in the configured app timezone (SOP times are local)."""
        from app.config import settings
        try:
            from zoneinfo import ZoneInfo
            return datetime.now(ZoneInfo(settings.app_timezone))
        except Exception:
            # Bad/unknown tz name — fall back to UTC rather than crash the loop.
            logger.warning("Invalid app_timezone %r, using UTC", settings.app_timezone)
            return datetime.now(timezone.utc)

    @staticmethod
    def _trigger_slots(sop: SOPDefinition) -> list:
        """All HH:MM fire times for this SOP in a day.
        Single-fire -> [start_time]. Interval -> start, start+N, ... up to
        end_time (or 23:59)."""
        start = sop.start_time
        if not sop.interval_hours or sop.interval_hours <= 0:
            return [start]
        try:
            h, m = map(int, start.split(":"))
        except (ValueError, AttributeError):
            return [start]
        start_min = h * 60 + m
        step = int(round(sop.interval_hours * 60))
        if step <= 0:
            return [start]
        # Upper bound: end_time if a valid HH:MM, else end of day.
        end_min = 23 * 60 + 59
        if sop.end_time:
            try:
                eh, em = map(int, sop.end_time.split(":"))
                end_min = eh * 60 + em
            except ValueError:
                pass
        # Overnight window (end before start, e.g. 22:00 -> 02:00): extend the
        # end past midnight so slots wrap; previously this produced NO slots and
        # the SOP never fired.
        if end_min < start_min:
            end_min += 24 * 60
        slots = []
        t = start_min
        while t <= end_min:
            mins = t % (24 * 60)          # wrap past midnight for the HH:MM label
            slots.append(f"{mins // 60:02d}:{mins % 60:02d}")
            t += step
        return slots

    def _auto_resume_paused(self, now):
        """Reactivate any paused SOP whose paused_until has passed. NULL
        paused_until = indefinite manual pause, left untouched."""
        from datetime import timezone as _tz
        rows = self.db.execute(
            select(SOPDefinition).where(
                SOPDefinition.status == SOPStatus.paused,
                SOPDefinition.paused_until.isnot(None),
            )
        ).scalars().all()
        changed = False
        for sop in rows:
            pu = sop.paused_until
            # Normalize naive timestamps to UTC before comparing to tz-aware now.
            if pu.tzinfo is None:
                pu = pu.replace(tzinfo=_tz.utc)
            if now >= pu:
                sop.status = SOPStatus.active
                sop.paused_until = None
                changed = True
                logger.info("SOP auto-resumed (pause expired): %s", sop.title)
        if changed:
            self.db.commit()

    def check_and_trigger(self):
        """Main scheduler entry — check all active SOPs and trigger if needed.
        Called every 60 seconds by the scheduler. Times are compared in the
        configured app timezone (app_timezone), not UTC."""
        now = self._now_local()
        today = now.date()
        current_time = now.strftime("%H:%M")
        current_min = now.hour * 60 + now.minute

        # Timed auto-resume: reactivate paused SOPs whose pause window has ended.
        self._auto_resume_paused(now)

        result = self.db.execute(
            select(SOPDefinition).where(SOPDefinition.status == SOPStatus.active)
        )
        sops = list(result.scalars().all())

        # Grace window (minutes): the job runs every 60s but a delayed/coalesced
        # run could miss the exact minute. Task creation dedupes on the
        # (sop_id, date, slot) execution key, so firing within a small window is
        # safe and recovers the slot instead of silently dropping it. Bounded so a
        # first run never back-fires the whole day's earlier slots.
        GRACE = 2

        for sop in sops:
            if not self._should_run_today(sop, today):
                continue

            for slot in self._trigger_slots(sop):
                try:
                    sh, sm = map(int, slot.split(":"))
                    slot_min = sh * 60 + sm
                except (ValueError, AttributeError):
                    slot_min = -10000
                # Fire when the current minute is at or just past the slot
                # (execution key prevents double creation).
                if 0 <= (current_min - slot_min) <= GRACE:
                    self._create_task_for_sop(sop, today, slot)

                # "Before" reminder.
                if self._time_minus(slot, sop.notify_before_min) == current_time:
                    self._send_pre_notification(sop, today, slot)

                # "After" follow-up.
                if self._time_plus(slot, sop.notify_after_min) == current_time:
                    self._check_completion(sop, today, slot)

                # Escalation to admin.
                if self._time_plus(slot, sop.admin_notify_after_min) == current_time:
                    self._escalate_to_admin(sop, today, slot)

    @staticmethod
    def _time_minus(time_str: str, minutes: int) -> str:
        """Subtract minutes from HH:MM time string."""
        h, m = map(int, time_str.split(":"))
        total = h * 60 + m - minutes
        # Clamp to 00:00
        if total < 0:
            total = 0
        return f"{total // 60:02d}:{total % 60:02d}"

    @staticmethod
    def _time_plus(time_str: str, minutes: int) -> str:
        """Add minutes to HH:MM time string."""
        h, m = map(int, time_str.split(":"))
        total = h * 60 + m + minutes
        # Clamp to 23:59
        if total >= 1440:
            total = 1439
        return f"{total // 60:02d}:{total % 60:02d}"

    def _get_or_create_execution(self, sop: SOPDefinition, scheduled_date: date,
                                 slot: str = None) -> SOPExecution:
        """Get existing execution for this date+slot or create a new one.
        Keying on slot lets interval SOPs track each fire independently."""
        date_str = scheduled_date.isoformat()
        slot = slot or sop.start_time
        result = self.db.execute(
            select(SOPExecution).where(
                SOPExecution.sop_id == sop.id,
                SOPExecution.scheduled_date == date_str,
                SOPExecution.scheduled_time == slot,
            )
        )
        execution = result.scalar_one_or_none()
        if execution:
            return execution

        execution = SOPExecution(
            sop_id=sop.id,
            assigned_to_id=sop.assigned_to_id,
            scheduled_date=date_str,
            scheduled_time=slot,
            status="pending",
        )
        self.db.add(execution)
        self.db.commit()
        self.db.refresh(execution)
        return execution

    def _create_task_for_sop(self, sop: SOPDefinition, today: date, slot: str = None):
        """Create a task from SOP template and mark execution."""
        slot = slot or sop.start_time
        execution = self._get_or_create_execution(sop, today, slot)
        if execution.task_id:
            return  # Task already created

        # Employee on leave — don't create/send this SOP task; mark it 'leave'
        # so the rollover won't count it as missed and the report shows it apart.
        emp = self.emp_svc.get_by_id(sop.assigned_to_id)
        if emp and getattr(emp, "on_leave", False):
            execution.status = "leave"
            self.db.commit()
            return

        # Create the actual task
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

        execution.task_id = task.id
        execution.status = "notified"
        execution.notified_at = datetime.now(timezone.utc)

        # Mark SOP as triggered for today
        sop.last_triggered_date = today.isoformat()

        self.db.commit()

        # Send WhatsApp notification
        self._notify_employee(sop, task, "new_task", slot)

        logger.info(f"SOP task created: {sop.title} @ {slot} -> {task.id}")

    def _send_pre_notification(self, sop: SOPDefinition, today: date, slot: str = None):
        """Send reminder that task is about to start."""
        slot = slot or sop.start_time
        execution = self._get_or_create_execution(sop, today, slot)
        if execution.status not in ("pending",):
            return

        emp = self.emp_svc.get_by_id(sop.assigned_to_id)
        if not emp:
            return

        msg = (f"⏰ *Reminder:* \"{sop.title}\" starts in {sop.notify_before_min} min.\n"
               f"Please prepare to start at {slot}.")
        try:
            from app.services.nlu import nlu_service
            send_whatsapp(emp.whatsapp_number,
                          nlu_service.translate(msg, getattr(emp, "preferred_language", "english")))
        except Exception as e:
            logger.error(f"Pre-notify failed for {emp.name}: {e}")

    def _execution_task_done(self, execution: SOPExecution) -> bool:
        """Has the Task linked to this execution been completed?

        Employees complete SOP tasks by replying 'done' on WhatsApp, which marks
        the *Task* done (TaskManager.mark_done) but never touches the
        SOPExecution. Without bridging the two, completed SOP tasks still trigger
        the 'still pending' follow-up and the admin escalation. Treat a done task
        as a done execution here so those don't fire."""
        if not execution.task_id:
            return False
        task = self.db.execute(
            select(Task).where(Task.id == execution.task_id)
        ).scalar_one_or_none()
        return bool(task and task.status == TaskStatus.done)

    def _check_completion(self, sop: SOPDefinition, today: date, slot: str = None):
        """Check if task was completed, follow up if not."""
        slot = slot or sop.start_time
        execution = self._get_or_create_execution(sop, today, slot)
        if execution.status == "done":
            return
        # Sync completion from the linked task (WhatsApp 'done' marks the task,
        # not the execution).
        if self._execution_task_done(execution):
            execution.status = "done"
            execution.completed_at = datetime.now(timezone.utc)
            self.db.commit()
            return

        emp = self.emp_svc.get_by_id(sop.assigned_to_id)
        if not emp:
            return

        msg = (f"🔔 *Follow-up:* \"{sop.title}\" was due {sop.notify_after_min} min ago.\n"
               f"Reply 'done' if completed, or describe any issues.")
        try:
            from app.services.nlu import nlu_service
            send_whatsapp(emp.whatsapp_number,
                          nlu_service.translate(msg, getattr(emp, "preferred_language", "english")))
        except Exception as e:
            logger.error(f"Follow-up failed for {emp.name}: {e}")

    def _escalate_to_admin(self, sop: SOPDefinition, today: date, slot: str = None):
        """Escalate to admin if task not completed."""
        slot = slot or sop.start_time
        execution = self._get_or_create_execution(sop, today, slot)
        if execution.status == "done":
            return
        # Don't escalate a task the employee already completed via WhatsApp.
        if self._execution_task_done(execution):
            execution.status = "done"
            execution.completed_at = datetime.now(timezone.utc)
            self.db.commit()
            return

        # Mark as escalated
        execution.status = "escalated"
        execution.escalated_at = datetime.now(timezone.utc)
        self.db.commit()

        # Notify admin
        admin_id = sop.admin_id
        if not admin_id:
            # Fallback: find any admin
            admins = self.emp_svc.get_all_admins()
            if not admins:
                return
            admin = admins[0]
        else:
            admin = self.emp_svc.get_by_id(admin_id)

        emp = self.emp_svc.get_by_id(sop.assigned_to_id)
        emp_name = emp.name if emp else "Unknown"

        if admin:
            msg = (f"⚠️ *SOP Escalation*\n\n"
                   f"Task: {sop.title}\n"
                   f"Assigned to: {emp_name}\n"
                   f"Not completed after {sop.admin_notify_after_min} min.\n"
                   f"Department: {sop.department}")
            try:
                send_whatsapp(admin.whatsapp_number, msg)
            except Exception as e:
                logger.error(f"Escalation notify failed: {e}")

    def _notify_employee(self, sop: SOPDefinition, task: Task, notify_type: str, slot: str = None):
        """Send WhatsApp notification to employee about new task."""
        slot = slot or sop.start_time
        emp = self.emp_svc.get_by_id(sop.assigned_to_id)
        if not emp:
            return

        # When the SOP has a photo checklist, spell out the required items so the
        # employee knows exactly which photos to send (and in what order).
        from app.services.attachment_service import AttachmentService
        checklist = AttachmentService(self.db).get_checklist(sop)
        if checklist:
            items = "\n".join(f"  {i}. {label}" for i, label in enumerate(checklist, 1))
            msg = (f"📋 *New SOP Task:* {sop.title}\n\n"
                   f"Start: {slot}\n"
                   f"📸 Send a photo for each item, one at a time:\n{items}\n\n"
                   f"Priority: {sop.priority.upper()}")
        else:
            msg = (f"📋 *New SOP Task:* {sop.title}\n\n"
                   f"Start: {slot}\n"
                   f"{'📎 Attachment required' if sop.requires_attachment else ''}\n"
                   f"Priority: {sop.priority.upper()}\n\n"
                   f"Reply 'done' when completed.")
        try:
            from app.services.nlu import nlu_service
            send_whatsapp(emp.whatsapp_number,
                          nlu_service.translate(msg, getattr(emp, "preferred_language", "english")))
        except Exception as e:
            logger.error(f"SOP notify failed for {emp.name}: {e}")

    # ── Bulk Import from Excel Data ─────────────────────────────────────────

    def bulk_create_from_list(self, items: list) -> dict:
        """Create SOPs from a list of dicts (from Excel import)."""
        count = 0
        errors = []
        for i, item in enumerate(items):
            try:
                self.create(item)
                count += 1
            except Exception as e:
                errors.append(f"Item {i+1}: {e}")
        return {"created": count, "errors": errors, "total": len(items)}

    # ── XLSX Import (sheet -> employees + SOPs) ──────────────────────────────

    @staticmethod
    def _cell_str(v) -> str:
        return "" if v is None else str(v).strip()

    @staticmethod
    def _normalize_number(v) -> str:
        """Delegate to the shared canonical normalizer so sheet imports key
        employees the same way CSV import, the dashboard, and the webhook do."""
        from app.utils.helpers import normalize_phone
        return normalize_phone(SOPService._cell_str(v))

    @staticmethod
    def _normalize_time(v) -> str | None:
        """Coerce a cell to 'HH:MM'. Handles datetime.time/datetime, and
        strings like '12:00:00', '8:00', '12.00'. Returns None if not a time."""
        import datetime as _dt, re
        if isinstance(v, (_dt.time, _dt.datetime)):
            return f"{v.hour:02d}:{v.minute:02d}"
        s = SOPService._cell_str(v)
        if not s:
            return None
        m = re.match(r"^(\d{1,2})[:.](\d{2})", s)
        if not m:
            return None
        h, mi = int(m.group(1)), int(m.group(2))
        if h > 23 or mi > 59:
            return None
        return f"{h:02d}:{mi:02d}"

    @staticmethod
    def _parse_end(v) -> tuple:
        """Interpret the 'Task End Time' cell.
        Returns (interval_hours|None, end_time 'HH:MM'|None).
        'every 4 hours' -> (4.0, None); '11:45:00' -> (None, '11:45')."""
        import re
        s = SOPService._cell_str(v).lower()
        if not s:
            return (None, None)
        m = re.search(r"every\s*(\d+(?:\.\d+)?)\s*(hour|hr|h|min)", s)
        if m:
            n = float(m.group(1))
            if m.group(2).startswith("min"):
                n = n / 60.0
            return (n, None)
        t = SOPService._normalize_time(v)
        return (None, t)

    @staticmethod
    def _yesno(v) -> bool:
        return SOPService._cell_str(v).lower() in ("yes", "y", "true", "1", "required", "req")

    def _upsert_employee(self, name: str, number: str, role: str, department: str):
        """Find employee by number (active or not) or create one. Returns
        (employee, created_bool). Number must be pre-normalized."""
        emp = self.db.execute(
            select(Employee).where(Employee.whatsapp_number == number)
        ).scalar_one_or_none()
        if emp:
            # Backfill blank fields from the sheet; never clobber existing data.
            if name and not emp.name:
                emp.name = name
            if role and not emp.role:
                emp.role = role
            if department and not emp.department:
                emp.department = department
            return emp, False
        emp = Employee(
            name=name or f"User-{number[-4:]}",
            department=department or "General",
            role=role or "Staff",
            whatsapp_number=number,
            registered_via="sop_import",
        )
        self.db.add(emp)
        self.db.flush()
        return emp, True

    def import_from_xlsx(self, file_bytes: bytes, default_priority: str = "medium") -> dict:
        """Parse the SOP roster sheet and create employees + SOP definitions.

        Handles: section-header rows (carried as department), blank rows,
        times with seconds, 'every N hours' end times (-> interval_hours),
        yes/no attachment, and 10-digit numbers (-> +91). Each row is
        independent — one bad row never aborts the rest."""
        import io
        try:
            import openpyxl
        except ImportError:
            return {"error": "openpyxl not installed", "created": 0}

        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return {"error": "empty sheet", "created": 0}

        header = [self._cell_str(c).lower() for c in rows[0]]

        def col(*needles):
            for i, h in enumerate(header):
                if any(n in h for n in needles):
                    return i
            return None

        ix = {
            "name": col("task name"),
            "details": col("task details", "details"),
            "start": col("start"),
            "end": col("end"),
            "attach": col("attachment", "require"),
            "person": col("assigned person", "assigned"),
            "dept": col("department"),
            "number": col("whatsapp", "whasapp", "number", "mobile"),
            "notes": col("note", "reminder", "remark"),
        }
        if ix["name"] is None or ix["person"] is None:
            return {"error": "missing 'Task Name' / 'Assigned Person' columns",
                    "header": header, "created": 0}

        def get(cells, key):
            i = ix[key]
            if i is None or i >= len(cells):
                return None
            return cells[i]

        section = None
        created = 0
        emps_created = 0
        errors = []
        skipped = 0

        for ri, cells in enumerate(rows[1:], start=2):
            cells = list(cells)
            title = self._cell_str(get(cells, "name"))
            person = self._cell_str(get(cells, "person"))
            number = self._normalize_number(get(cells, "number"))
            start = self._normalize_time(get(cells, "start"))

            # Section header: a title with no assignee/number/start time.
            if title and not person and not number and not start:
                section = title
                continue
            # Blank row.
            if not title and not person:
                skipped += 1
                continue
            # Real task row — validate.
            if not person or not number:
                errors.append(f"Row {ri} ('{title}'): missing assignee name/number")
                skipped += 1
                continue
            if not start:
                errors.append(f"Row {ri} ('{title}'): missing/invalid start time")
                skipped += 1
                continue

            try:
                role = self._cell_str(get(cells, "dept"))   # sheet 'Department' col = job title
                department = section or role or "General"
                emp, was_new = self._upsert_employee(person, number, role, department)
                if was_new:
                    emps_created += 1

                interval, end = self._parse_end(get(cells, "end"))
                self.create({
                    "title": title,
                    "description": self._cell_str(get(cells, "details")) or None,
                    "department": department,
                    "start_time": start,
                    "end_time": end,
                    "interval_hours": interval,
                    "assigned_to_id": emp.id,
                    "requires_attachment": self._yesno(get(cells, "attach")),
                    "priority": default_priority,
                })
                created += 1
            except Exception as e:
                self.db.rollback()
                errors.append(f"Row {ri} ('{title}'): {e}")
                skipped += 1

        return {
            "created": created,
            "employees_created": emps_created,
            "skipped": skipped,
            "errors": errors,
            "total_rows": len(rows) - 1,
        }

    def get_executions(self, sop_id: str = None, limit: int = 50) -> list:
        """Get execution history."""
        query = select(SOPExecution).order_by(SOPExecution.created_at.desc())
        if sop_id:
            query = query.where(SOPExecution.sop_id == sop_id)
        result = self.db.execute(query.limit(limit))
        return list(result.scalars().all())

    def mark_execution_done(self, execution_id: str) -> bool:
        """Mark an execution as completed."""
        execution = self.db.execute(select(SOPExecution).where(SOPExecution.id == execution_id))
        execution = execution.scalar_one_or_none()
        if not execution:
            return False
        execution.status = "done"
        execution.completed_at = datetime.now(timezone.utc)
        self.db.commit()
        return True

    def rollover_missed(self) -> dict:
        """Close out SOP executions from past days that were never completed.
        A SOP is a same-day operation — if not done by end of its day it is
        MISSED, not carried forward. Marks such executions + their tasks
        'missed' so they leave the pending buckets and show in the report.
        Idempotent; runs on a schedule (day boundary in app_timezone)."""
        today = self._now_local().date().isoformat()
        stale = self.db.execute(
            select(SOPExecution).where(
                SOPExecution.scheduled_date < today,
                SOPExecution.status.notin_(["done", "missed", "leave"]),
            )
        ).scalars().all()
        closed = 0
        for ex in stale:
            ex.status = "missed"
            if ex.task_id:
                task = self.db.execute(
                    select(Task).where(Task.id == ex.task_id)
                ).scalar_one_or_none()
                # Only close tasks still open — never overwrite a done/escalated one.
                if task and task.status in (TaskStatus.pending, TaskStatus.in_progress):
                    task.status = TaskStatus.missed
            closed += 1
        if closed:
            self.db.commit()
            logger.info("SOP rollover: marked %d stale executions missed", closed)
        return {"missed": closed}
