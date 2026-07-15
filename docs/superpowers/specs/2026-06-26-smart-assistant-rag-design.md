# Smart Assistant — RAG + Live-Ops Q&A + NLU Upgrade

**Date:** 2026-06-26
**Status:** Approved (design) → implementation pending
**Author:** Crusty Dev (with Claude)

## Problem

The WhatsApp bot's "smart" layer is effectively dead:

- `kb_documents` is **empty** (0 rows); the RAG/search path is unused.
- Embeddings are **broken under Groq**: provider is `groq` (llama-3.3-70b), `embedding_provider`
  defaults to groq, but Groq exposes no embeddings API. `KBService._get_embedding` falls back to
  the OpenAI client with the Groq key → fails → returns an all-zero vector. Every doc scores
  identically → semantic search is useless even once docs exist.
- **General questions get zero company context.** `webhook` HELP/else branches call
  `nlu.ask(body)` with no KB, no task data, no SOP roster → generic chatbot answers. The bot
  cannot answer "what are my tasks", "who cleans the kitchen floor", "kitne pending hai".
- Operational data (49 SOPs, 25 staff, 42 tasks) lives in Postgres but the bot never queries it
  to answer questions.

## Goal

Give the bot working memory of its own data: answer questions from **live operational data**
(tasks/SOPs/staff) and from **documents** (KB), with short conversational memory, and make the
command-parsing NLU context-aware.

## Decisions (locked)

- **Scope:** Both live-ops + documents (full RAG), built in phases.
- **Documents:** keyword / Postgres full-text search. **No embedding provider** added now (Groq
  has none; vectors deferred to a later phase).
- **Live-ops:** **curated query tools** only. No LLM-generated SQL (avoids injection / wrong-join /
  data-leak surface).
- **NLU upgrade** included (user-requested).

## Architecture & Data Flow

A new `assistant_service` becomes the single brain for any message that is not a clear command.
The `webhook` HELP/else branches stop calling `nlu.ask(body)` blind and instead call
`assistant.answer(question, employee, db, lang)`:

```
inbound general question
   │
   ├─ 1. OPS TOOLS   → LLM picks ONE curated tool (Groq JSON mode) → run safe parametrized query
   │                   permission-gated: employee = own data only; admin = everything
   │
   ├─ 2. DOC SEARCH  → Postgres full-text over kb_documents (ts_rank); ILIKE fallback
   │
   ├─ 3. MEMORY      → last ~6 turns from Redis (per employee, 30-min TTL)
   │
   └─ 4. SYNTHESIZE  → LLM gets {ops result + doc snippets + history} → answer in user's language
```

Live operational data is **never indexed/copied** — ops tools hit live tables, so answers are
always current. Documents are the only thing stored in the KB.

## Components

### A. `ops_tools.py` — curated, permission-gated lookups

Each returns a compact text block for the LLM. Permission is enforced **inside each tool**, not by
the caller — the LLM chooses only *which* tool + args and can never reach data the tool won't
return.

| Tool | Who | Returns |
|---|---|---|
| `my_pending_tasks` / `my_tasks_today` | all (self) | caller's open tasks |
| `task_lookup(query)` | all (self) | status of a named task |
| `who_owns_sop(name)` | all | SOP → assignee, schedule |
| `sop_schedule_today(dept?)` | all | today's SOP roster |
| `dept_pending_count(dept?)` | admin | open counts by dept |
| `overdue_tasks(dept?)` | admin | past-due list |
| `team_status` | admin | all pending by person |
| `staff_lookup(name)` | admin | role/dept/contact |

Non-admin callers: self-scoped tools only; admin-only tools return a polite refusal if selected for
a non-admin.

### B. `assistant_service.py` — orchestrator

Steps, each wrapped so one failure degrades gracefully:
1. **Tool selection** — Groq JSON mode returns `{"tool": str|null, "args": {...}}`. Keyword routing
   fallback if the LLM fails or returns no tool.
2. **Run tool** (if any) → ops context block.
3. **Doc search** — `KBService.search` (FTS).
4. **History** — Redis pull.
5. **Synthesize** — single LLM call with assembled context, answer in `lang`. If no ops result and
   no docs, fall back to a plain helpful answer (current behavior) rather than erroring.

### C. Doc search upgrade

Add a `tsvector` GIN index on `kb_documents.content` via a no-alembic `_migrate_*` function.
`KBService.search` uses `ts_rank` full-text ranking when embeddings are absent (the current case);
ILIKE remains the last-resort fallback. Embedding path is left intact for a future vector phase.

### D. Conversation memory

Redis key `chat:hist:{employee_id}`: rolling list of the last 6 turns (user + bot), 30-min TTL.
Written by the webhook on each handled general message; read by both `assistant_service` and
`nlu.parse`. Commands (assign/done) are not stored as history, but recent context is available to
resolve elliptical commands.

### E. NLU upgrades

1. **Memory-aware parse** — `nlu.parse` accepts recent history so elliptical/pronoun commands
   resolve: "assign it to him too", "same task for Raj", "make it high priority".
2. **LLM-first for ambiguous admin directives** — TASK_ASSIGN currently fires only on `@mention` or
   "assign to X". Widen LLM intent detection to admin directives lacking a clear mention; keyword
   path stays the fast default.
3. **Fuzzy target resolution** — nickname / partial / misspelling → employee ("@krsh", "krish from
   IT"). Ambiguous → bot asks which person.
4. **Auto priority & due** — infer from phrasing ("asap", "by tonight", "before lunch") via the
   existing verify step; keyword extractor as fallback.
5. **Attachment detection** — keep the expanded keyword set; LLM verify may also set
   `requires_attachment` (belt and suspenders).

## Phasing

Each phase ships independently and is verified before the next.

- **P1:** `ops_tools` + `assistant_service` + webhook wiring → live-ops Q&A working.
- **P2:** Postgres FTS doc search + KB populated with starter content.
- **P3:** Redis conversation memory (wired into assistant + nlu).
- **P4:** NLU upgrades (1–4 above).

## Error Handling

- Every tool / LLM call wrapped; tool failure → "couldn't fetch that right now".
- LLM unavailable → keyword fallback (parse) / plain answer (assistant).
- Permission denied → polite refusal, no data leak.
- All existing webhook behavior preserved when the assistant path returns nothing useful.

## Testing

- Unit-test each ops tool against seeded data, **including permission gating** (an employee cannot
  see another employee's tasks; admin-only tools refuse non-admins).
- Mock LLM tool-selection to assert routing + arg extraction.
- FTS ranking sanity test (relevant doc ranks above irrelevant).
- Memory TTL / rollover test.
- Regression: existing command intents (assign/done/status) unchanged.

## Out of Scope (deferred)

- Vector embeddings (needs an embedding provider/key or a local model).
- LLM-generated SQL.
- Cross-employee analytics dashboards (covered by existing `analytics` router/UI).
