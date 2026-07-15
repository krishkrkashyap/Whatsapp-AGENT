"""F-9: Scheduled cron jobs using APScheduler."""
import logging
from datetime import datetime, timezone
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from app.config import settings

logger = logging.getLogger("scheduler")

scheduler = BackgroundScheduler()


def _acquire_job_lock(name: str, ttl: int) -> bool:
    """Best-effort distributed lock so a job runs on only ONE worker per cycle.

    The backend runs with `uvicorn --workers N`, and the scheduler starts in
    every worker — without this, each reminder/escalation would be sent N times.
    We take a short Redis lock (SET NX EX) keyed per job; whichever worker grabs
    it first runs that cycle, the rest skip. TTL is shorter than the job interval
    so the next cycle is free to run. If Redis is unavailable we fail OPEN (run
    anyway) — correct for the common single-worker/dev case.
    """
    try:
        import redis
        r = redis.from_url(settings.redis_url, socket_timeout=3)
        return bool(r.set(f"scheduler:lock:{name}", "1", nx=True, ex=ttl))
    except Exception as e:
        logger.warning("Scheduler lock unavailable (%s) — running job '%s' unlocked", e, name)
        return True

def _run_check_due_tasks():
    """Check for overdue tasks and send reminders."""
    if not _acquire_job_lock("check_due_tasks", ttl=1500):
        return
    from app.database import get_db_context
    from app.services.task_manager import TaskManager
    from app.services.employee_svc import EmployeeService
    from app.services.whatsapp import send_whatsapp
    from app.routers.settings import get_bool_setting
    from app.models.task import Task, TaskStatus
    from sqlalchemy import select

    with get_db_context() as db:
        if not get_bool_setting(db, "auto_followup_enabled"):
            logger.info("Due task check skipped (auto_followup_enabled=false)")
            return
        now = datetime.now(timezone.utc)
        result = db.execute(
            select(Task).where(
                Task.status.in_([TaskStatus.pending, TaskStatus.in_progress]),
                Task.due_date != None,
                Task.due_date <= now,
            )
        )
        overdue = list(result.scalars().all())
        emp_svc = EmployeeService(db)
        for task in overdue:
            # Use task-specific interval as cooldown, default to 1 hour
            interval_secs = (task.follow_up_interval_hours or 1.0) * 3600
            if task.last_follow_up_at and (now - task.last_follow_up_at).total_seconds() < interval_secs:
                continue
            emp = emp_svc.get_by_id(task.assigned_to_id)
            if emp and not emp.on_leave:
                try:
                    from app.services.nlu import nlu_service
                    msg = (f"⏰ *Reminder:* Task \"{task.title}\" is due!\n"
                           f"Priority: {task.priority.value.upper()}\n\n"
                           f"Reply 'done' if completed, or describe issue for help.")
                    send_whatsapp(emp.whatsapp_number,
                        nlu_service.translate(msg, getattr(emp, "preferred_language", "english")))
                    task.last_follow_up_at = now
                except Exception as e:
                    logger.error(f"Failed to remind {emp.name}: {e}")
        logger.info(f"Due task check: {len(overdue)} overdue tasks processed")

