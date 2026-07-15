# SLA Toggle + Daily Reminder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-task SLA toggle, global SLA master switch, and per-department daily reminder digest system.

**Architecture:** Three parts: (1) new `sla_enabled` field on Task model + global `sla_enabled` setting, (2) new `department_configs` table storing per-dept reminder time + SLA toggle, (3) new scheduler job `_run_daily_reminders` sending digest WhatsApp messages at configured times. SLA checker modified to respect all three levels of toggle (global, department, per-task).

**Tech Stack:** Python/FastAPI, SQLAlchemy, APScheduler, React/TypeScript, WhatsApp API

---

## File Structure

### Files to Create
- `backend/app/models/department_config.py` — DepartmentConfig model
- `backend/app/routers/department_configs.py` — CRUD endpoints for department configs

### Files to Modify
- `backend/app/models/task.py` — add `sla_enabled` column
- `backend/app/schemas/task.py` — add `sla_enabled` to TaskUpdate
- `backend/app/routers/tasks.py` — add `sla_enabled` to list/create/responses
- `backend/app/routers/settings.py` — add `sla_enabled` to DEFAULTS
- `backend/app/services/scheduler.py` — add `_run_daily_reminders`, modify `_run_sla_check`
- `backend/app/services/task_manager.py` — add `sla_enabled` param to `assign()`
- `backend/app/main.py` — register department_configs router
- `backend/app/database.py` — import DepartmentConfig model
- `frontend/src/api/client.ts` — add department config API methods
- `frontend/src/pages/Settings.tsx` — add SLA & Reminders section
- `frontend/src/pages/Tasks.tsx` — add SLA toggle to assign modal
- `frontend/src/components/EditTaskModal.tsx` — add SLA toggle
- `docs/superpowers/specs/2026-06-23-sla-daily-reminder-design.md` — design doc already written

---

### Task 1: Add `sla_enabled` column to Task model

**Files:**
- Modify: `backend/app/models/task.py:45` (after `requires_attachment` line)

- [ ] **Step 1: Add column to Task model**

Edit `backend/app/models/task.py`, add after line 45 (`requires_attachment`):

```python
    sla_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
```

Also add `sla_enabled` to the `TaskUpdate` schema in `backend/app/schemas/task.py`:

```python
    sla_enabled: Optional[bool] = None
```

Add after `requires_attachment` line (line 22).

- [ ] **Step 2: Add `sla_enabled` param to TaskManager.assign()**

Edit `backend/app/services/task_manager.py:31` — add `sla_enabled: bool = True` parameter:

```python
        requires_attachment: bool = False,
        sla_enabled: bool = True,
```

And add it in the `Task()` constructor after `requires_attachment`:

```python
            requires_attachment=requires_attachment,
            sla_enabled=sla_enabled,
```

- [ ] **Step 3: Update TaskManager.update_task() field_map**

Edit `backend/app/services/task_manager.py:170` — add `sla_enabled` to field_map:

```python
            "requires_attachment": "requires_attachment",
            "sla_enabled": "sla_enabled",
```

---

### Task 2: Create DepartmentConfig model

**Files:**
- Create: `backend/app/models/department_config.py`

- [ ] **Step 1: Create the model file**

```python
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, Integer, Boolean
from sqlalchemy.orm import mapped_column, Mapped
from app.database import Base
import uuid


class DepartmentConfig(Base):
    """Per-department SLA and daily reminder configuration."""
    __tablename__ = "department_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    department: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    reminder_time: Mapped[str] = mapped_column(String(5), nullable=True)  # HH:MM, null = no reminder
    sla_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_reminder_date: Mapped[str] = mapped_column(String(10), nullable=True)  # YYYY-MM-DD
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                                                 onupdate=lambda: datetime.now(timezone.utc))
```

- [ ] **Step 2: Import in database.py**

Edit `backend/app/database.py:78`:

```python
    from app.models import employee, task, conversation, kb_document, escalation, audit_log, pending_registration, system_settings, lid_mapping, sop, department_config  # noqa
```

---

### Task 3: Create department_configs API router

**Files:**
- Create: `backend/app/routers/department_configs.py`
- Modify: `backend/app/main.py:70` — register router

- [ ] **Step 1: Create the router**

