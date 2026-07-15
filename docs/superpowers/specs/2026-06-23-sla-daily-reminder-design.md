# SLA Toggle + Daily Reminder System

**Date:** 2026-06-23
**Status:** Approved

## Overview

Two features to make task reminders less aggressive and more predictable:

1. **SLA on/off toggle** — per-task + global master switch to disable auto-escalation for non-urgent tasks
2. **Daily reminder digest** — sends a summary of all pending manually-assigned tasks at per-department configured time (e.g., 10:30 AM)
   - SOP tasks excluded: they have their own notification pipeline (pre-notify → create → follow-up → escalate) and are same-day tasks
   - Only employees with 1+ pending tasks get a message

---

## Data Model

### New: `department_configs` table

```
department_configs
├── id: String (PK, UUID)
├── department: String (unique, matches employee.department values)
├── reminder_time: String (nullable, HH:MM format, null = no daily reminder for this dept)
├── sla_enabled: Boolean (default true, per-department SLA override)
├── last_reminder_date: String (nullable, YYYY-MM-DD, tracks last daily reminder sent)
├── created_at: DateTime
└── updated_at: DateTime
```

### Modified: `tasks` table

Add column:
- `sla_enabled: Boolean` (default true)
- When false, SLA scheduler skips this task
- Independent from follow-up reminders (those keep running based on `follow_up_type`)

### Modified: `system_settings` table

Add key:
- `sla_enabled` → `"true"` (default) — global master toggle
- When `"false"`, entire SLA checker job is skipped entirely
- Per-task `sla_enabled` only matters when global toggle is on

---

*Note: SOP model unchanged. SOP tasks excluded from daily reminder via subquery check against SOPExecution table. SOP notification pipeline remains as previously designed (pre-notify → create task at start_time → follow-up → escalate).*

## Backend API

### New endpoints — Department Configs

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `GET` | `/api/department-configs/` | JWT | List all department configs |
| `PUT` | `/api/department-configs/{department}` | JWT | Upsert: set `reminder_time`, `sla_enabled` |

### Modified endpoints — Tasks

- `POST /api/tasks/assign` — add `sla_enabled` field (optional, default true)
- `PUT /api/tasks/{id}` — allow updating `sla_enabled`
- `GET /api/tasks/` — include `sla_enabled` in response
- `GET /api/tasks/{id}` — include `sla_enabled` in response

### Settings

- `sla_enabled` key auto-seeded on first `GET /api/settings/` call (existing pattern)
- Editable via existing `PUT /api/settings/{key}` endpoint

---

## Scheduler Changes

### New job: `_run_daily_reminders`

- **Interval:** Every 60 seconds (same as SOP scheduler)
- **Logic:**
  1. Read all `department_configs` where `reminder_time` IS NOT NULL and `last_reminder_date != today`
  2. For each dept where `reminder_time == current HH:MM`:
     a. Query all employees in that department
     b. For each employee, collect pending + in_progress tasks, **excluding SOP-generated tasks** (use subquery: exclude tasks that have a linked `SOPExecution`)
     c. If any tasks exist (count > 0), send single WhatsApp digest message
     d. If zero tasks, skip that employee entirely — no message sent
     e. After processing all employees in dept, update `last_reminder_date = today` to prevent duplicate sends
- **Message format:**
  ```
  📋 *Daily Task Summary*
  
  You have {count} pending task(s):
  {index}) {priority_emoji} {title} — Due {due_info}
  
  Reply 'done' to complete any task.
  ```
- Priority emojis: High=🔴, Medium=🟡, Low=🔵

### Modified job: `_run_sla_check`

- **Skip entire run** if global setting `sla_enabled = false`
- **Skip individual task** if `task.sla_enabled = false`
- **Skip individual task** if `department_configs[task.department].sla_enabled = false` (dept override)
- Otherwise, behavior unchanged (escalate pending tasks after `sla_hours` window)

### Modified job: `_run_check_due_tasks`

- No change — due date reminders are independent from SLA
- Still runs every 30 minutes with cooldown via `follow_up_interval_hours`

---

## Frontend UI

### Settings page: new "SLA & Reminders" section

- **Global "Enable SLA Escalation" toggle** — master switch
- **Department reminder times** — table/list showing all departments:
  - Department name (read-only)
  - Reminder time (time picker HH:MM, or blank to disable)
  - SLA enabled toggle (per-department)
  - Save button per row (auto-saves via API)

### Tasks page: per-task SLA toggle

- **Create Task modal** — toggle "Auto-escalate via SLA" (default ON)
- **Edit Task modal** — same toggle, visible and editable
- **Task list card** — show SLA status icon (shield with checkmark if enabled, slash if disabled)

*Note: SOP pages unchanged. SOP tasks have their own escalation pipeline.*

## Files to Change

### Backend
- `backend/app/models/task.py` — add `sla_enabled` column
- `backend/app/models/department_config.py` — NEW: DepartmentConfig model
- `backend/app/services/scheduler.py` — add `_run_daily_reminders`, modify `_run_sla_check`
- `backend/app/routers/department_configs.py` — NEW: CRUD endpoints
- `backend/app/routers/tasks.py` — modify GET/POST/PUT to handle `sla_enabled`
- `backend/app/main.py` — register department_configs router
- `backend/app/database.py` — import DepartmentConfig model

### Frontend
- `frontend/src/pages/Settings.tsx` — add SLA & Reminders section (department configs table)
- `frontend/src/pages/Tasks.tsx` — add SLA toggle to create/edit modals + display
- `frontend/src/api/client.ts` — add department-configs API methods

---

## Implementation Order

1. Backend model changes (Task + new DepartmentConfig)
2. Backend API endpoints (department_configs CRUD + task changes)
3. Scheduler changes (new daily reminder job + SLA check modification)
4. Main.py router registration + database.py init
5. Frontend API client methods
6. Settings page UI (department configs table + global SLA toggle)
7. Tasks page UI (SLA toggle in modals + display)

---

## Edge Cases

- **Department without config entry**: default `sla_enabled=true`, no daily reminder
- **Employee in multiple departments**: each employee belongs to one department (current data model)
- **Reminder time midnight**: HH:MM format handles 00:00 correctly
- **No pending tasks for employee**: no message sent to that employee
- **No pending tasks for entire department**: no messages sent, `last_reminder_date` still updated so the check doesn't re-fire
- **SLA disabled globally**: scheduler skips entire SLA check, per-task setting irrelevant
- **SLA enabled globally but disabled per-task or per-department**: task skipped individually
- **Restart/rebuild**: department_configs persist in DB; `last_reminder_date` resets — may send one extra digest on restart day (acceptable, single message)
- **SOP tasks**: excluded from daily reminder via subquery against SOPExecution table; SOP has its own notification pipeline

## Migration

- `department_configs` table: created automatically by SQLAlchemy on startup (via init_db)
- Task `sla_enabled` column: new column, default `true` for existing rows via SQLAlchemy `server_default`