def _run_sla_check():
    """Check for SLA breaches and auto-escalate — respects global, department, and per-task toggles."""
    if not _acquire_job_lock("check_sla", ttl=3300):
        return
    from app.database import get_db_context
    from app.services.employee_svc import EmployeeService
    from app.services.whatsapp import send_whatsapp
    from app.routers.settings import get_int_setting, get_bool_setting
    from app.models.task import Task, TaskStatus
    from app.models.escalation import EscalationTicket, EscalationStatus
    from app.models.department_config import DepartmentConfig
    from app.models.employee import Employee
    from sqlalchemy import select
    from datetime import timedelta

    with get_db_context() as db:
        # 1. Check global toggle
        if not get_bool_setting(db, "sla_enabled"):
            logger.info("SLA check skipped (sla_enabled=false)")
            return

        now = datetime.now(timezone.utc)
        sla_hours = get_int_setting(db, "sla_hours", 4)
        sla_time = now - timedelta(hours=sla_hours)

        # Load all department configs into a dict for fast lookup
        dept_configs_result = db.execute(select(DepartmentConfig))
        dept_configs = {c.department: c for c in dept_configs_result.scalars().all()}

        result = db.execute(
            select(Task).where(
                Task.status == TaskStatus.pending,
                Task.assigned_at <= sla_time,
            )
        )
        # Don't escalate tasks that have an explicit future deadline — they
        # aren't a "not started in time" breach yet, just not started.
        overdue_sla = [
            t for t in result.scalars().all()
            if not (t.due_date and t.due_date > now)
        ]
        emp_svc = EmployeeService(db)
        escalated_count = 0

        for task in overdue_sla:
            # 2. Check per-task toggle
            if not task.sla_enabled:
                continue

            # 3. Check department-level toggle
            emp = emp_svc.get_by_id(task.assigned_to_id)
            dept_cfg = dept_configs.get(emp.department if emp else None)
            if dept_cfg and not dept_cfg.sla_enabled:
                continue

            task.status = TaskStatus.escalated
            emp_name = emp.name if emp else "Unknown"
            ticket = EscalationTicket(
                employee_id=task.assigned_to_id,
                task_id=task.id,
                original_query=f"SLA Breach: Task '{task.title}' not started within {sla_hours} hours.",
                status=EscalationStatus.open,
            )
            db.add(ticket)
            # Notify ONLY this task's admin (its assigner), not every admin.
            task_admin = emp_svc.get_by_id(task.assigned_by_id) if task.assigned_by_id else None
            recipients = emp_svc.resolve_escalation_recipients(task_admin)
            for admin in recipients:
                try:
                    send_whatsapp(admin.whatsapp_number,
                        f"⚠️ *SLA Breach Escalation*\n\n"
                        f"Task: {task.title}\n"
                        f"Assigned to: {emp_name}\n"
                        f"Status: Not started for > {sla_hours} hours!")
                except Exception:
                    pass
            escalated_count += 1

        db.commit()
        logger.info(f"SLA check: {escalated_count} tasks escalated (global={get_bool_setting(db, 'sla_enabled')})")

def _run_periodic_followups():
    """Send periodic follow-up reminders."""
    if not _acquire_job_lock("periodic_followups", ttl=750):
        return
    from app.database import get_db_context
    from app.services.employee_svc import EmployeeService
    from app.services.whatsapp import send_whatsapp
    from app.services.nlu import nlu_service
    from app.routers.settings import get_bool_setting
    from app.models.task import Task, FollowUp, TaskStatus
    from sqlalchemy import select
    from datetime import timedelta

    with get_db_context() as db:
        # Retry forwarding of completed-but-unforwarded checklist photos FIRST —
        # this must run even when auto-followups are disabled, otherwise failed
        # forwards (and their stored base64) would be stranded forever.
        try:
            from app.services.attachment_service import AttachmentService
            AttachmentService(db).retry_unforwarded()
        except Exception as e:
            logger.warning("Attachment forward retry failed: %s", e)

        if not get_bool_setting(db, "auto_followup_enabled"):
            logger.info("Periodic follow-ups skipped (auto_followup_enabled=false)")
            return
        now = datetime.now(timezone.utc)
        result = db.execute(select(FollowUp).where(FollowUp.next_trigger_at <= now))
        followups = list(result.scalars().all())
        emp_svc = EmployeeService(db)
        for fu in followups:
            task_result = db.execute(select(Task).where(Task.id == fu.task_id))
            task = task_result.scalar_one_or_none()
            if not task or task.status == TaskStatus.done:
                continue
            emp = emp_svc.get_by_id(task.assigned_to_id)
            if emp and not emp.on_leave:
                try:
                    msg = (f"🔄 *Follow-up:* Task \"{task.title}\" still pending.\n\n"
                           f"Reply 'done' or describe issue.")
                    send_whatsapp(emp.whatsapp_number,
                        nlu_service.translate(msg, getattr(emp, "preferred_language", "english")))
                except Exception:
                    pass
            if fu.interval_hours:
                fu.next_trigger_at = now + timedelta(hours=fu.interval_hours)
            else:
                fu.next_trigger_at = now + timedelta(days=1)
        logger.info(f"Periodic follow-ups: {len(followups)} checked")