```python
"""Department Configs Router — per-department SLA toggle and reminder time."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import select
from app.database import get_db
from app.models.department_config import DepartmentConfig
from app.routers.auth import verify_token

router = APIRouter(prefix="/api/department-configs", tags=["department-configs"])


class UpsertConfigRequest(BaseModel):
    reminder_time: Optional[str] = None  # HH:MM or null
    sla_enabled: Optional[bool] = None


@router.get("/")
def list_configs(db=Depends(get_db), _user=Depends(verify_token)):
    """List all department configs."""
    result = db.execute(select(DepartmentConfig).order_by(DepartmentConfig.department))
    configs = result.scalars().all()
    return [{
        "department": c.department,
        "reminder_time": c.reminder_time,
        "sla_enabled": c.sla_enabled,
        "last_reminder_date": c.last_reminder_date,
    } for c in configs]


@router.put("/{department}")
def upsert_config(
    department: str,
    req: UpsertConfigRequest,
    db=Depends(get_db),
    _user=Depends(verify_token),
):
    """Create or update config for a department."""
    result = db.execute(select(DepartmentConfig).where(DepartmentConfig.department == department))
    config = result.scalar_one_or_none()

    if not config:
        config = DepartmentConfig(department=department)
        db.add(config)

    if req.reminder_time is not None:
        config.reminder_time = req.reminder_time if req.reminder_time else None
    if req.sla_enabled is not None:
        config.sla_enabled = req.sla_enabled

    db.commit()
    db.refresh(config)
    return {
        "department": config.department,
        "reminder_time": config.reminder_time,
        "sla_enabled": config.sla_enabled,
    }
```

- [ ] **Step 2: Register router in main.py**

Edit `backend/app/main.py:8` — add import:

```python
from app.routers import webhook, employees, tasks, kb, internal, auth, openwa, analytics, escalations, logs, sops
from app.routers import settings as settings_router
from app.routers import department_configs as department_configs_router
```

Add after line 70 (`app.include_router(sops.router)`):

```python
app.include_router(department_configs_router.router)
```

---

### Task 4: Add `sla_enabled` to settings defaults

**Files:**
- Modify: `backend/app/routers/settings.py:13-30`

- [ ] **Step 1: Add `sla_enabled` to DEFAULTS**

Edit `backend/app/routers/settings.py`, add after `sla_hours` entry:

```python
    "sla_enabled": {
        "value": "true",
        "description": "Enable SLA escalation for overdue tasks (master switch)"
    },
```

---

### Task 5: Add `sla_enabled` to tasks router responses and create flow

**Files:**
- Modify: `backend/app/routers/tasks.py`

- [ ] **Step 1: Add `sla_enabled` to list_tasks response**

Edit line 31-40 — add `"sla_enabled"` to each task dict in list_tasks:

```python
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
```

- [ ] **Step 2: Add `sla_enabled` to list_pending_tasks response**

Edit line 46-51 — add `"sla_enabled"`:

```python
    return [{"id": t.id, "title": t.title, "status": t.status.value,
             "priority": t.priority.value, "assigned_to_id": t.assigned_to_id,
             "due_date": str(t.due_date) if t.due_date else None,
             "created_at": str(t.assigned_at),
             "description": t.description,
             "requires_attachment": t.requires_attachment,
             "sla_enabled": t.sla_enabled} for t in tasks]
```

- [ ] **Step 3: Add `sla_enabled` to employee_tasks response**

Edit line 63-67:

```python
    return [{"id": t.id, "title": t.title, "status": t.status.value,
             "priority": t.priority.value, "due_date": str(t.due_date) if t.due_date else None,
             "description": t.description,
             "requires_attachment": t.requires_attachment,
             "sla_enabled": t.sla_enabled}
            for t in tasks]
```

- [ ] **Step 4: Add `sla_enabled` field to DashboardTaskAssign model**

Edit line 80, add:

```python
    sla_enabled: bool = True
```

- [ ] **Step 5: Pass `sla_enabled` to TaskManager.assign() call**

Edit line 93-103 — add `sla_enabled=req.sla_enabled` to the `mgr.assign()` call:

```python
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
```

- [ ] **Step 6: Add `sla_enabled` to DashboardTaskAssign response**

Edit line 130 — add `"sla_enabled"` to return:

```python
        return {"id": task.id, "title": task.title, "status": task.status.value, "sla_enabled": task.sla_enabled}
```

- [ ] **Step 7: Add `sla_enabled` to update_task response**

Edit line 274-275 — add `"sla_enabled"`:

```python
        return {"id": updated.id, "title": updated.title, "status": updated.status.value,
                "priority": updated.priority.value, "sla_enabled": updated.sla_enabled, "message": "Updated"}
```

