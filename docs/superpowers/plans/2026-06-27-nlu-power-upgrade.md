# NLU Power Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Raise multilingual intent accuracy (few-shot + always-LLM with a confidence gate), let the bot answer general/current questions from the web (DuckDuckGo, no key), and give it short Redis conversation memory.

**Architecture:** `nlu.parse` keeps an instant keyword fast-path only for unambiguous commands and routes everything else to a few-shot JSON LLM call gated by confidence. A new `web_search` module scrapes DuckDuckGo HTML and summarizes top hits through the existing SSRF-safe fetch, wired into `assistant_service.answer` as a fallback. A new `chat_memory` module stores the last few turns per employee in Redis and feeds both `parse` and the assistant.

**Tech Stack:** FastAPI, SQLAlchemy (SQLite in tests), pytest, Groq llama-3.3-70b via `NLUService`, Redis, httpx.

## Global Constraints

- Keyword fast-path retained for unambiguous cases; confidence-gated fallback to keyword. (verbatim from spec)
- Web search via DuckDuckGo HTML, no API key. (verbatim from spec)
- Only fetch result URLs that pass `nlu._is_safe_url` (blocks private/loopback/metadata). (verbatim from spec)
- Every LLM / HTTP / Redis call wrapped; all paths degrade to current behavior. (verbatim from spec)
- Conversation memory: last 6 turns (12 entries), 30-min (1800s) TTL. (verbatim from spec)
- Confidence threshold for accepting an LLM intent: `>= 0.55`. (verbatim from spec)

## Test loop (no image rebuild per iteration)

Backend image has no source mount. Copy changed files into the running container, then run pytest with PYTHONPATH:

```bash
docker cp backend/app/services/nlu.py crusty-backend:/app/app/services/nlu.py
docker cp backend/tests/test_nlu_intent.py crusty-backend:/app/tests/test_nlu_intent.py
MSYS_NO_PATHCONV=1 docker exec -w /app -e PYTHONPATH=/app crusty-backend pytest tests/test_nlu_intent.py -v
```
Final deploy at end: `docker compose build backend && docker compose up -d backend`.

## File Structure

- Modify: `backend/app/services/nlu.py` — few-shot `_FEWSHOT`, reworked `parse()` (widen LLM, confidence, optional `history`).
- Create: `backend/app/services/web_search.py` — DuckDuckGo `search()` + `answer()`.
- Create: `backend/app/services/chat_memory.py` — Redis `append`/`recent`/`format_for_prompt`.
- Modify: `backend/app/services/assistant_service.py` — web-search fallback + optional `history`.
- Modify: `backend/app/routers/webhook.py` — record turns; pass history to parse + assistant.
- Create tests: `backend/tests/test_nlu_intent.py`, `test_web_search.py`, `test_chat_memory.py`.

## Reference (read-only)

- `NLUService.parse(text, employee_name="", is_admin=False) -> dict` returns `{intent, language, entities}`. Currently calls `_keyword_parse` first; LLM only when keyword intent == "HELP".
- `NLUService._keyword_parse` returns `TASK_ASSIGN` only when an @mention / "assign to" is present AND is_admin; `TASK_DONE` only via `helpers.is_done_command`; `REGISTER` via register words; otherwise TROUBLE_HELP/STATUS_CHECK/FOLLOW_UP/HELP.
- `NLUService._VALID_INTENTS` = {TASK_ASSIGN, TASK_DONE, TROUBLE_HELP, FOLLOW_UP, STATUS_CHECK, REGISTER, HELP}.
- `NLUService._call_llm(prompt, json_mode=False) -> str`, `.ask(question, context="", language="english") -> str`, `._is_safe_url(url) -> bool`, `.webfetch(url) -> str`, `.api_key`.
- `assistant_service.answer(question, employee, db, language="english") -> str`; `select_tool`, `ops_tools.dispatch`.
- `settings.redis_url`.

---

### Task 1: Few-shot + always-LLM intent with confidence gate

**Files:**
- Modify: `backend/app/services/nlu.py` (`parse`, add `_FEWSHOT`)
- Test: `backend/tests/test_nlu_intent.py`

