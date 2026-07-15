# SOP Multi-Attachment Checklist — Design

**Date:** 2026-06-24
**Status:** Approved

## Problem

Some SOP tasks need several photo proofs, not one. Example: a cleaning SOP requires
separate photos for Production Floor, Cold Room, Side Wall, Machinery Cleaning,
Utensil Wash, Working Table, and Chemical Tins. Today a task has only a single
`requires_attachment` boolean, and the webhook merely checks that *one* photo
exists (it never even stores it). There is no way to require, track, or collect a
named set of photos.

## Goal

Let admins attach an ordered **checklist of named items** to an **SOP**. Each
generated SOP task then requires one photo per item. The employee submits photos
**sequentially** over WhatsApp; the bot tracks which items remain, blocks
completion until all are received, and on completion **forwards every photo plus a
status summary to the SOP's admin**. Photos are retained only until forwarded —
no dashboard gallery, no long-term archive.

## Scope

In scope:
- Checklist definition on **SOP only** (dashboard SOP create/edit form).
- SOP-generated tasks inherit the checklist and enforce it.
- Sequential photo collection + per-item tracking in the webhook.
- Completion forwarding to the SOP admin via WhatsApp.

Out of scope (explicitly):
- Checklists on one-off dashboard tasks or WhatsApp-assigned tasks.
- A dashboard photo gallery / served image store.
- Persisting images beyond forwarding.

## Data Model

### `SOPDefinition.attachment_checklist` (new)
- `Text`, nullable. JSON array of item-name strings, e.g.
  `["Production Floor","Cold Room","Side Wall","Machinery Cleaning"]`.
- Empty / null ⇒ checklist mode off (legacy single-photo `requires_attachment`
  behavior unchanged).

### `Task.attachment_checklist` (new)
- `Text`, nullable. Same JSON shape. **Carrier only** — copied from the SOP when
  the task is created. Not user-editable anywhere. Drives the webhook flow, since
  employees complete the generated Task, not the SOP.

### `task_attachments` (new table)
| column | type | notes |
|--------|------|-------|
| id | String(36) PK | uuid |
| task_id | FK tasks.id | |
| item_index | Integer | 0-based order in the checklist |
| item_label | String(200) | item name |
| status | String(20) | `pending` \| `received` (default `pending`) |
| media_base64 | Text, nullable | transient; nulled after forward |
| media_mimetype | String(100), nullable | e.g. `image/jpeg` |
| received_at | DateTime(tz), nullable | |
| forwarded_at | DateTime(tz), nullable | set when forwarded to admin |

Rows are **pre-created `pending`** (one per checklist item) when the task is
created. This makes ordering and "what is still missing" trivial DB queries.

### Migration
No-alembic style, consistent with existing `database.py` `_migrate_*` functions:
- add `sop_definitions.attachment_checklist TEXT`
- add `tasks.attachment_checklist TEXT`
- `Base.metadata.create_all` creates `task_attachments` (new table — created
  automatically; no ALTER needed).

## Flow