---

### Task 6: Add daily reminder job and modify SLA check in scheduler

**Files:**
- Modify: `backend/app/services/scheduler.py`

- [ ] **Step 1: Add `_run_daily_reminders` function**

Add after `_run_sop_scheduler` function (before `start_scheduler`):

```python
def _run_daily_reminders():
    """Send daily task digest at per-department configured reminder_time."""
    if not _acquire_job_lock("daily_reminders", ttl=50):
        return
    from app.database import get_db_context
    from app.services.employee_svc import EmployeeService
    from app.services.whatsapp import send_whatsapp
    from app.models.task import Task, TaskStatus
    from app.models.sop import SOPExecution
    from app.models.department_config import DepartmentConfig
    from sqlalchemy import select
    from datetime import date

    today_str = date.today().isoformat()
    now_hhmm = datetime.now(timezone.utc).strftime("%H:%M")

    with get_db_context() as db:
        result = db.execute(
            select(DepartmentConfig).where(
                DepartmentConfig.reminder_time.isnot(None),
                DepartmentConfig.reminder_time == now_hhmm,
                (DepartmentConfig.last_reminder_date != today_str) |
                (DepartmentConfig.last_reminder_date.is_(None)),
            )
        )
        configs = list(result.scalars().all())

        for cfg in configs:
            emp_svc = EmployeeService(db)
            employees = emp_svc.get_by_department(cfg.department)

            for emp in employees:
                # Get pending tasks for this employee, excluding SOP-generated tasks
                result = db.execute(
                    select(Task).where(
                        Task.assigned_to_id == emp.id,
                        Task.status.in_([TaskStatus.pending, TaskStatus.in_progress]),
                        # Exclude tasks linked to SOP executions
                        ~Task.id.in_(
                            select(SOPExecution.task_id).where(SOPExecution.task_id.isnot(None))
                        ),
                    ).order_by(Task.priority, Task.due_date, Task.assigned_at)
                )
                pending = list(result.scalars().all())

                if not pending:
                    continue

                # Build digest message
                lines = [f"📋 *Daily Task Summary*\n\nYou have {len(pending)} pending task(s):\n"]
                for i, t in enumerate(pending, 1):
                    emoji = {"high": "🔴", "medium": "🟡", "low": "🔵"}.get(t.priority.value, "⚪")
                    due_info = ""
                    if t.due_date:
                        days_left = (t.due_date.date() - date.today()).days
                        if days_left < 0:
                            due_info = " — OVERDUE"
                        elif days_left == 0:
                            due_info = " — Due today"
                        elif days_left == 1:
                            due_info = " — Due tomorrow"
                        else:
                            due_info = f" — Due in {days_left} days"
                    lines.append(f"{i}) {emoji} {t.title}{due_info}")

                lines.append("\nReply 'done' to complete any task.")
                msg = "\n".join(lines)

                try:
                    from app.services.nlu import nlu_service
                    send_whatsapp(emp.whatsapp_number,
                        nlu_service.translate(msg, getattr(emp, "preferred_language", "english")))
                except Exception as e:
                    logger.error(f"Daily reminder failed for {emp.name}: {e}")

            # Mark department as reminded today
            cfg.last_reminder_date = today_str
            db.commit()

        if configs:
            logger.info(f"Daily reminders sent for {len(configs)} departments at {now_hhmm}")
```

- [ ] **Step 2: Modify `_run_sla_check` to respect all toggle levels**

Replace the current `_run_sla_check` function (lines 77-130) with:

```python
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
        overdue_sla = [
            t for t in result.scalars().all()
            if not (t.due_date and t.due_date > now)
        ]

        emp_svc = EmployeeService(db)
        admins = emp_svc.get_all_admins()
        escalated_count = 0

        for task in overdue_sla:
            # 2. Check per-task toggle
            if not task.sla_enabled:
                continue

            # 3. Check department-level toggle
            dept_cfg = dept_configs.get(task.assigned_to.department if task.assigned_to else None)
            if dept_cfg and not dept_cfg.sla_enabled:
                continue

            task.status = TaskStatus.escalated
            emp = emp_svc.get_by_id(task.assigned_to_id)
            emp_name = emp.name if emp else "Unknown"
            ticket = EscalationTicket(
                employee_id=task.assigned_to_id,
                task_id=task.id,
                original_query=f"SLA Breach: Task '{task.title}' not started within {sla_hours} hours.",
                status=EscalationStatus.open,
            )
            db.add(ticket)
            for admin in admins:
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
```

