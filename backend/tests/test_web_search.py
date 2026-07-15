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