### Definition (frontend)
SOP create/edit form gains a dynamic "Attachment checklist" editor: a list of text
inputs with add/remove. Saved as the `attachment_checklist` array on the SOP.
Empty list ⇒ omit / null. The SOP router passes the field straight through to
`SOPService.create` / `.update` (both already accept arbitrary `data` dicts; just
include the new key in `update()`'s field allow-list).

### Task creation (`_create_task_for_sop`)
When a checklist SOP fires:
1. set `task.attachment_checklist = sop.attachment_checklist`
2. set `task.requires_attachment = True` (so existing gating short-circuits to the
   checklist path)
3. after `db.flush()`, insert one `TaskAttachment(status="pending")` per item with
   `item_index` / `item_label`.
The new-task WhatsApp message lists the required items.

### Submission (webhook — sequential)
Helper `find_active_checklist_task(employee)` = task assigned to employee, status
`pending`/`in_progress`, that has ≥1 `pending` task_attachments row, ordered by
most-recent `assigned_at` (tiebreak: most recently received attachment).

On an **inbound media** message:
1. If an active checklist task exists, take its lowest-`item_index` `pending` row:
   store `media_base64` + mimetype, set `status="received"`, `received_at=now`,
   set task `in_progress`.
2. Ack: `✅ Got "Cold Room" (2/7). Next: Side Wall` (or `🎉 All 7 received!`).
3. If that was the last pending row ⇒ mark task `done`, then forward (below).
4. If no active checklist task ⇒ fall through to existing single-attachment
   `_handle_task_done` behavior (unchanged).

On **`done`** (TASK_DONE intent) for a checklist task with missing items:
- reply `⚠️ Still need photos for: Side Wall, Utensil Wash, Working Table. Send
  them one at a time.` — do NOT complete. (Checked before the normal mark_done.)

### Completion forwarding
On checklist completion:
1. Recipient = `SOP.admin_id`'s employee. For SOP tasks the task's
   `assigned_by_id` is already set to `sop.admin_id or sop.assigned_to_id`, so use
   `task.assigned_by_id`; resolve to an employee.
2. Send a summary text: task title, station (`employee.department / employee.role`),
   employee name, `completed_at`, and a per-item `✓ <label> — <time>` list.
3. For each received attachment, send the image via OpenWA `send-image` with
   `base64` + `caption=item_label`. New `whatsapp.py` helper
   `send_whatsapp_media_base64(to, caption, base64, mimetype)`.
4. On success set `forwarded_at=now` and null `media_base64` (free the bytes).
5. If forwarding fails (admin unreachable / OpenWA error), leave `media_base64`
   intact and `forwarded_at` null; a periodic retry (piggybacked on an existing
   scheduler tick) re-attempts forwarding for tasks `done` with unforwarded
   received attachments.

## Components / boundaries

- `models/sop.py`, `models/task.py` — columns; new `TaskAttachment` model file
  `models/task_attachment.py`.
- `database.py` — migration calls + import of new model in `init_db`.
- `services/sop_service.py` — copy checklist onto task + pre-create rows;
  update() allow-list gains `attachment_checklist`.
- `services/attachment_service.py` (new, small) — the checklist state machine:
  `find_active_checklist_task`, `record_media`, `remaining_items`,
  `is_complete`, `forward_completed`. Keeps the webhook handler thin and the logic
  unit-testable in isolation.
- `services/whatsapp.py` — `send_whatsapp_media_base64`.
- `routers/webhook.py` — wire media + `done` into the attachment service.
- `routers/sops.py` — passthrough field (mostly already generic).
- `frontend/src/pages/SOPManage.tsx` — checklist editor; `api/client.ts` already
  posts the whole form object, so no client change beyond the form state.

## Error handling

- Media present but no active checklist task → existing single-photo path.
- Checklist SOP with an empty/whitespace item list → treated as no checklist
  (validation in the SOP form prevents blank items).
- OpenWA media payload missing base64 → record `received` with null base64 (still
  counts toward completion; forward step skips the image, notes "photo unavailable"
  in summary) so a flaky media fetch can't permanently block completion.
- Duplicate webhook delivery of the same photo → idempotency key dedupe already
  guards this upstream; additionally, filling only the lowest pending row means a
  retried delivery can at worst fill the next slot, never double-complete.

## Testing

- `attachment_service` unit tests: pre-create rows, record N photos in order,
  remaining-items text, completion detection, forward marks `forwarded_at` + nulls
  base64, forward-failure path keeps bytes.
- `_create_task_for_sop` copies checklist + creates pending rows.
- Webhook: media fills next slot + ack; `done` with missing items blocks.
- Migration idempotency (run twice, no error).

## Decisions (resolved during brainstorming)

- Model: **named checklist** (not count).
- Matching: **sequential prompt** (no captions).
- Storage: **transient** — track + forward, do not archive/serve.
- Recipients: **SOP admin / task assigner** only.
- Definition surface: **SOP only**.
