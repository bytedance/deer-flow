"""Per-model token usage regression tests (issue #3645).

Covers the full path that powers ``GET /api/threads/{id}/token-usage``'s
``by_model`` field:

* ``RunJournal`` capturing each LLM call's real ``response_metadata.model_name``
  for both the lead agent / middleware path (``on_llm_end``) and the subagent
  external-records path (``record_external_llm_usage_records``).
* ``RunJournal.get_completion_data`` exposing the per-model breakdown so it can
  be threaded into the run store on completion.
* ``MemoryRunStore`` and ``RunRepository`` (SQLAlchemy) returning the same
  ``by_model`` shape from ``aggregate_tokens_by_thread``, with the invariant
  ``sum(by_model[*].tokens) == total_tokens``.
* Legacy rows written before this fix (``token_usage_by_model`` empty) falling
  back to the old ``model_name + total_tokens`` attribution instead of being
  silently dropped.
"""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from deerflow.persistence.run import RunRepository
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.journal import RunJournal
from deerflow.runtime.runs.store.memory import MemoryRunStore

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


def _make_llm_response(*, usage: dict | None, model_name: str | None = "lead-model"):
    """Build a minimal LLM response carrying the bits journal/collector read."""
    msg = MagicMock()
    msg.type = "ai"
    msg.content = ""
    msg.id = f"msg-{id(msg)}"
    msg.tool_calls = []
    msg.invalid_tool_calls = []
    msg.response_metadata = {} if model_name is None else {"model_name": model_name}
    msg.usage_metadata = usage
    msg.additional_kwargs = {}
    msg.name = None
    msg.model_dump.return_value = {
        "content": "",
        "additional_kwargs": {},
        "response_metadata": msg.response_metadata,
        "type": "ai",
        "name": None,
        "id": msg.id,
        "tool_calls": [],
        "invalid_tool_calls": [],
        "usage_metadata": usage,
    }
    gen = MagicMock()
    gen.message = msg
    response = MagicMock()
    response.generations = [[gen]]
    return response


def _journal() -> RunJournal:
    return RunJournal("r1", "t1", MemoryRunEventStore(), flush_threshold=100)


# ---------------------------------------------------------------------------
# RunJournal: per-call model accounting
# ---------------------------------------------------------------------------