def _run_session_watchdog():
    """Keep the WhatsApp session alive without anyone watching the dashboard.

    The OpenWA engine can drop to 'disconnected' (network blip, WA re-pairing).
    Auth data persists in the gateway volume, so a `start` nudge reconnects it to
    'ready' WITHOUT a new QR. We only nudge on a settled 'disconnected' state —
    'initializing'/'authenticating' are transient and must be left alone."""
    if not _acquire_job_lock("session_watchdog", ttl=110):
        return
    import httpx
    from app.config import settings
    from app.services.openwa_session import get_active_session_id
    if not settings.openwa_api_key:
        return
    sid = get_active_session_id()
    if not sid:
        return
    headers = {"X-API-Key": settings.openwa_api_key}
    base = settings.openwa_base_url
    try:
        resp = httpx.get(f"{base}/sessions/{sid}", headers=headers, timeout=5)
        if resp.status_code != 200:
            return
        status = resp.json().get("status")
    except Exception as e:
        logger.warning("Session watchdog status check failed: %s", e)
        return
    if status == "disconnected":
        logger.info("Session watchdog: session %s disconnected — nudging start", sid)
        try:
            # start init is slow (launches Chrome); a short timeout logs a false
            # error even though the start fires. Give it room.
            httpx.post(f"{base}/sessions/{sid}/start", headers=headers, timeout=20)
        except Exception as e:
            logger.warning("Session watchdog start nudge failed: %s", e)
    elif status == "failed":
        # A crashed puppeteer/Chrome session (e.g. after a container restart) gets
        # stuck 'failed'; a plain start 500s. stop->start clears the bad state and
        # reinitializes from persisted auth. Only re-links (QR) if auth was lost.
        logger.info("Session watchdog: session %s FAILED — stop+start to recover", sid)
        try:
            httpx.post(f"{base}/sessions/{sid}/stop", headers=headers, timeout=10)
            import time
            time.sleep(4)
            httpx.post(f"{base}/sessions/{sid}/start", headers=headers, timeout=15)
        except Exception as e:
            logger.warning("Session watchdog failed-state recovery error: %s", e)


def _run_sop_scheduler():
    """Check SOP schedules — runs every 60 seconds to trigger tasks at correct times."""
    if not _acquire_job_lock("sop_scheduler", ttl=50):
        return
    from app.database import get_db_context
    from app.services.sop_service import SOPService
    with get_db_context() as db:
        svc = SOPService(db)
        svc.check_and_trigger()


def _run_daily_report():
    """Auto-send yesterday's performance report (.xlsx) over WhatsApp to the
    configured recipient. Runs once/day at daily_report_hour (app_timezone)."""
    if not _acquire_job_lock("daily_report", ttl=3600):
        return
    from datetime import timedelta
    from app.database import get_db_context
    from app.services.analytics_report import build_report_xlsx
    from app.services.employee_svc import EmployeeService
    from app.services.whatsapp import send_whatsapp_document
    try:
        from zoneinfo import ZoneInfo
        today_local = datetime.now(ZoneInfo(settings.app_timezone)).date()
    except Exception:
        today_local = datetime.now(timezone.utc).date()
    yday = (today_local - timedelta(days=1)).isoformat()

    with get_db_context() as db:
        recip = (settings.daily_report_recipient or "").strip()
        if recip.startswith("+") or recip.replace("+", "").isdigit():
            number = recip if recip.startswith("+") else "+" + recip
        else:
            emp = EmployeeService(db).get_by_name_or_mention(recip)
            number = emp.whatsapp_number if emp else None
        if not number:
            logger.warning("Daily report: recipient %r not resolved — skipping", recip)
            return
        buf, fname = build_report_xlsx(db, yday, yday)
        send_whatsapp_document(number, fname, buf.getvalue(),
                               caption=f"Daily performance report — {yday}")
        logger.info("Daily report sent to %s for %s", number, yday)


def _run_sop_rollover():
    """Close prior-day SOP executions that were never completed as 'missed'.
    SOPs are same-day operations — they must not carry forward. Hourly so it
    fires soon after the app_timezone day boundary."""
    if not _acquire_job_lock("sop_rollover", ttl=3300):
        return
    from app.database import get_db_context
    from app.services.sop_service import SOPService
    with get_db_context() as db:
        SOPService(db).rollover_missed()


