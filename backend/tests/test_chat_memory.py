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
