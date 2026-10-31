"""PostgreSQL JSON columns must never receive bare NaN/Infinity tokens.

The shared ORM engine's ``json_serializer`` (:func:`deerflow.persistence.engine._json_serializer`)
and the sync agent-storage and skill-mutation engines all use the same serializer.
Without it they serialize JSON columns with the lenient ``json.dumps`` default
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


def test_sync_agent_engine_normalizes_sqlite_json_columns(tmp_path):
    from sqlalchemy import select, text
    from sqlalchemy.orm import Session

    from deerflow.persistence.agents.model import AgentRow
    from deerflow.persistence.agents.sql import _build_engine

    engine = _build_engine(f"sqlite:///{tmp_path / 'agents.db'}")
    value = {"label": "文", "keep": [1.5, True, None], "nested": [float("nan"), {"positive": float("inf"), "negative": float("-inf")}]}
    expected = {"label": "文", "keep": [1.5, True, None], "nested": [None, {"positive": None, "negative": None}]}
    try:
        AgentRow.__table__.create(engine)
        with Session(engine) as session, session.begin():
            session.add(AgentRow(id="agent", user_id="owner", name="test", config=value))
        with Session(engine) as session:
            raw = session.scalar(text("SELECT config FROM agents WHERE id = 'agent'"))
            assert _strict_loads(raw) == expected
            assert session.scalar(select(AgentRow.config)) == expected
    finally:
        engine.dispose()


def test_sync_skill_mutation_engine_wires_the_safe_serializer_for_postgres(monkeypatch):
    from types import SimpleNamespace

    from deerflow.skills.mutations import topology

    captured = {}

    def fake_create_engine(url, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(topology, "create_engine", fake_create_engine)
    topology.mutation_session_factory("postgresql+psycopg://u:p@localhost/db")
    serializer = captured.get("json_serializer")
    assert serializer is not None, "the skill-mutation engine must set a json serializer"
    assert _strict_loads(serializer({"x": float("nan")})) == {"x": None}


def test_sync_skill_mutation_engine_normalizes_sqlite_json_columns(tmp_path):
    from sqlalchemy import select, text

    from deerflow.persistence.skill_mutations.model import SkillProposalRow
    from deerflow.persistence.user.model import UserRow
    from deerflow.skills.mutations.topology import mutation_session_factory

    engine, sessions = mutation_session_factory(f"sqlite:///{tmp_path / 'mutations.db'}")
    value = {"label": "文", "keep": [1.5, True, None], "nested": [float("nan"), {"positive": float("inf"), "negative": float("-inf")}]}
    expected = {"label": "文", "keep": [1.5, True, None], "nested": [None, {"positive": None, "negative": None}]}
    try:
        UserRow.__table__.create(engine)
        SkillProposalRow.__table__.create(engine)
        with sessions.begin() as session:
            session.add(UserRow(id="owner", email="owner@example.test"))
        with sessions.begin() as session:
            session.add(
                SkillProposalRow(
                    proposal_id="proposal",
                    plugin_id="test",
                    owner_id="owner",
                    target_ref="target",
                    name="skill",
                    base_revision={},
                    sources=[],
                    candidate_hash="hash",
                    state="draft",
                    expires_at=1000,
                    check_result=value,
                    idempotency_key="key",
                    request_hash="hash",
                )
            )
        with sessions() as session:
            raw = session.scalar(text("SELECT check_result FROM skill_mutation_proposals WHERE proposal_id = 'proposal'"))
            assert _strict_loads(raw) == expected
            assert session.scalar(select(SkillProposalRow.check_result)) == expected
    finally:
        engine.dispose()