- [ ] **Step 3: Register the new job in `start_scheduler()`**

Edit line 189 — add after the SOP scheduler job:

```python
    scheduler.add_job(_run_daily_reminders, IntervalTrigger(seconds=60), id="daily_reminders", replace_existing=True)
```

Update line 191 log message:

```python
    logger.info("Scheduler started with 5 jobs: due_tasks(30m), sla(1h), followups(15m), sop(60s), reminders(60s)")
```

**Note:** The `_run_sla_check` function references `task.assigned_to.department`. The `Task` model has a relationship `assigned_to = relationship("Employee", foreign_keys=[assigned_to_id])`. However, the relationship might not be loaded when accessed within the scheduler context (since the session may not have loaded it eagerly). We need to import and use `Employee` model to get the department for each task. Let me fix this — instead of accessing `task.assigned_to.department`, do a direct lookup:

Replace line where department is checked:
```python
            # 3. Check department-level toggle
            emp = emp_svc.get_by_id(task.assigned_to_id)
            dept_cfg = dept_configs.get(emp.department if emp else None)
            if dept_cfg and not dept_cfg.sla_enabled:
                continue
```

And remove the duplicate `emp = emp_svc.get_by_id(task.assigned_to_id)` that appears later (line ~112 in original).

---

### Task 7: Frontend — Add department config API methods

**Files:**
- Modify: `frontend/src/api/client.ts`

- [ ] **Step 1: Add API methods**

Add after the SOP API methods (after line 131):

```typescript
  // Department Configs (SLA + Daily Reminders)
  getDepartmentConfigs: () => fetchJSON(`${BASE}/department-configs/`),
  upsertDepartmentConfig: (department: string, data: { reminder_time?: string | null; sla_enabled?: boolean }) =>
    fetchJSON(`${BASE}/department-configs/${encodeURIComponent(department)}`, { method: 'PUT', body: JSON.stringify(data) }),
```

---

### Task 8: Frontend — Settings page SLA & Reminders section

**Files:**
- Modify: `frontend/src/pages/Settings.tsx`

- [ ] **Step 1: Add SLA & Reminders section**

Edit `Settings.tsx`. Add new imports:
```typescript
import { Settings as SettingsIcon, Moon, Sun, Server, Shield, Bell, ShieldOff } from 'lucide-react'
```

Add state variables after line 10:
```typescript
  const [deptConfigs, setDeptConfigs] = useState<any[]>([])
  const [employeesLoading, setEmployeesLoading] = useState(true)
```

Add data loading in useEffect:
```typescript
    api.getDepartmentConfigs().then(setDeptConfigs).catch(() => {}).finally(() => setEmployeesLoading(false))
```

Add handler function before `toggleDark`:
```typescript
  const handleSaveDeptConfig = async (department: string, field: string, value: any) => {
    try {
      const existing = deptConfigs.find(c => c.department === department)
      const payload: any = {}
      payload[field] = value
      await api.upsertDepartmentConfig(department, payload)
      setDeptConfigs(deptConfigs.map(c => c.department === department ? { ...c, [field]: value } : c))
    } catch (err) {
      alert('Failed to save: ' + err)
    }
  }
```

Add a new card after the Behavior card (after line 101 `</div>`):

