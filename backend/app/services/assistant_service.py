"""Smart assistant — answers general questions from live ops data.

P1: pick one curated ops tool (LLM JSON mode, keyword fallback), run it, and let
the existing nlu_service.ask synthesize a natural answer. Doc search (P2) and
conversation memory (P3) extend answer() later without changing this contract.
"""
import json
import logging
from app.services import ops_tools
from app.services import web_search
from app.services.nlu import nlu_service

logger = logging.getLogger("assistant")

# Keyword fallback routing — (substrings, tool_name). First match wins.
_KEYWORD_ROUTES = [
    (["team status", "team pending", "sabka", "everyone", "all tasks"], "team_status"),
    (["overdue", "late task", "past due"], "overdue_tasks"),
    (["how many", "count", "department pending", "dept pending"], "dept_pending_count"),
    (["who owns", "who does", "who handles", "owner of", "kaun karta"], "who_owns_sop"),
    (["schedule", "today's sop", "sop today", "roster"], "sop_schedule_today"),
    (["my task", "my pending", "mera task", "mere task", "pending"], "my_pending_tasks"),
    (["today", "aaj"], "my_tasks_today"),
    (["who is", "contact of", "phone of", "role of", "staff"], "staff_lookup"),
]


def _keyword_route(question: str):
    q = question.lower()
    for needles, tool in _KEYWORD_ROUTES:
        if any(n in q for n in needles):
            return tool, {}
    return None, {}


def select_tool(question: str, employee):
    """Return (tool_name|None, args). LLM first, keyword fallback."""
    if nlu_service.api_key:
        prompt = (
            "You route an internal task-bot question to ONE lookup tool, or none.\n"
            f"Tools:\n{ops_tools.tool_catalog()}\n\n"
            f"Question: \"{question}\"\n\n"
            'Respond JSON ONLY: {"tool": "<name or null>", "args": {<arg: value>}}. '
            "Use null when no tool fits (general chit-chat / world knowledge)."
        )
        try:
            raw = nlu_service._call_llm(prompt, json_mode=True)
            data = json.loads(raw)
            tool = data.get("tool")
            args = data.get("args") or {}
            if tool in ops_tools.TOOL_REGISTRY:
                return tool, (args if isinstance(args, dict) else {})
            if tool in (None, "null", ""):
                # LLM explicitly said "no tool" — trust it, but let keyword have a
                # last word so obvious phrasings still route.
                return _keyword_route(question)
        except Exception as e:
            logger.warning("tool selection LLM failed: %s", e)
    return _keyword_route(question)


_WEB_MARKERS = ("?", "weather", "price", "rate", "news", "today", "aaj",
                "kitna", "kitni", "kaun", "kab", "kyu", "kyun",
                "what", "who", "when", "where", "why", "how", "kya", "kaise")


def _wants_web(question: str) -> bool:
    """Heuristic: does this look like a factual/world question worth a web lookup?"""
    q = (question or "").lower()
    return any(m in q for m in _WEB_MARKERS)


def answer(question: str, employee, db, language: str = "english", history: str = "") -> str:
    """Answer a general question using live ops data when a tool fits, else a
    plain LLM answer. Never raises — always returns a string."""
    ops_context = ""
    try:
        tool, args = select_tool(question, employee)
        if tool:
            ops_context = ops_tools.dispatch(tool, args, employee, db)
    except Exception as e:
        logger.warning("assistant tool phase failed: %s", e)

    # No ops data — if it looks like a factual/world question, try the web.
    if not ops_context and _wants_web(question):
        try:
            web = web_search.answer(question, language=language)
            if web:
                return web
        except Exception as e:
            logger.warning("assistant web phase failed: %s", e)

    ctx = ((history + "\n\n") if history else "") + (ops_context or "")
    try:
        if ctx.strip():
            return nlu_service.ask(question, context=ctx, language=language)
        return nlu_service.ask(question, language=language)
    except Exception as e:
        logger.warning("assistant synthesize failed: %s", e)
        return ops_context or "Sorry, I couldn't process that right now."