def _run_daily_reminders():
    """Send daily WhatsApp digest per department — one summary per employee covering all pending manual tasks."""
    # Lock TTL must stay BELOW the 60s job interval — it only guards against the
    # 4 workers firing the same minute concurrently. A long TTL (was 3300s) made
    # the first worker hold it for 55 min, so any department whose reminder_time
    # fell in that window was skipped all day. Per-day dedupe is handled by
    # last_reminder_date, not by this lock.
    if not _acquire_job_lock("daily_reminders", ttl=50):
        return
    from app.database import get_db_context
    from app.services.whatsapp import send_whatsapp
    from app.models.task import Task, TaskStatus
    from app.models.sop import SOPExecution
    from app.models.employee import Employee
    from app.models.department_config import DepartmentConfig
    from sqlalchemy import select

    with get_db_context() as db:
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        current_hhmm = now.strftime("%H:%M")

        configs = db.execute(
            select(DepartmentConfig).where(
                DepartmentConfig.reminder_time != None,
                DepartmentConfig.reminder_time == current_hhmm,
            )
        ).scalars().all()

        if not configs:
            return

        for cfg in configs:
            # Already sent today?
            if cfg.last_reminder_date == today:
                continue

            employees = db.execute(
                select(Employee).where(
                    Employee.department == cfg.department,
                    Employee.is_active == True,
                    Employee.on_leave == False,
                )
            ).scalars().all()

            for emp in employees:
                # Find all pending/in-progress manual tasks (exclude SOP-originated)
                pending = db.execute(
                    select(Task).where(
                        Task.assigned_to_id == emp.id,
                        Task.status.in_([TaskStatus.pending, TaskStatus.in_progress]),
                        ~Task.id.in_(select(SOPExecution.task_id).where(SOPExecution.task_id != None)),
                    )
                ).scalars().all()

                if not pending:
                    continue

                # Build summary message
                lines = [f"📋 *Daily Reminder* — You have {len(pending)} pending task(s):\n"]
                for i, t in enumerate(pending, 1):
                    priority_icon = "🔴" if t.priority.value == "high" else "🟡" if t.priority.value == "medium" else "🔵"
                    due_str = f" (due: {t.due_date.strftime('%d-%b')})" if t.due_date else ""
                    lines.append(f"{priority_icon} *{i}.* {t.title}{due_str}")
                lines.append("\n*Reply 'done' on any to complete it.*")
                msg = "\n".join(lines)

                try:
                    send_whatsapp(emp.whatsapp_number, msg)
                except Exception as e:
                    logger.error(f"Daily reminder failed for {emp.name}: {e}")

            # Mark sent
            cfg.last_reminder_date = today

        db.commit()


def start_scheduler():
    """Start the background scheduler with all jobs."""
    scheduler.add_job(_run_check_due_tasks, IntervalTrigger(minutes=30), id="check_due_tasks", replace_existing=True)
    scheduler.add_job(_run_sla_check, IntervalTrigger(hours=1), id="check_sla", replace_existing=True)
    scheduler.add_job(_run_periodic_followups, IntervalTrigger(minutes=15), id="periodic_followups", replace_existing=True)
    scheduler.add_job(_run_sop_scheduler, IntervalTrigger(seconds=60), id="sop_scheduler", replace_existing=True)
    scheduler.add_job(_run_daily_reminders, IntervalTrigger(seconds=60), id="daily_reminders", replace_existing=True)
    scheduler.add_job(_run_session_watchdog, IntervalTrigger(seconds=120), id="session_watchdog", replace_existing=True)
    scheduler.add_job(_run_sop_rollover, IntervalTrigger(hours=1), id="sop_rollover", replace_existing=True)
    try:
        from zoneinfo import ZoneInfo
        report_tz = ZoneInfo(settings.app_timezone)
    except Exception:
        report_tz = None
    scheduler.add_job(_run_daily_report,
                      CronTrigger(hour=settings.daily_report_hour, minute=0, timezone=report_tz),
                      id="daily_report", replace_existing=True)
    scheduler.start()
    logger.info("Scheduler started with 8 jobs: due_tasks(30m), sla(1h), followups(15m), sop(60s), reminders(60s), session_watchdog(120s), sop_rollover(1h), daily_report(%02d:00 %s)",
                settings.daily_report_hour, settings.app_timezone)

def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler stopped")