```tsx
        {/* SLA & Daily Reminders */}
        <div className="bg-white rounded-xl shadow p-6">
          <h2 className="font-semibold mb-4 flex items-center gap-2">
            <Bell className="w-5 h-5" /> SLA & Daily Reminders
          </h2>
          <div className="space-y-4">
            {/* Global SLA Toggle */}
            <div className="flex items-center justify-between pb-3 border-b">
              <div>
                <p className="font-medium">Enable SLA Escalation (Global)</p>
                <p className="text-xs text-gray-500">Master switch for all SLA auto-escalation</p>
              </div>
              {(() => {
                const slaSetting = settings.find(s => s.key === 'sla_enabled')
                return slaSetting ? (
                  <button onClick={() => handleToggleSetting('sla_enabled', slaSetting.value)}
                    className={`relative w-12 h-6 rounded-full transition-colors shrink-0 ${slaSetting.value === 'true' ? 'bg-indigo-600' : 'bg-gray-300'}`}>
                    <span className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform ${slaSetting.value === 'true' ? 'translate-x-6' : ''}`}></span>
                  </button>
                ) : <span className="text-sm text-gray-400">Loading...</span>
              })()}
            </div>

            {/* Department Reminder Times */}
            <div>
              <p className="font-medium mb-2">Department Reminder Times</p>
              <p className="text-xs text-gray-500 mb-3">Set daily digest time per department. Empty = no reminder.</p>
              {employeesLoading ? (
                <p className="text-sm text-gray-400">Loading departments...</p>
              ) : deptConfigs.length === 0 ? (
                <p className="text-sm text-gray-400">No departments configured yet. Add departments via Employees page first.</p>
              ) : (
                <div className="space-y-2">
                  {deptConfigs.map(cfg => (
                    <div key={cfg.department} className="flex items-center gap-3 p-2 bg-gray-50 rounded-lg">
                      <span className="text-sm font-medium w-40 truncate">{cfg.department}</span>
                      <input type="time" value={cfg.reminder_time || ''}
                        onChange={e => {
                          const val = e.target.value || null
                          setDeptConfigs(deptConfigs.map(c => c.department === cfg.department ? { ...c, reminder_time: val } : c))
                        }}
                        onBlur={e => handleSaveDeptConfig(cfg.department, 'reminder_time', e.target.value || null)}
                        className="border rounded px-2 py-1 text-sm" />
                      <label className="flex items-center gap-1 text-sm ml-auto">
                        <input type="checkbox" checked={cfg.sla_enabled}
                          onChange={e => handleSaveDeptConfig(cfg.department, 'sla_enabled', e.target.checked)} />
                        SLA
                      </label>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
```

- [ ] **Step 2: Fetch departments list on load for auto-creation**

Add after the existing useEffect data loading — we need to ensure department configs exist for all departments. Add to useEffect:

```typescript
    // Auto-create department configs for any departments missing them
    api.getDepartments().then((depts: any[]) => {
      const deptNames = depts.map((d: any) => d.department || d)
      deptNames.forEach((dept: string) => {
        if (!deptConfigs.find(c => c.department === dept)) {
          api.upsertDepartmentConfig(dept, { reminder_time: null, sla_enabled: true }).catch(() => {})
        }
      })
    }).catch(() => {})
```

Note: This needs to be inside a separate effect or after deptConfigs is loaded. Actually, to simplify, we'll handle this differently — just show all departments from the employees endpoint and create configs on first save. We can adjust the UI to show all known departments.

Actually, let's simplify. We'll get departments from `api.getDepartments()` and merge with existing configs. Replace the deptConfigs loading logic:

```typescript
  const [allDepartments, setAllDepartments] = useState<string[]>([])

  useEffect(() => {
    api.getHealth().then(setHealth).catch(() => {})
    api.getOpenWAStatus().then(setOpenWA).catch(() => {})
    api.getSettings().then(setSettings).catch(() => {})
    api.getDepartmentConfigs().then(setDeptConfigs).catch(() => {})
    api.getDepartments().then((depts: any[]) => {
      setAllDepartments(depts.map((d: any) => d.department || d))
    }).catch(() => {})
  }, [])
```

And in the department reminder times section, iterate over `allDepartments` and find/create the config on the fly:

```tsx
                  {allDepartments.map(dept => {
                    const cfg = deptConfigs.find(c => c.department === dept) || { department: dept, reminder_time: null, sla_enabled: true }
                    return (
                      <div key={dept} className="flex items-center gap-3 p-2 bg-gray-50 rounded-lg">
                        <span className="text-sm font-medium w-40 truncate">{dept}</span>
                        <input type="time" value={cfg.reminder_time || ''}
                          onChange={e => {
                            const val = e.target.value || null
                            // Update local state directly
                            handleSaveDeptConfig(dept, 'reminder_time', val)
                          }}
                          className="border rounded px-2 py-1 text-sm" />
                        <label className="flex items-center gap-1 text-sm ml-auto">
                          <input type="checkbox" checked={cfg.sla_enabled}
                            onChange={e => handleSaveDeptConfig(dept, 'sla_enabled', e.target.checked)} />
                          SLA
                        </label>
                      </div>
                    )
                  })}
```

This is cleaner — no auto-creation needed, the PUT will create on first save.

---

### Task 9: Frontend — Add SLA toggle to Tasks assign modal

**Files:**
- Modify: `frontend/src/pages/Tasks.tsx`

- [ ] **Step 1: Add `sla_enabled` to assignForm state**

Edit line 30 — add `sla_enabled: true`:

```typescript
  const [assignForm, setAssignForm] = useState({
    title: '', description: '', priority: 'medium', assigned_to_id: '',
    due_date: '', requires_attachment: false,
    follow_up_enabled: false, follow_up_interval: 30, follow_up_unit: 'min',
    sla_enabled: true,
  })
```

- [ ] **Step 2: Add SLA toggle UI in assign modal**

After the follow-up section (after line 255 `)`), add:

```tsx
              {/* ── SLA section ── */}
              <hr className="my-2" />
              <label className="flex items-center gap-2 text-sm font-medium">
                <input type="checkbox" checked={assignForm.sla_enabled}
                  onChange={e => setAssignForm(f => ({ ...f, sla_enabled: e.target.checked }))} />
                ⚡ Auto-escalate via SLA (escalate if not started after configured hours)
              </label>
```

- [ ] **Step 3: Pass sla_enabled in assign payload**

Edit the api.assignTask call — add `sla_enabled: assignForm.sla_enabled`:

```typescript
      await api.assignTask({
        ...assignForm,
        assigned_by_id: firstAdmin?.id || assignForm.assigned_to_id,
        follow_up_type: followUpType,
        follow_up_interval_hours: followUpHours,
        sla_enabled: assignForm.sla_enabled,
      })
```

- [ ] **Step 4: Reset sla_enabled in form reset**

Edit line 106 — add `sla_enabled: true` to reset:

```typescript
      setAssignForm({
        title: '', description: '', priority: 'medium', assigned_to_id: '',
        due_date: '', requires_attachment: false,
        follow_up_enabled: false, follow_up_interval: 30, follow_up_unit: 'min',
        sla_enabled: true,
      })
```

---

### Task 10: Frontend — Add SLA toggle to EditTaskModal

**Files:**
- Modify: `frontend/src/components/EditTaskModal.tsx`

- [ ] **Step 1: Add SLA state and toggle**

Add after line 31:

```typescript
  const [slaEnabled, setSlaEnabled] = useState(task.sla_enabled !== false)  // default true
```

Add to Task interface (line 11-15):
```typescript
  sla_enabled?: boolean;
```

Add after the requires_attachment toggle (after line 118):

```tsx
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={slaEnabled}
              onChange={e => setSlaEnabled(e.target.checked)} />
            Auto-escalate via SLA
          </label>
```

Add to payload in handleSave (after the requires_attachment check):

```typescript
      if (slaEnabled !== (task.sla_enabled !== false)) payload.sla_enabled = slaEnabled
```

Wait, `task.sla_enabled` might be undefined for old tasks. Let me simplify:

```typescript
      // SLA toggle — always send since default is true
      const currentSla = task.sla_enabled !== false  // undefined defaults to true
      if (slaEnabled !== currentSla) payload.sla_enabled = slaEnabled
```

Add this after `requiresAttachment` check (after line 45):

```typescript
      if (slaEnabled !== (task.sla_enabled !== false)) payload.sla_enabled = slaEnabled
```

---

### Task 11: Rebuild and restart

**Files:**
- Command: `docker-compose build backend frontend && docker-compose up -d`

- [ ] **Step 1: Rebuild containers**

```bash
docker-compose build backend frontend
docker-compose up -d
```

- [ ] **Step 2: Verify**

```bash
docker-compose ps
# Check: all 5 containers healthy

# Check backend logs for any startup errors
docker-compose logs backend --tail 20

# Check frontend loads
curl -s -o /dev/null -w "%{http_code}" http://localhost:3000
# Expected: 200
```

---

## Self-Review Checklist

1. **Spec coverage:** Does every requirement from the design doc have a corresponding task?
   - Per-task SLA toggle → Tasks 1 (model), 5 (router), 9&10 (frontend)
   - Global SLA setting → Task 4 (settings)
   - Department configs model → Task 2
   - Department configs API → Task 3
   - Daily reminder scheduler → Task 6
   - SLA check respects all toggles → Task 6
   - SOP tasks excluded from daily reminder → Task 6 (subquery against SOPExecution)
   - No SOP model changes → confirmed, no SOP files touched
   - Settings UI → Task 8
   - Tasks UI → Tasks 9 & 10

2. **Placeholder scan:** No TBDs, TODOs, or "implement later" patterns.

3. **Type consistency:** All field names match between model, schema, router, and frontend. `sla_enabled` used consistently.

4. **Edge cases covered:** Department without config entry (handled in SLA check with `dept_configs.get(...)` default), SOP exclusion subquery, no-pending-tasks skip, last_reminder_date tracking, global master toggle skips entire SLA run.
