"""PostgreSQL JSON columns must never receive bare NaN/Infinity tokens.

The shared ORM engine's ``json_serializer`` (:func:`deerflow.persistence.engine._json_serializer`)
and the sync agent-storage engine (:func:`deerflow.persistence.agents.sql._build_engine`)
both serialized JSON columns with the lenient ``json.dumps`` default
(``allow_nan=True``). A non-finite float reaching a JSON column — run metadata
merges caller-supplied values, ``goal_verdict`` and ``token_usage_by_model``
carry model/provider numbers — is emitted as the bare ``NaN`` / ``Infinity``
token, which PostgreSQL's jsonb rejects as invalid JSON, turning the write
into a ``DataError``. SQLite silently accepts and round-trips the invalid
token instead, so the failure is postgres-only and environment-dependent.

The display/wire surfaces got the same normalization in the canonical
serializer (#7670), which explicitly does not cover persisted state; the
Gateway already uses ``allow_nan=False`` at three hand-picked sites. This pins
the shared persistence layer to the same contract: non-finite floats become
``None`` before any JSON column is written.
"""

from __future__ import annotations

import json

from deerflow.persistence.engine import _json_serializer, _postgres_engine_kwargs
from deerflow.persistence.json_compat import dumps_json_safe, json_safe_value


def _strict_loads(payload: str):
    """json.loads, but bare NaN/Infinity/-Infinity tokens fail loudly."""

    def _reject(token):
        raise AssertionError(f"bare {token} token reached the wire: {payload}")

    return json.loads(payload, parse_constant=_reject)


def test_non_finite_floats_become_none_everywhere():
    payload = dumps_json_safe({"a": float("inf"), "b": float("-inf"), "c": float("nan"), "nested": [float("inf"), {"d": float("nan")}], "keep": 1.5})
    parsed = _strict_loads(payload)
    assert parsed == {"a": None, "b": None, "c": None, "nested": [None, {"d": None}], "keep": 1.5}


def test_finite_values_and_bools_pass_through_unchanged():
    value = {"s": "文", "i": 3, "b": True, "f": 0.25, "n": None, "l": [1, False]}
    assert _strict_loads(dumps_json_safe(value)) == value
    assert json_safe_value(value) == value


def test_async_postgres_engine_serializer_is_safe():
    kwargs = _postgres_engine_kwargs(echo=False, pool_size=5)
    assert kwargs["json_serializer"] is _json_serializer
    assert _strict_loads(kwargs["json_serializer"]({"x": float("inf")})) == {"x": None}


def test_sync_agent_engine_wires_the_safe_serializer_for_postgres(monkeypatch):
    import deerflow.persistence.agents.sql as agents_sql

    captured: dict[str, object] = {}

    def fake_create_engine(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        engine = type("FakeEngine", (), {"dialect": type("D", (), {"name": "postgresql"})()})()
        return engine

    monkeypatch.setattr(agents_sql, "create_engine", fake_create_engine)

    agents_sql._build_engine("postgresql+psycopg://u:p@localhost/db")

    assert captured["url"].startswith("postgresql")
    serializer = captured["kwargs"].get("json_serializer")
    assert serializer is not None, "the sync postgres engine must set a json serializer"
    assert _strict_loads(serializer({"x": float("nan")})) == {"x": None}


def test_sync_agent_engine_leaves_sqlite_untouched(monkeypatch):
    import deerflow.persistence.agents.sql as agents_sql

    captured: dict[str, object] = {}

    def fake_create_engine(url, **kwargs):
        captured["kwargs"] = kwargs
        engine = type("FakeEngine", (), {})()
        # The sqlite branch registers connect listeners via sqlalchemy.event,
        # which needs a real target; give it a stand-in that accepts listeners.
        engine.dialect = type("D", (), {"name": "sqlite"})()
        return engine

    monkeypatch.setattr(agents_sql, "create_engine", fake_create_engine)
    monkeypatch.setattr(agents_sql.event, "listens_for", lambda *a, **k: lambda f: f)
    agents_sql._build_engine("sqlite:///tmp/agents.db")
    assert "json_serializer" not in captured["kwargs"], "sqlite does not accept json_serializer and stores JSON leniently"