class TestJournalByModel:
    def test_lead_agent_call_lands_on_real_model(self) -> None:
        j = _journal()
        j.on_llm_end(
            _make_llm_response(usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}, model_name="lead-model"),
            run_id=uuid4(),
            parent_run_id=None,
            tags=["lead_agent"],
        )
        data = j.get_completion_data()
        assert data["token_usage_by_model"] == {
            "lead-model": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        }
        assert data["lead_agent_tokens"] == 15
        assert data["total_tokens"] == 15

    def test_middleware_call_lands_on_its_own_model(self) -> None:
        """A middleware (e.g. title/summarization) on a different model gets its own bucket."""
        j = _journal()
        j.on_llm_end(
            _make_llm_response(usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}, model_name="lead-model"),
            run_id=uuid4(),
            parent_run_id=None,
            tags=["lead_agent"],
        )
        j.on_llm_end(
            _make_llm_response(usage={"input_tokens": 4, "output_tokens": 1, "total_tokens": 5}, model_name="title-model"),
            run_id=uuid4(),
            parent_run_id=None,
            tags=["middleware:title"],
        )
        data = j.get_completion_data()
        assert data["token_usage_by_model"] == {
            "lead-model": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            "title-model": {"input_tokens": 4, "output_tokens": 1, "total_tokens": 5},
        }
        assert data["lead_agent_tokens"] == 15
        assert data["middleware_tokens"] == 5

    def test_missing_model_name_falls_back_to_unknown(self) -> None:
        j = _journal()
        j.on_llm_end(
            _make_llm_response(usage={"input_tokens": 3, "output_tokens": 2, "total_tokens": 5}, model_name=None),
            run_id=uuid4(),
            parent_run_id=None,
            tags=["lead_agent"],
        )
        data = j.get_completion_data()
        assert data["token_usage_by_model"] == {
            "unknown": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
        }

    def test_same_model_aggregates_across_calls(self) -> None:
        j = _journal()
        for _ in range(2):
            j.on_llm_end(
                _make_llm_response(usage={"input_tokens": 7, "output_tokens": 3, "total_tokens": 10}, model_name="lead-model"),
                run_id=uuid4(),
                parent_run_id=None,
                tags=["lead_agent"],
            )
        data = j.get_completion_data()
        assert data["token_usage_by_model"] == {
            "lead-model": {"input_tokens": 14, "output_tokens": 6, "total_tokens": 20},
        }

    def test_subagent_external_records_attribute_to_real_model(self) -> None:
        """The fix's headline behavior: subagent on a different model no longer
        steals tokens from the lead model bucket."""
        j = _journal()
        # Lead emits 10 tokens on lead-model.
        j.on_llm_end(
            _make_llm_response(usage={"input_tokens": 6, "output_tokens": 4, "total_tokens": 10}, model_name="lead-model"),
            run_id=uuid4(),
            parent_run_id=None,
            tags=["lead_agent"],
        )
        # Subagent ran on subagent-model and reports 25 tokens via the
        # external-records bridge (the path SubagentTokenCollector uses).
        j.record_external_llm_usage_records(
            [
                {
                    "source_run_id": "sub-1",
                    "caller": "subagent:general-purpose",
                    "model_name": "subagent-model",
                    "input_tokens": 15,
                    "output_tokens": 10,
                    "total_tokens": 25,
                },
            ],
        )
        data = j.get_completion_data()
        assert data["token_usage_by_model"] == {
            "lead-model": {"input_tokens": 6, "output_tokens": 4, "total_tokens": 10},
            "subagent-model": {"input_tokens": 15, "output_tokens": 10, "total_tokens": 25},
        }
        assert data["total_tokens"] == 35
        # by_caller stays accurate too.
        assert data["lead_agent_tokens"] == 10
        assert data["subagent_tokens"] == 25
        # Invariant the issue calls out: by_model sums to total_tokens.
        assert sum(b["total_tokens"] for b in data["token_usage_by_model"].values()) == data["total_tokens"]

    def test_subagent_record_without_model_falls_back_to_unknown(self) -> None:
        j = _journal()
        j.record_external_llm_usage_records(
            [
                {
                    "source_run_id": "sub-1",
                    "caller": "subagent:bash",
                    "input_tokens": 5,
                    "output_tokens": 2,
                    "total_tokens": 7,
                },
            ],
        )
        data = j.get_completion_data()
        assert data["token_usage_by_model"] == {
            "unknown": {"input_tokens": 5, "output_tokens": 2, "total_tokens": 7},
        }

    def test_on_llm_end_dedup_does_not_double_count_model(self) -> None:
        j = _journal()
        rid = uuid4()
        usage = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
        j.on_llm_end(_make_llm_response(usage=usage, model_name="lead-model"), run_id=rid, parent_run_id=None, tags=["lead_agent"])
        # Same langchain run_id firing twice (real callbacks do this) must
        # not inflate either total_tokens or the per-model bucket.
        j.on_llm_end(_make_llm_response(usage=usage, model_name="lead-model"), run_id=rid, parent_run_id=None, tags=["lead_agent"])
        data = j.get_completion_data()
        assert data["total_tokens"] == 15
        assert data["token_usage_by_model"] == {
            "lead-model": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        }

    def test_external_records_dedup_does_not_double_count_model(self) -> None:
        j = _journal()
        record = {
            "source_run_id": "sub-1",
            "caller": "subagent:general-purpose",
            "model_name": "subagent-model",
            "input_tokens": 15,
            "output_tokens": 10,
            "total_tokens": 25,
        }
        j.record_external_llm_usage_records([record])
        j.record_external_llm_usage_records([record])
        data = j.get_completion_data()
        assert data["subagent_tokens"] == 25
        assert data["token_usage_by_model"] == {
            "subagent-model": {"input_tokens": 15, "output_tokens": 10, "total_tokens": 25},
        }

    def test_track_tokens_disabled_keeps_by_model_empty(self) -> None:
        store = MemoryRunEventStore()
        j = RunJournal("r1", "t1", store, track_token_usage=False, flush_threshold=100)
        j.on_llm_end(
            _make_llm_response(usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}, model_name="lead-model"),
            run_id=uuid4(),
            parent_run_id=None,
            tags=["lead_agent"],
        )
        j.record_external_llm_usage_records(
            [{"source_run_id": "sub", "caller": "subagent:x", "model_name": "sub-model", "input_tokens": 1, "output_tokens": 1, "total_tokens": 2}],
        )
        data = j.get_completion_data()
        assert data["token_usage_by_model"] == {}
        assert data["total_tokens"] == 0


