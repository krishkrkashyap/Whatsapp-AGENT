# NLU Power Upgrade — Few-shot Intent + Web-Powered Answers + Conversation Memory

**Date:** 2026-06-27
**Status:** Approved (design) → implementation pending
**Branch:** feat/smart-assistant-rag
**Author:** Crusty Dev (with Claude)

## Problem

The bot's NLU under-uses the LLM and has no memory or live-web knowledge:

- **Keyword-first, LLM only on the HELP fallback.** Most messages never reach the
  LLM; intent is decided by keyword lists. Messy multilingual phrasings
  (Hindi/Hinglish/Gujarati) misroute.
- **Zero-shot prompt, no examples, no confidence.** When the LLM does run
  (`nlu.parse` HELP branch) it gets a bare instruction with no few-shot examples
  and returns no confidence — best practice is 3–10 same-language examples +
  structured JSON + a confidence gate.
- **No conversation memory.** Each message is stateless; "assign it to him too",
  "make it high priority", "same for Raj" cannot resolve.
- **No live web knowledge.** `nlu.webfetch` only summarizes an explicitly pasted
  URL. Groq (llama-3.3-70b) has no browsing, so questions like "aaj weather?" or
  "GST rate on bakery items?" get stale/guessed answers.

## Goal

Raise intent-routing accuracy on multilingual messages, let the bot answer
general/current questions from the web, and give it short conversational memory.

## Decisions (locked)

- **Few-shot + always-LLM intent**, keyword fast-path retained for unambiguous
  cases, confidence-gated fallback.
- **Web-powered answers** via **DuckDuckGo HTML** (no API key), summarized through
  the existing SSRF-safe fetch.
- **Conversation memory** in Redis, last 6 turns, 30-min TTL.
- Smarter entity extraction (fuzzy names, multi-assign) is OUT of scope this round.

## Component 1 — Few-shot + always-LLM intent (`app/services/nlu.py`)

Current `parse(text, employee_name, is_admin)` runs `_keyword_parse` first and
only calls the LLM when the keyword intent is `HELP`. Change:

1. **Keyword fast-path stays** for unambiguous, high-precision cases ONLY:
   - done command (`helpers.is_done_command`)
   - task assign with an `@mention` or explicit "assign/task/delegate to <name>"
   - register keywords
   When the fast-path matches one of these, return it without the LLM (instant,
   reliable, already battle-tested).
2. **Everything else → few-shot LLM.** Add a module constant `_FEWSHOT`: ~8
   labeled examples covering every intent, spanning English / Hinglish / Hindi /
   Gujarati, e.g.:
   - `@Raj kal tak server theek karo` → TASK_ASSIGN
   - `mera kaam ho gaya` → TASK_DONE
   - `samajh nahi aaya kaise karu` → TROUBLE_HELP
   - `mere pending tasks batao` → STATUS_CHECK
   - `sabka status do` → FOLLOW_UP (admin)
   - `mujhe add karo naam Raj` → REGISTER
   - `aaj weather kya hai` → HELP (general question)
   - `commands batao` → HELP
   Injected into the existing JSON-mode prompt.
3. **Confidence gate.** Prompt requests `"confidence": 0.0–1.0`. If the LLM
   response is invalid, intent not in `_VALID_INTENTS`, or `confidence < 0.55`,
   fall back to the keyword result. (`_VALID_INTENTS` already exists.)
4. The LLM result remains the existing JSON shape (`intent`, `language`,
   `entities`) plus `confidence`. No new caller contract.

Latency: Groq llama-3.3-70b is fast; the fast-path still short-circuits the
highest-volume commands (done/assign), so only ambiguous messages pay the LLM
round-trip.

## Component 2 — Web-powered answers (`app/services/web_search.py`, new)

