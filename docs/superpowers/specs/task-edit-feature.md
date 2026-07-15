# Task Edit Feature

## Overview
Add edit capability for tasks via Dashboard (UI) and WhatsApp (command), with role-based permissions.

## Backend API

### PUT /api/tasks/{task_id}
Full task update endpoint.

**Auth:** Requires valid token. Admin can edit any field. Assigned employee can only edit status (in_progress, blocked).

**Request body** (all fields optional — only provided fields are updated):
```json
{
  "title": "string",
  "description": "string",
  "status": "pending | in_progress | done | blocked | escalated",
  "priority": "high | medium | low",
  "due_date": "YYYY-MM-DD | null",
  "assigned_to_id": "string (employee UUID)",
  "requires_attachment": true | false
}
```

**Logic:**
- Fetch existing task by ID
- If requester is not admin and not assigned employee → 403
- If requester is assigned employee and any field besides status is present → 403
- Merge provided fields (skip null/undefined)
- Set `due_date` to null if explicitly passed as null
- Save and return updated task
- After save, send WhatsApp notification to assigned employee (if task is assigned) summarizing changes
- Keep existing `PUT /tasks/{id}/status` for backward compatibility

**WhatsApp notification format** (when task is updated by admin):
```
📝 Task #2 updated:
  Title: Clean Kitchen → Deep Clean Kitchen
  Priority: Low → High
  Due: 2026-06-07
```

### Changes to existing endpoints
None required — new endpoint added alongside existing ones.

## WhatsApp Edit Command

### Format
```
edit task <number> <field> <value>
```

### Parsing
1. Match message starting with `edit task ` (case-insensitive)
2. Extract `<number>`: first token after prefix
3. Extract `<field>`: second token — maps to model field
4. Extract `<value>`: remaining text (allows spaces)
5. Validate field name, value, permissions

### Field mapping
| Command field | Model field | Allowed values |
|---|---|---|
| status | status | pending, in_progress, done, blocked, escalated |
| priority | priority | high, medium, low |
| due | due_date | tomorrow, today, YYYY-MM-DD, "clear" for null |
| title | title | any string |
| desc | description | any string |
| assign | assigned_to_id | employee name/phone lookup |

### Permission enforcement
| Requester | Editable fields |
|---|---|
| Admin | All |
| Assigned employee | status only (in_progress, blocked, done) |

### Due date parsing
- `tomorrow` → (today + 1 day) as YYYY-MM-DD
- `today` → today as YYYY-MM-DD
- `clear` or `none` → null
- `YYYY-MM-DD` → parse directly
- Any other → invalid

### Response messages
Success:
```
✅ Task #2 status updated to 'blocked'
```
Error:
```
❌ Invalid field. Options: status, priority, due, title, desc, assign
❌ Only admin can change priority
❌ Task #2 not found
❌ Invalid value for status. Allowed: pending, in_progress, done, blocked, escalated
```

## Dashboard Edit Modal

### Trigger
Click any task card → opens modal overlay.

### Modal fields
| Field | Control | Source |
|---|---|---|
| Title | Text input | Task title |
| Description | Textarea | Task description |
| Status | Dropdown | pending, in_progress, done, blocked, escalated |
| Priority | Dropdown | high, medium, low |
| Due Date | Date picker | Task due_date |
| Assignee | Dropdown | Employee list (GET /api/employees) |
| Requires Attachment | Checkbox | Task requires_attachment |

### Buttons
- **Save** → PUT /api/tasks/{task_id} → on success: close modal, refresh task list, show success toast
- **Cancel** → close modal

### State
- Loading while saving (disable buttons, show spinner)
- Error display if API fails (inline error message)

## Implementation Plan

### Phase 1: Backend (Python)
1. Add `TaskUpdate` pydantic schema in `schemas/task.py` with all fields optional
2. Add `update_task()` function in `services/task_manager.py`
3. Add PUT endpoint in `routers/tasks.py`
4. Add permission checks (admin vs assigned employee)
5. Add WhatsApp notification on update
6. Validate duedate parsing helper
7. Test via curl/Postman

### Phase 2: Dashboard (TypeScript/React)
1. Add `updateTask()` API call in `api/client.ts`
2. Create `EditTaskModal.tsx` component
3. Add click handler on task cards to open modal
4. Wire save button → API → refresh
5. Handle loading/error states

### Phase 3: WhatsApp Command
1. Add `handle_edit_command()` in webhook message handler
2. Add field/value parsing + validation
3. Add permission checks
4. Add due date parsing
5. Wire into existing message dispatch

## Files Changed
| File | Change |
|---|---|
| backend/app/schemas/task.py | Add TaskUpdate schema |
| backend/app/services/task_manager.py | Add update_task() |
| backend/app/routers/tasks.py | Add PUT endpoint |
| backend/app/routers/webhook.py | Handle edit task command |
| backend/app/utils/helpers.py | Add parse_due_date() |
| frontend/src/api/client.ts | Add updateTask() |
| frontend/src/pages/Tasks.tsx | Add edit modal trigger |
| frontend/src/components/EditTaskModal.tsx | New — modal component |