# ---------------------------------------------------------------------------
# Store aggregation: invariants and parity across MemoryRunStore + RunRepository
# ---------------------------------------------------------------------------


_THREAD = "thread-by-model"


def _completed_run(
    run_id: str,
    *,
    model_name: str | None,
    total_tokens: int,
    lead: int = 0,
    sub: int = 0,
    mw: int = 0,
    by_model: dict | None = None,
) -> dict:
    """Shape that both stores accept for completion writes (kwargs to update_run_completion)."""
    return {
        "run_id": run_id,
        "model_name": model_name,
        "completion": {
            "status": "success",
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_tokens": total_tokens,
            "llm_call_count": 1,
            "lead_agent_tokens": lead,
            "subagent_tokens": sub,
            "middleware_tokens": mw,
            "token_usage_by_model": by_model or {},
            "message_count": 0,
        },
    }


async def _seed_run(store, *, run_id: str, model_name: str | None, completion: dict) -> None:
    await store.put(run_id, thread_id=_THREAD, status="pending", model_name=model_name)
    await store.update_run_completion(run_id, **completion)


_RUN_FIXTURES = [
    # 1. Run where subagent and middleware ran on different models than lead.
    _completed_run(
        "run-1",
        model_name="lead-model",
        total_tokens=300,
        lead=100,
        sub=150,
        mw=50,
        by_model={
            "lead-model": {"input_tokens": 60, "output_tokens": 40, "total_tokens": 100},
            "subagent-model": {"input_tokens": 90, "output_tokens": 60, "total_tokens": 150},
            "middleware-model": {"input_tokens": 30, "output_tokens": 20, "total_tokens": 50},
        },
    ),
    # 2. Another run, lead on a *different* lead model — exercises multi-run merge.
    _completed_run(
        "run-2",
        model_name="lead-model-b",
        total_tokens=80,
        lead=80,
        by_model={
            "lead-model-b": {"input_tokens": 50, "output_tokens": 30, "total_tokens": 80},
        },
    ),
    # 3. Legacy row written before this fix: empty token_usage_by_model. Must
    #    fall back to (model_name, total_tokens) instead of disappearing from
    #    by_model entirely.
    _completed_run(
        "run-3",
        model_name="legacy-model",
        total_tokens=42,
        lead=42,
        by_model={},
    ),
]


async def _seed_all(store) -> None:
    for fix in _RUN_FIXTURES:
        await _seed_run(store, run_id=fix["run_id"], model_name=fix["model_name"], completion=fix["completion"])


def _assert_aggregate_shape(agg: dict) -> None:
    """Pin the contract that powers /api/threads/{id}/token-usage."""
    # The headline totals stay the simple SUMs.
    assert agg["total_tokens"] == 300 + 80 + 42
    assert agg["total_runs"] == 3
    assert agg["by_caller"] == {
        "lead_agent": 100 + 80 + 42,
        "subagent": 150,
        "middleware": 50,
    }
    # The core fix: subagent / middleware models show up in by_model with their
    # real tokens; the lead-model bucket is NOT inflated with subagent tokens.
    assert agg["by_model"]["lead-model"] == {"tokens": 100, "runs": 1}
    assert agg["by_model"]["subagent-model"] == {"tokens": 150, "runs": 1}
    assert agg["by_model"]["middleware-model"] == {"tokens": 50, "runs": 1}
    assert agg["by_model"]["lead-model-b"] == {"tokens": 80, "runs": 1}
    # Legacy fallback path — empty token_usage_by_model maps to the row's
    # ``model_name`` with the full total_tokens.
    assert agg["by_model"]["legacy-model"] == {"tokens": 42, "runs": 1}
    # Invariant from issue #3645.
    assert sum(b["tokens"] for b in agg["by_model"].values()) == agg["total_tokens"]


