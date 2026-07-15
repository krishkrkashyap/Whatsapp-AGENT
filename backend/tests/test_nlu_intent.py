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