**Interfaces:**
- Produces: `NLUService.parse(text, employee_name="", is_admin=False, history="") -> dict` — adds optional `history` param and a `confidence` key in the LLM path. Behavior: keyword fast-path returns immediately for `TASK_ASSIGN`/`TASK_DONE`/`REGISTER`; all other messages go to the few-shot LLM; LLM result accepted only if intent ∈ `_VALID_INTENTS` and `confidence >= 0.55`, else keyword result.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_nlu_intent.py`:

```python
from app.services.nlu import nlu_service as ns


def test_fastpath_done_skips_llm(monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(ns, "api_key", "x")
    monkeypatch.setattr(ns, "_call_llm", lambda *a, **k: called.__setitem__("n", called["n"] + 1) or "{}")
    out = ns.parse("ho gaya", "Krish", False)
    assert out["intent"] == "TASK_DONE"
    assert called["n"] == 0  # fast-path, no LLM


def test_fastpath_assign_skips_llm(monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(ns, "api_key", "x")
    monkeypatch.setattr(ns, "_call_llm", lambda *a, **k: called.__setitem__("n", called["n"] + 1) or "{}")
    out = ns.parse("@Raj fix the oven", "Admin", True)
    assert out["intent"] == "TASK_ASSIGN"
    assert called["n"] == 0


def test_ambiguous_uses_llm(monkeypatch):
    monkeypatch.setattr(ns, "api_key", "x")
    monkeypatch.setattr(ns, "_call_llm",
        lambda *a, **k: '{"intent":"STATUS_CHECK","language":"hinglish","entities":{},"confidence":0.9}')
    out = ns.parse("bhai mera kaam kitna bacha hai", "Krish", False)
    assert out["intent"] == "STATUS_CHECK"


def test_low_confidence_falls_back_to_keyword(monkeypatch):
    monkeypatch.setattr(ns, "api_key", "x")
    monkeypatch.setattr(ns, "_call_llm",
        lambda *a, **k: '{"intent":"TASK_ASSIGN","language":"english","entities":{},"confidence":0.2}')
    out = ns.parse("can you help me understand this", "Krish", False)
    assert out["intent"] != "TASK_ASSIGN"  # low confidence rejected -> keyword (TROUBLE_HELP/HELP)


def test_invalid_intent_falls_back(monkeypatch):
    monkeypatch.setattr(ns, "api_key", "x")
    monkeypatch.setattr(ns, "_call_llm",
        lambda *a, **k: '{"intent":"GARBAGE","language":"english","entities":{},"confidence":0.99}')
    out = ns.parse("random chatter here", "Krish", False)
    assert out["intent"] in ns._VALID_INTENTS


def test_no_api_key_uses_keyword(monkeypatch):
    monkeypatch.setattr(ns, "api_key", "")
    out = ns.parse("mujhe add karo naam Raj", "Raj", False)
    assert out["intent"] == "REGISTER"
```

- [ ] **Step 2: Run to verify it fails**

Run:
```bash
docker cp backend/tests/test_nlu_intent.py crusty-backend:/app/tests/test_nlu_intent.py
MSYS_NO_PATHCONV=1 docker exec -w /app -e PYTHONPATH=/app crusty-backend pytest tests/test_nlu_intent.py -v
```
Expected: FAILs — `test_ambiguous_uses_llm` (keyword currently returns its own intent without LLM) and `test_fastpath_*` may pass by luck; at least the ambiguous/low-confidence tests fail because `parse` has no confidence gate and returns keyword for non-HELP.

- [ ] **Step 3: Add the few-shot constant**

In `backend/app/services/nlu.py`, add as a class attribute on `NLUService` (right after `_VALID_INTENTS`):

```python
    _FEWSHOT = """Examples (message -> intent):
"@Raj kal tak server theek karo" -> TASK_ASSIGN
"assign cleaning to Sapna every 2 hours" -> TASK_ASSIGN
"mera kaam ho gaya" -> TASK_DONE
"done 2" -> TASK_DONE
"samajh nahi aaya kaise karu" -> TROUBLE_HELP
"machine kaam nahi kar rahi" -> TROUBLE_HELP
"mere pending tasks batao" -> STATUS_CHECK
"kya karna hai aaj" -> STATUS_CHECK
"sabka status do" -> FOLLOW_UP
"mujhe add karo naam Raj" -> REGISTER
"aaj weather kya hai" -> HELP
"GST rate on bakery items?" -> HELP
"commands batao" -> HELP
"""
```

- [ ] **Step 4: Rework `parse`**

Replace the whole `parse` method body in `backend/app/services/nlu.py` with:

```python
    def parse(self, text: str, employee_name: str = "", is_admin: bool = False,
              history: str = "") -> dict:
        """Parse incoming message. Returns intent, language, entities.

        Keyword fast-path handles unambiguous commands (assign with mention, done,
        register) instantly. Everything else goes to a few-shot LLM call whose
        result is accepted only when valid and confident; otherwise the keyword
        result stands.
        """
        keyword_result = self._keyword_parse(text, employee_name, is_admin)
        kw_intent = keyword_result.get("intent", "HELP")

        # High-precision keyword intents short-circuit the LLM (fast + reliable).
        if kw_intent in ("TASK_ASSIGN", "TASK_DONE", "REGISTER"):
            return keyword_result

        # Ambiguous (TROUBLE_HELP / STATUS_CHECK / FOLLOW_UP / HELP) — ask the LLM.
        if not self.api_key:
            return keyword_result

        hist_block = f"\nRecent conversation (for context):\n{history}\n" if history else ""
        system_prompt = f"""You are a task management assistant for an internal company WhatsApp bot.
Parse the employee message and extract intent and entities.

Available intents:
- TASK_ASSIGN: Admin assigning a task (real @mention or explicit "assign to"). Extract follow-up intervals ("every 30 min", "har 2 ghante").
- TASK_DONE: Employee confirming completion ("done", "ho gaya", "kar diya").
- TROUBLE_HELP: Employee stuck/needs help ("stuck", "error", "samajh nahi aaya", "kaise", "problem").
- FOLLOW_UP: Asking about task status ("follow up", "status", "sabka status").
- STATUS_CHECK: Employee asking their own tasks ("my tasks", "pending", "kya karna hai").
- REGISTER: New user wanting to register ("register", "add me", "mujhe add karo").
- HELP: Command list OR a general/world question (weather, prices, general chat).

CRITICAL: Only TASK_ASSIGN if a real @mention or "assign to" phrase is present. Domain names are not @mentions. General/world questions are HELP.
For TASK_ASSIGN with "every X min/hour" / "har X minute/ghanta": follow_up_type="periodic", interval_hours=decimal hours (30 min=0.5, 2 hours=2.0).

{self._FEWSHOT}{hist_block}
Respond in JSON ONLY:
- "intent": one of the intents above
- "language": "hindi"|"english"|"hinglish"|"gujarati"|"gujlish"
- "confidence": 0.0 to 1.0 (how sure you are of the intent)
- "entities": {{"target_name": str|null, "task_description": str|null, "priority": "high"|"medium"|"low"|null, "due_date": str|null, "follow_up_type": "periodic"|null, "interval_hours": number|null, "register_name": str|null}}

Message from {employee_name} (is_admin={is_admin}): {text}"""

        try:
            raw = self._call_llm(system_prompt, json_mode=True)
            parsed = json.loads(raw)
            llm_intent = parsed.get("intent", "HELP")
            confidence = parsed.get("confidence", 1.0)
            try:
                confidence = float(confidence)
            except (TypeError, ValueError):
                confidence = 0.0
            if llm_intent not in self._VALID_INTENTS or confidence < 0.55:
                logger.info("LLM intent rejected (intent=%s conf=%s) -> keyword", llm_intent, confidence)
                return keyword_result
            return parsed
        except Exception as e:
            logger.warning(f"NLU API error: {e}")
            return keyword_result
```

- [ ] **Step 5: Run tests to verify they pass**

Run:
```bash
docker cp backend/app/services/nlu.py crusty-backend:/app/app/services/nlu.py
docker cp backend/tests/test_nlu_intent.py crusty-backend:/app/tests/test_nlu_intent.py
MSYS_NO_PATHCONV=1 docker exec -w /app -e PYTHONPATH=/app crusty-backend pytest tests/test_nlu_intent.py -v
```
Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/nlu.py backend/tests/test_nlu_intent.py
git commit -m "feat(nlu): few-shot always-LLM intent with confidence gate"
```

---

### Task 2: DuckDuckGo search module

**Files:**
- Create: `backend/app/services/web_search.py`
- Test: `backend/tests/test_web_search.py`

**Interfaces:**
- Produces: `search(query: str, max_results: int = 3) -> list[dict]` returning `[{"title","url","snippet"}]`; decodes DuckDuckGo `/l/?uddg=` redirect wrappers to the real URL; `[]` on any error.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_web_search.py`:

```python
from urllib.parse import quote
from app.services import web_search


_HTML = '''
<div class="result">
  <a class="result__a" href="//duckduckgo.com/l/?uddg={u}&rut=x">Weather Today</a>
  <a class="result__snippet">It is 31C and sunny.</a>
</div>
<div class="result">
  <a class="result__a" href="//duckduckgo.com/l/?uddg={p}">Private</a>
  <a class="result__snippet">internal</a>
</div>
'''.format(u=quote("https://weather.example.com/today", safe=""),
           p=quote("http://169.254.169.254/latest", safe=""))


def test_search_parses_and_decodes(monkeypatch):
    class R:
        status_code = 200
        text = _HTML
    monkeypatch.setattr(web_search.httpx, "get", lambda *a, **k: R())
    res = web_search.search("weather today")
    assert res[0]["title"] == "Weather Today"
    assert res[0]["url"] == "https://weather.example.com/today"
    assert "sunny" in res[0]["snippet"]


def test_search_empty_on_http_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network down")
    monkeypatch.setattr(web_search.httpx, "get", boom)
    assert web_search.search("x") == []
```

- [ ] **Step 2: Run to verify it fails**

Run:
```bash
docker cp backend/tests/test_web_search.py crusty-backend:/app/tests/test_web_search.py
MSYS_NO_PATHCONV=1 docker exec -w /app -e PYTHONPATH=/app crusty-backend pytest tests/test_web_search.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.web_search'`.

- [ ] **Step 3: Implement `search`**

Create `backend/app/services/web_search.py`:

```python
"""Keyless web search via DuckDuckGo's HTML endpoint.

Used to answer general/current questions the LLM cannot know (Groq has no
browsing). Result URLs are fetched only after passing nlu._is_safe_url, so the
SSRF protection of the existing webfetch path applies here too.
"""
import re
import logging
from urllib.parse import quote_plus, unquote, urlparse, parse_qs
import httpx

logger = logging.getLogger("web_search")

_ENDPOINT = "https://html.duckduckgo.com/html/"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# Matches each result anchor and the following snippet anchor.
_RESULT_RE = re.compile(
    r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_SNIPPET_RE = re.compile(
    r'class="result__snippet"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")


def _strip(html: str) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub("", html)).strip()


def _real_url(href: str) -> str:
    """Decode DuckDuckGo's /l/?uddg=<encoded> redirect wrapper."""
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        q = parse_qs(parsed.query)
        if "uddg" in q:
            return unquote(q["uddg"][0])
    return href


def search(query: str, max_results: int = 3) -> list:
    """Return up to max_results [{title,url,snippet}] for the query. [] on error."""
    try:
        resp = httpx.get(
            f"{_ENDPOINT}?q={quote_plus(query)}",
            headers={"User-Agent": _UA}, timeout=12, follow_redirects=True,
        )
        if resp.status_code != 200:
            return []
        anchors = _RESULT_RE.findall(resp.text)
        snippets = _SNIPPET_RE.findall(resp.text)
        out = []
        for i, (href, title) in enumerate(anchors[:max_results]):
            out.append({
                "title": _strip(title),
                "url": _real_url(href),
                "snippet": _strip(snippets[i]) if i < len(snippets) else "",
            })
        return out
    except Exception as e:
        logger.warning("DuckDuckGo search failed: %s", e)
        return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
docker cp backend/app/services/web_search.py crusty-backend:/app/app/services/web_search.py
MSYS_NO_PATHCONV=1 docker exec -w /app -e PYTHONPATH=/app crusty-backend pytest tests/test_web_search.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/web_search.py backend/tests/test_web_search.py
git commit -m "feat(search): keyless DuckDuckGo HTML search"
```

---

### Task 3: web_search.answer() + assistant wiring

**Files:**
- Modify: `backend/app/services/web_search.py` (add `answer`)
- Modify: `backend/app/services/assistant_service.py` (`answer` web fallback)
- Test: `backend/tests/test_web_search.py`, `backend/tests/test_assistant_service.py`

**Interfaces:**
- Produces: `web_search.answer(query: str, language: str = "english") -> str` — searches, fetches the top 1–2 SSRF-safe results via `nlu.webfetch`, summarizes via `nlu.ask`; `""` when nothing usable.
- Consumes (assistant): `web_search.answer`. `assistant_service.answer` gains a private `_wants_web(question) -> bool` and calls web search only when no ops tool produced context AND `_wants_web` is true.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_web_search.py`:

```python
def test_answer_summarizes_safe_results(monkeypatch):
    monkeypatch.setattr(web_search, "search",
        lambda q, max_results=3: [{"title": "T", "url": "https://ok.example.com", "snippet": "31C sunny"}])
    from app.services.nlu import nlu_service
    monkeypatch.setattr(nlu_service, "_is_safe_url", lambda u: True)
    monkeypatch.setattr(nlu_service, "webfetch", lambda u: "Full weather page text")
    monkeypatch.setattr(nlu_service, "ask", lambda q, context="", language="english": "It is 31C and sunny.")
    out = web_search.answer("weather today", "english")
    assert "sunny" in out.lower()


def test_answer_empty_when_no_results(monkeypatch):
    monkeypatch.setattr(web_search, "search", lambda q, max_results=3: [])
    assert web_search.answer("zzz", "english") == ""
```

Append to `backend/tests/test_assistant_service.py`:

```python
def test_answer_uses_web_when_no_tool(monkeypatch, db):
    from app.models.employee import Employee
    e = Employee(name="Krish", department="IT", role="Staff",
                 whatsapp_number="+910003", is_admin=False)
    db.add(e); db.commit(); db.refresh(e)
    import app.services.web_search as ws
    monkeypatch.setattr(asv.nlu_service, "api_key", "")  # force keyword route -> no tool
    called = {"web": 0}
    monkeypatch.setattr(ws, "answer",
        lambda q, language="english": called.__setitem__("web", 1) or "WEB ANSWER")
    out = asv.answer("what is the GST rate on bakery items?", e, db)
    assert out == "WEB ANSWER"
    assert called["web"] == 1


def test_answer_no_web_for_plain_chat(monkeypatch, db):
    from app.models.employee import Employee
    e = Employee(name="Krish", department="IT", role="Staff",
                 whatsapp_number="+910004", is_admin=False)
    db.add(e); db.commit(); db.refresh(e)
    import app.services.web_search as ws
    monkeypatch.setattr(asv.nlu_service, "api_key", "")
    monkeypatch.setattr(ws, "answer", lambda q, language="english": "SHOULD NOT BE CALLED")
    monkeypatch.setattr(asv.nlu_service, "ask", lambda q, context="", language="english": "HI THERE")
    out = asv.answer("hello", e, db)
    assert out == "HI THERE"
```

- [ ] **Step 2: Run to verify they fail**

Run:
```bash
docker cp backend/tests/test_web_search.py crusty-backend:/app/tests/test_web_search.py
docker cp backend/tests/test_assistant_service.py crusty-backend:/app/tests/test_assistant_service.py
MSYS_NO_PATHCONV=1 docker exec -w /app -e PYTHONPATH=/app crusty-backend pytest tests/test_web_search.py tests/test_assistant_service.py -v
```
Expected: FAIL — `web_search.answer` missing; assistant has no web fallback.

- [ ] **Step 3: Implement `web_search.answer`**

Append to `backend/app/services/web_search.py`:

```python
def answer(query: str, language: str = "english") -> str:
    """Search + summarize. Fetches the top 1-2 SSRF-safe results and asks the LLM
    to answer in the user's language. Returns '' when nothing usable."""
    from app.services.nlu import nlu_service
    results = search(query, max_results=3)
    if not results:
        return ""
    parts = []
    fetched = 0
    for r in results:
        parts.append(f"{r['title']}: {r['snippet']}")
        if fetched < 2 and r["url"] and nlu_service._is_safe_url(r["url"]):
            try:
                page = nlu_service.webfetch(r["url"])
                if page and not page.startswith("❌"):
                    parts.append(page[:1500])
                    fetched += 1
            except Exception:
                pass
    context = "\n\n".join(parts).strip()
    if not context:
        return ""
    try:
        return nlu_service.ask(query, context=context, language=language)
    except Exception:
        return ""
```

- [ ] **Step 4: Wire into the assistant**

In `backend/app/services/assistant_service.py`, add the import near the top (with the other service imports):

```python
from app.services import web_search
```

Add this helper above `answer`:

```python
_WEB_MARKERS = ("?", "weather", "price", "rate", "news", "today", "aaj",
                "kitna", "kitni", "kaun", "kab", "kyu", "kyun",
                "what", "who", "when", "where", "why", "how", "kya", "kaise")


def _wants_web(question: str) -> bool:
    """Heuristic: does this look like a factual/world question worth a web lookup?"""
    q = (question or "").lower()
    return any(m in q for m in _WEB_MARKERS)
```

Then in `answer`, replace the synthesize block:

```python
    try:
        if ops_context:
            return nlu_service.ask(question, context=ops_context, language=language)
        return nlu_service.ask(question, language=language)
    except Exception as e:
        logger.warning("assistant synthesize failed: %s", e)
        return ops_context or "Sorry, I couldn't process that right now."
```

with:

```python
    # No ops data — if it looks like a factual/world question, try the web.
    if not ops_context and _wants_web(question):
        try:
            web = web_search.answer(question, language=language)
            if web:
                return web
        except Exception as e:
            logger.warning("assistant web phase failed: %s", e)

    try:
        if ops_context:
            return nlu_service.ask(question, context=ops_context, language=language)
        return nlu_service.ask(question, language=language)
    except Exception as e:
        logger.warning("assistant synthesize failed: %s", e)
        return ops_context or "Sorry, I couldn't process that right now."
```

- [ ] **Step 5: Run tests to verify they pass**

Run:
```bash
docker cp backend/app/services/web_search.py crusty-backend:/app/app/services/web_search.py
docker cp backend/app/services/assistant_service.py crusty-backend:/app/app/services/assistant_service.py
docker cp backend/tests/test_web_search.py crusty-backend:/app/tests/test_web_search.py
docker cp backend/tests/test_assistant_service.py crusty-backend:/app/tests/test_assistant_service.py
MSYS_NO_PATHCONV=1 docker exec -w /app -e PYTHONPATH=/app crusty-backend pytest tests/test_web_search.py tests/test_assistant_service.py -v
```
Expected: all passed (web_search 4, assistant 8).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/web_search.py backend/app/services/assistant_service.py backend/tests/test_web_search.py backend/tests/test_assistant_service.py
git commit -m "feat(assistant): web-powered answers via DuckDuckGo fallback"
```

---

### Task 4: Conversation memory module

**Files:**
- Create: `backend/app/services/chat_memory.py`
- Test: `backend/tests/test_chat_memory.py`

**Interfaces:**
- Produces: `append(employee_id, role, text)`, `recent(employee_id, limit=6) -> list[dict]` (oldest-first, `[{role,text}]`), `format_for_prompt(employee_id) -> str`. Backed by Redis list `chat:hist:{id}`, trimmed to 12 entries, TTL 1800s. A module-level `_redis()` returns the client; tests monkeypatch it. All functions fail silently / return empty on Redis error.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_chat_memory.py`:

```python
from app.services import chat_memory


class FakeRedis:
    def __init__(self):
        self.store = {}
        self.ttl = {}
    def rpush(self, k, v):
        self.store.setdefault(k, []).append(v)
    def ltrim(self, k, start, end):
        if k in self.store:
            self.store[k] = self.store[k][start:] if end == -1 else self.store[k][start:end + 1]
    def lrange(self, k, start, end):
        lst = self.store.get(k, [])
        return lst[start:] if end == -1 else lst[start:end + 1]
    def expire(self, k, secs):
        self.ttl[k] = secs


def test_append_and_recent(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(chat_memory, "_redis", lambda: fake)
    chat_memory.append("e1", "user", "hello")
    chat_memory.append("e1", "bot", "hi")
    out = chat_memory.recent("e1")
    assert out == [{"role": "user", "text": "hello"}, {"role": "bot", "text": "hi"}]
    assert fake.ttl["chat:hist:e1"] == 1800


def test_trim_to_12(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(chat_memory, "_redis", lambda: fake)
    for i in range(20):
        chat_memory.append("e1", "user", f"m{i}")
    stored = fake.store["chat:hist:e1"]
    assert len(stored) == 12
    assert chat_memory.recent("e1", limit=6)[-1]["text"] == "m19"


def test_format_for_prompt(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(chat_memory, "_redis", lambda: fake)
    chat_memory.append("e1", "user", "assign to raj")
    chat_memory.append("e1", "bot", "done")
    s = chat_memory.format_for_prompt("e1")
    assert "User: assign to raj" in s and "Bot: done" in s


def test_graceful_when_redis_down(monkeypatch):
    def boom():
        raise RuntimeError("no redis")
    monkeypatch.setattr(chat_memory, "_redis", boom)
    chat_memory.append("e1", "user", "x")   # must not raise
    assert chat_memory.recent("e1") == []
    assert chat_memory.format_for_prompt("e1") == ""
```

- [ ] **Step 2: Run to verify it fails**

Run:
```bash
docker cp backend/tests/test_chat_memory.py crusty-backend:/app/tests/test_chat_memory.py
MSYS_NO_PATHCONV=1 docker exec -w /app -e PYTHONPATH=/app crusty-backend pytest tests/test_chat_memory.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.chat_memory'`.

- [ ] **Step 3: Implement**

Create `backend/app/services/chat_memory.py`:

```python
"""Short per-employee conversation memory in Redis.

Stores the last few turns so elliptical follow-ups ("assign it to him too",
"make it high priority") can be resolved. Best-effort: any Redis failure
degrades to stateless behavior.
"""
import json
import logging
from app.config import settings

logger = logging.getLogger("chat_memory")

_KEY = "chat:hist:{}"
_MAX = 12          # ~6 turns (user+bot)
_TTL = 1800        # 30 minutes


def _redis():
    import redis
    return redis.from_url(settings.redis_url, socket_timeout=3, decode_responses=True)


def append(employee_id: str, role: str, text: str) -> None:
    if not text:
        return
    try:
        r = _redis()
        key = _KEY.format(employee_id)
        r.rpush(key, json.dumps({"role": role, "text": text[:1000]}))
        r.ltrim(key, -_MAX, -1)
        r.expire(key, _TTL)
    except Exception as e:
        logger.warning("chat_memory append failed for %s: %s", employee_id, e)


def recent(employee_id: str, limit: int = 6) -> list:
    try:
        r = _redis()
        raw = r.lrange(_KEY.format(employee_id), -limit, -1)
        out = []
        for item in raw:
            try:
                out.append(json.loads(item))
            except (ValueError, TypeError):
                pass
        return out
    except Exception as e:
        logger.warning("chat_memory recent failed for %s: %s", employee_id, e)
        return []


def format_for_prompt(employee_id: str, limit: int = 6) -> str:
    turns = recent(employee_id, limit)
    if not turns:
        return ""
    lines = []
    for t in turns:
        who = "User" if t.get("role") == "user" else "Bot"
        lines.append(f"{who}: {t.get('text', '')}")
    return "\n".join(lines)
```

Note: `recent` returns at most `limit` entries; `test_trim_to_12` asserts the stored list (via `ltrim`) is 12, and `recent("e1", limit=6)` returns the last 6 ending at `m19`.

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
docker cp backend/app/services/chat_memory.py crusty-backend:/app/app/services/chat_memory.py
MSYS_NO_PATHCONV=1 docker exec -w /app -e PYTHONPATH=/app crusty-backend pytest tests/test_chat_memory.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/chat_memory.py backend/tests/test_chat_memory.py
git commit -m "feat(memory): Redis conversation memory module"
```

---

### Task 5: Wire memory into webhook, parse, and assistant

**Files:**
- Modify: `backend/app/routers/webhook.py` (record turns; pass history)
- Modify: `backend/app/services/assistant_service.py` (`answer` accepts `history`)

**Interfaces:**
- Consumes: `chat_memory.format_for_prompt`, `chat_memory.append`; `nlu.parse(..., history=...)` (Task 1); `web_search` (Task 3).
- Produces: `assistant_service.answer(question, employee, db, language="english", history="") -> str` — `history` appended to the synthesis context.

- [ ] **Step 1: Add `history` to `assistant_service.answer`**

In `backend/app/services/assistant_service.py`, change the signature and thread history into the synthesis context. Replace:

```python
def answer(question: str, employee, db, language: str = "english") -> str:
```
with:
```python
def answer(question: str, employee, db, language: str = "english", history: str = "") -> str:
```

And replace the two `nlu_service.ask(question, ...)` synthesize calls so history is prepended to context:

```python
    ctx = ((history + "\n\n") if history else "") + (ops_context or "")
    try:
        if ctx.strip():
            return nlu_service.ask(question, context=ctx, language=language)
        return nlu_service.ask(question, language=language)
    except Exception as e:
        logger.warning("assistant synthesize failed: %s", e)
        return ops_context or "Sorry, I couldn't process that right now."
```

(Keep the `_wants_web` web-search block from Task 3 immediately before this, unchanged.)

- [ ] **Step 2: Wire webhook — import + history + record turns**

In `backend/app/routers/webhook.py`, add near the service imports:

```python
from app.services import chat_memory
```

Find the NLU parse call:
```python
            parsed = nlu_service.parse(body, employee.name, employee.is_admin)
```
Replace with:
```python
            _history = chat_memory.format_for_prompt(employee.id)
            parsed = nlu_service.parse(body, employee.name, employee.is_admin, history=_history)
```

Find the HELP-branch general answer:
```python
            else:
                reply = assistant_answer(body, employee, db, language=lang)
                send_whatsapp(employee.whatsapp_number, reply)
```
Replace with:
```python
            else:
                reply = assistant_answer(body, employee, db, language=lang, history=_history)
                send_whatsapp(employee.whatsapp_number, reply)
                chat_memory.append(employee.id, "user", body)
                chat_memory.append(employee.id, "bot", reply)
```

Find the final else-branch general answer:
```python
        else:
            reply = assistant_answer(body, employee, db, language=lang)
            send_whatsapp(employee.whatsapp_number, reply)
```
Replace with:
```python
        else:
            reply = assistant_answer(body, employee, db, language=lang, history=_history)
            send_whatsapp(employee.whatsapp_number, reply)
            chat_memory.append(employee.id, "user", body)
            chat_memory.append(employee.id, "bot", reply)
```

- [ ] **Step 3: Verify import + full suite**

Run:
```bash
docker cp backend/app/services/assistant_service.py crusty-backend:/app/app/services/assistant_service.py
docker cp backend/app/routers/webhook.py crusty-backend:/app/app/routers/webhook.py
docker cp backend/app/services/chat_memory.py crusty-backend:/app/app/services/chat_memory.py
docker cp backend/app/services/web_search.py crusty-backend:/app/app/services/web_search.py
docker cp backend/app/services/nlu.py crusty-backend:/app/app/services/nlu.py
MSYS_NO_PATHCONV=1 docker exec -w /app -e PYTHONPATH=/app crusty-backend python -c "from app.routers import webhook; print('import OK')"
MSYS_NO_PATHCONV=1 docker exec -w /app -e PYTHONPATH=/app crusty-backend pytest tests/ -v
```
Expected: `import OK` and the full suite passes (existing + new nlu/web/memory/assistant tests).

- [ ] **Step 4: Build, deploy, smoke-test**

Run:
```bash
docker compose build backend && docker compose up -d backend
sleep 6
MSYS_NO_PATHCONV=1 docker exec -w /app crusty-backend python -c "from app.routers import webhook; from app.services import web_search, chat_memory; print('deployed OK')"
```
Then (live, optional) from a WhatsApp number ask a world question like "aaj weather kya hai" → expect a web-sourced answer; and confirm normal commands (done/assign) still work.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/webhook.py backend/app/services/assistant_service.py
git commit -m "feat(nlu): wire conversation memory into parse + assistant"
```

---

## Self-Review

**Spec coverage:**
- Few-shot + always-LLM + confidence gate + keyword fast-path — Task 1. ✓
- DuckDuckGo search (parse + uddg decode + [] on error) — Task 2. ✓
- web_search.answer (SSRF-safe fetch + summarize) + assistant wiring (_wants_web, no-ops fallback) — Task 3. ✓
- chat_memory (append/recent/format, 12 entries, 1800s TTL, graceful) — Task 4. ✓
- Wiring memory into webhook + parse(history=) + assistant(history=) — Task 5. ✓
- Constraints: keyword fast-path retained ✓; no-key DDG ✓; `_is_safe_url` gating on fetched results ✓ (Task 3 answer + spec); all calls wrapped ✓; 12 entries / 1800s ✓; confidence >= 0.55 ✓.

**Placeholder scan:** No TBD/TODO; every code step has full code. ✓

**Type consistency:** `parse(text, employee_name, is_admin, history="")`, `assistant.answer(question, employee, db, language, history="")`, `web_search.search(query, max_results)`, `web_search.answer(query, language)`, `chat_memory.append/recent/format_for_prompt` used identically across tasks 1–5. ✓