1. `search(query: str, max_results: int = 3) -> list[dict]` — GET
   `https://html.duckduckgo.com/html/?q=<query>` with a browser User-Agent, parse
   result anchors (`a.result__a` href + snippet text) into
   `[{title, url, snippet}]`. Decode DuckDuckGo's `/l/?uddg=` redirect wrapper to
   the real URL. Wrapped in try/except → `[]` on failure.
2. `answer(query: str, language: str) -> str` — run `search`; for the top 1–2
   results whose URL passes `nlu._is_safe_url`, fetch+clean via the existing
   `nlu.webfetch` text path; concatenate snippets + fetched text as context and
   summarize via `nlu.ask(query, context, language)`. If nothing usable, return
   `""` (caller falls back).
3. **Wiring** in `assistant_service.answer`: after the ops-tool phase yields no
   `ops_context`, decide if the question wants the web — a lightweight check
   (`?`, question words who/what/when/where/why/how/kya/kaise/kab/kitna/kyu,
   or current-info markers weather/price/rate/news/today/aaj). If so, try
   `web_search.answer`; on non-empty, synthesize with it; else fall back to the
   current plain `nlu.ask`.
4. **Security:** only fetch result URLs that pass `_is_safe_url` (blocks
   private/loopback/metadata IPs — already implemented). No fetch of
   DuckDuckGo-internal/relative links.

## Component 3 — Conversation memory (`app/services/chat_memory.py`, new)

1. `append(employee_id, role, text)` — push `{role, text}` to Redis list
   `chat:hist:{employee_id}`, trim to last 12 entries (≈6 turns), refresh TTL
   1800s. `role` ∈ {"user","bot"}. Fails silently if Redis down.
2. `recent(employee_id, limit=6) -> list[dict]` — return the last `limit` turns
   oldest-first, `[]` on miss/error.
3. `format_for_prompt(employee_id) -> str` — compact transcript
   ("User: …\nBot: …") for prompt injection, `""` when empty.
4. **Wiring:**
   - `webhook`: after handling a general message (HELP/assistant branches),
     `append(emp, "user", body)` and `append(emp, "bot", reply)`.
   - `nlu.parse`: accept an optional `history: str = ""` param; when present,
     prepend it to the few-shot prompt so elliptical commands resolve. Webhook
     passes `chat_memory.format_for_prompt(employee.id)`.
   - `assistant_service.answer`: accept optional `history` and include it in the
     synthesis prompt context.
   - Commands (done/assign) need not be stored, but storing the general Q&A pair
     is enough to resolve the common follow-ups.

## Error Handling

- Every LLM / HTTP / Redis call wrapped. Intent LLM failure → keyword result.
  Web search failure → plain `nlu.ask`. Redis failure → stateless (no history).
- No new user-visible errors; all paths degrade to current behavior.

## Testing

- **Intent:** mock `_call_llm` — assert few-shot routing for ambiguous messages,
  confidence-gate fallback to keyword on low confidence / invalid intent, and
  fast-path short-circuit (done/assign) does NOT call the LLM. Keyword regression
  stays green.
- **Web search:** mock DuckDuckGo HTML → assert parsing yields correct
  title/url/snippet and decodes the `uddg` redirect; assert `_is_safe_url`
  rejects a private-IP result; `search` returns `[]` on HTTP error.
- **Memory:** append/trim to 12, `recent` ordering, TTL set, graceful empty on
  Redis miss.
- **Assistant wiring:** with no ops tool + a factual question, `answer` calls web
  search and passes its text as context (mock both).

## Phasing

- **P4a:** few-shot + always-LLM intent (+ confidence gate).
- **P4b:** `web_search` module + assistant wiring.
- **P4c:** `chat_memory` module + parse/assistant/webhook wiring.

Each phase ships and is verified independently.

## Out of Scope (deferred)

- Fuzzy name matching / multi-assignee commands / advanced entity extraction.
- Paid search APIs (Tavily/Serper/Brave) — DuckDuckGo no-key for now.
- Vector embeddings / KB document RAG (separate P2 plan).
