from src.agents.memory.scope import MemoryScope
from src.agents.memory.store import PostgresMemoryStore


class _FakeCursor:
    def __init__(self):
        self.calls = []
        self.fetchone_result = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchone(self):
        return self.fetchone_result


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True


def test_save_memory_persists_single_profile_document(monkeypatch):
    cursor = _FakeCursor()
    conn = _FakeConn(cursor)

    store = PostgresMemoryStore("postgres://unused")
    monkeypatch.setattr(store, "_connect", lambda: conn)

    scope = MemoryScope.from_values("chat", "ws-1", strict=True)
    payload = {
        "version": "1.0",
        "user": {},
        "history": {},
        "facts": [
            {"id": "fact_a", "content": "User's name is Marcellus", "category": "profile", "confidence": 0.97, "source": "t1"},
            {"id": "fact_b", "content": "User has 7 cats", "category": "profile", "confidence": 0.86, "source": "t1"},
        ],
    }

    ok = store.save_memory(scope, payload)

    assert ok is True
    assert conn.committed is True

    sql_text = "\n".join(call[0] for call in cursor.calls)
    assert "INSERT INTO memory_profiles" in sql_text
    assert "ON CONFLICT (workspace_type, workspace_id)" in sql_text
    assert "memory_facts" not in sql_text


def test_get_memory_reads_profile_document_only(monkeypatch):
    cursor = _FakeCursor()
    conn = _FakeConn(cursor)

    store = PostgresMemoryStore("postgres://unused")
    monkeypatch.setattr(store, "_connect", lambda: conn)

    scope = MemoryScope.from_values("chat", "ws-r", strict=True)
    cursor.fetchone_result = ({"version": "1.0", "user": {}, "history": {}, "facts": [{"id": "fact_a"}]},)

    result = store.get_memory(scope)

    assert result["facts"] == [{"id": "fact_a"}]

    sql_text = "\n".join(call[0] for call in cursor.calls)
    assert "SELECT profile_json" in sql_text
    assert "memory_facts" not in sql_text
