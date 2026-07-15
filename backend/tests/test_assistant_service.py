import types
from app.services import assistant_service as asv


class _Emp:
    def __init__(self, admin=False):
        self.id = "e1"; self.name = "Krish"; self.is_admin = admin


def test_select_tool_uses_llm(monkeypatch):
    monkeypatch.setattr(asv.nlu_service, "api_key", "x")
    monkeypatch.setattr(asv.nlu_service, "_call_llm",
                        lambda prompt, json_mode=False: '{"tool":"my_pending_tasks","args":{}}')
    name, args = asv.select_tool("what are my tasks", _Emp())
    assert name == "my_pending_tasks"


def test_select_tool_invalid_llm_falls_back_to_keyword(monkeypatch):
    monkeypatch.setattr(asv.nlu_service, "api_key", "x")
    monkeypatch.setattr(asv.nlu_service, "_call_llm",
                        lambda prompt, json_mode=False: '{"tool":"garbage","args":{}}')
    name, _ = asv.select_tool("my pending tasks", _Emp())
    assert name == "my_pending_tasks"   # keyword fallback recovered it


def test_select_tool_keyword_when_no_api_key(monkeypatch):
    monkeypatch.setattr(asv.nlu_service, "api_key", "")
    name, _ = asv.select_tool("show team status", _Emp(admin=True))
    assert name == "team_status"


def test_select_tool_none_for_unrelated(monkeypatch):
    monkeypatch.setattr(asv.nlu_service, "api_key", "")
    name, _ = asv.select_tool("what is the capital of France", _Emp())
    assert name is None


def test_answer_uses_ops_context(monkeypatch, db):
    from app.models.employee import Employee
    from app.models.task import Task, Priority, TaskStatus
    from datetime import datetime, timezone
    e = Employee(name="Krish", department="IT", role="Staff",
                 whatsapp_number="+910001", is_admin=False)
    db.add(e); db.commit(); db.refresh(e)
    db.add(Task(title="Clean oven", priority=Priority.medium, status=TaskStatus.pending,
                assigned_by_id="a", assigned_to_id=e.id,
                assigned_at=datetime.now(timezone.utc))); db.commit()

    captured = {}
    def fake_ask(question, context="", language="english"):
        captured["context"] = context
        return "ANSWER"
    monkeypatch.setattr(asv.nlu_service, "api_key", "")  # force keyword route
    monkeypatch.setattr(asv.nlu_service, "ask", fake_ask)

    out = asv.answer("what are my pending tasks", e, db, language="english")
    assert out == "ANSWER"
    assert "Clean oven" in captured["context"]   # ops result was passed as context


def test_answer_falls_back_without_tool(monkeypatch, db):
    from app.models.employee import Employee
    e = Employee(name="Krish", department="IT", role="Staff",
                 whatsapp_number="+910002", is_admin=False)
    db.add(e); db.commit(); db.refresh(e)
    monkeypatch.setattr(asv.nlu_service, "api_key", "")
    monkeypatch.setattr(asv.nlu_service, "ask",
                        lambda question, context="", language="english": "GENERAL")
    out = asv.answer("what is the capital of France", e, db)
    assert out == "GENERAL"


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