@pytest.mark.anyio
async def test_memory_store_by_model_invariant_and_fallback():
    store = MemoryRunStore()
    await _seed_all(store)
    agg = await store.aggregate_tokens_by_thread(_THREAD)
    _assert_aggregate_shape(agg)


async def _make_sql_repo(tmp_path):
    from deerflow.persistence.engine import get_session_factory, init_engine

    url = f"sqlite+aiosqlite:///{tmp_path / 'by-model.db'}"
    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    return RunRepository(get_session_factory())


async def _close_sql_engine() -> None:
    from deerflow.persistence.engine import close_engine

    await close_engine()


@pytest.mark.anyio
async def test_sql_store_by_model_invariant_and_fallback(tmp_path):
    repo = await _make_sql_repo(tmp_path)
    try:
        await _seed_all(repo)
        agg = await repo.aggregate_tokens_by_thread(_THREAD)
        _assert_aggregate_shape(agg)
    finally:
        await _close_sql_engine()


@pytest.mark.anyio
async def test_memory_and_sql_stores_agree(tmp_path):
    """Memory and SQL stores must return byte-identical aggregations so
    behavior does not silently diverge based on database.backend choice."""
    mem = MemoryRunStore()
    sql = await _make_sql_repo(tmp_path)
    try:
        await _seed_all(mem)
        await _seed_all(sql)
        mem_agg = await mem.aggregate_tokens_by_thread(_THREAD)
        sql_agg = await sql.aggregate_tokens_by_thread(_THREAD)
        assert mem_agg == sql_agg
    finally:
        await _close_sql_engine()


@pytest.mark.anyio
async def test_include_active_picks_up_running_progress_snapshot(tmp_path):
    """``update_run_progress`` must persist ``token_usage_by_model`` so the
    ``include_active=true`` view of /token-usage reflects in-flight tokens."""
    repo = await _make_sql_repo(tmp_path)
    try:
        await repo.put("run-active", thread_id=_THREAD, status="pending")
        # Transition to running so update_run_progress' status guard fires.
        await repo.update_status("run-active", "running")
        await repo.update_run_progress(
            "run-active",
            total_tokens=70,
            total_input_tokens=40,
            total_output_tokens=30,
            lead_agent_tokens=70,
            token_usage_by_model={
                "lead-model": {"input_tokens": 40, "output_tokens": 30, "total_tokens": 70},
            },
        )
        # Default (completed-only) excludes running runs.
        completed_only = await repo.aggregate_tokens_by_thread(_THREAD)
        assert completed_only["total_runs"] == 0
        assert completed_only["by_model"] == {}

        active = await repo.aggregate_tokens_by_thread(_THREAD, include_active=True)
        assert active["total_runs"] == 1
        assert active["by_model"] == {"lead-model": {"tokens": 70, "runs": 1}}
        assert active["total_tokens"] == 70
    finally:
        await _close_sql_engine()


# ---------------------------------------------------------------------------
# Prompt-cache-hit accounting (powers cache-aware cost estimation in
# /api/console): cache_read_tokens is a *sparse* bucket key — present only
# when a provider reported cache hits — so pre-existing bucket shapes and
# exact-equality assertions above stay valid.
# ---------------------------------------------------------------------------


class TestJournalCacheRead:
    def test_cache_read_accumulates_as_sparse_key(self) -> None:
        j = _journal()
        j.on_llm_end(
            _make_llm_response(
                usage={"input_tokens": 100, "output_tokens": 10, "total_tokens": 110, "input_token_details": {"cache_read": 80}},
                model_name="m",
            ),
            run_id=uuid4(),
            parent_run_id=None,
            tags=["lead_agent"],
        )
        # Second call without cache hits still accumulates into the same bucket.
        j.on_llm_end(
            _make_llm_response(usage={"input_tokens": 50, "output_tokens": 5, "total_tokens": 55}, model_name="m"),
            run_id=uuid4(),
            parent_run_id=None,
            tags=["lead_agent"],
        )
        data = j.get_completion_data()
        assert data["token_usage_by_model"]["m"] == {
            "input_tokens": 150,
            "output_tokens": 15,
            "total_tokens": 165,
            "cache_read_tokens": 80,
        }

    def test_bucket_without_cache_hits_keeps_legacy_shape(self) -> None:
        j = _journal()
        j.on_llm_end(
            _make_llm_response(usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}, model_name="m"),
            run_id=uuid4(),
            parent_run_id=None,
            tags=["lead_agent"],
        )
        assert j.get_completion_data()["token_usage_by_model"]["m"] == {
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
        }

    def test_external_records_carry_cache_read(self) -> None:
        j = _journal()
        j.record_external_llm_usage_records(
            [
                {
                    "source_run_id": "sub-1",
                    "caller": "subagent:general-purpose",
                    "model_name": "sub-m",
                    "input_tokens": 40,
                    "output_tokens": 10,
                    "total_tokens": 50,
                    "cache_read_tokens": 25,
                },
            ],
        )
        assert j.get_completion_data()["token_usage_by_model"]["sub-m"]["cache_read_tokens"] == 25

    def test_deepseek_raw_usage_normalizes_to_cache_read(self) -> None:
        """Pin the DeepSeek chat-completions shape end-to-end: the raw
        ``prompt_tokens_details.cached_tokens`` field is what langchain-openai's
        ``_create_usage_metadata`` normalizes into
        ``input_token_details.cache_read`` (DeepSeek's top-level
        ``prompt_cache_hit/miss_tokens`` are redundant aliases LangChain does
        not read), and the journal captures it. The derived cache-miss count
        (input − cache_read) must equal DeepSeek's own
        ``prompt_cache_miss_tokens``, which is what cache-aware pricing bills
        at the full input price."""
        from langchain_openai.chat_models.base import _create_usage_metadata

        raw = {
            "prompt_tokens": 106,
            "completion_tokens": 112,
            "total_tokens": 218,
            "prompt_tokens_details": {"cached_tokens": 64},
            "prompt_cache_hit_tokens": 64,
            "prompt_cache_miss_tokens": 42,
        }
        usage = _create_usage_metadata(raw)
        j = _journal()
        j.on_llm_end(
            _make_llm_response(usage=dict(usage), model_name="deepseek-chat"),
            run_id=uuid4(),
            parent_run_id=None,
            tags=["lead_agent"],
        )
        bucket = j.get_completion_data()["token_usage_by_model"]["deepseek-chat"]
        assert bucket == {
            "input_tokens": 106,
            "output_tokens": 112,
            "total_tokens": 218,
            "cache_read_tokens": 64,
        }
        assert bucket["input_tokens"] - bucket["cache_read_tokens"] == raw["prompt_cache_miss_tokens"]

    def test_collector_extracts_cache_read_from_usage_metadata(self) -> None:
        from deerflow.subagents.token_collector import SubagentTokenCollector

        collector = SubagentTokenCollector("subagent:general-purpose")
        collector.on_llm_end(
            _make_llm_response(
                usage={"input_tokens": 30, "output_tokens": 6, "total_tokens": 36, "input_token_details": {"cache_read": 20}},
                model_name="sub-m",
            ),
            run_id=uuid4(),
        )
        records = collector.snapshot_records()
        assert len(records) == 1
        assert records[0]["cache_read_tokens"] == 20

    def test_collector_omits_cache_read_key_when_no_cache_hits(self) -> None:
        from deerflow.subagents.token_collector import SubagentTokenCollector

        collector = SubagentTokenCollector("subagent:general-purpose")
        collector.on_llm_end(
            _make_llm_response(
                usage={"input_tokens": 30, "output_tokens": 6, "total_tokens": 36},
                model_name="sub-m",
            ),
            run_id=uuid4(),
        )
        records = collector.snapshot_records()
        assert len(records) == 1
        # Sparse record shape: no explicit 0 when the provider reported no
        # cache hits (record_external_llm_usage_records treats absent as 0).
        assert "cache_read_tokens" not in records[0]
