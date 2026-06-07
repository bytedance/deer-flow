import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from tg_intel_crawler.filter.candidate_reviewer import (
    CandidateReviewer, Stage1Decision, Stage1Result,
)


@pytest.fixture
def llm_config():
    return {
        "api_key": "test-key",
        "base_url": "https://example.com/v1",
        "model": "ep-test",
        "batch_size": 5,
    }


@pytest.fixture
def intel_stats_stub():
    """Stub: every group scores zero unless overridden."""
    class _Stub:
        def __init__(self, scores=None):
            self._scores = scores or {}
        def score_for(self, name):
            return self._scores.get(name, {"high": 0, "medium": 0, "total_msgs": 0})
    return _Stub


def _candidate_dict(key="douyinhao88", invite_hash=None, count=7, sources=None):
    return {
        "key": key,
        "invite_hash": invite_hash,
        "first_seen": "2026-06-05T08:30:00+00:00",
        "last_seen":  "2026-06-08T22:15:00+00:00",
        "count": count,
        "status": "pending",
        "sources": sources or [
            {"group": "卖号群", "msg_id": 100, "channel": "text"},
        ],
    }


def test_build_stage1_prompt_includes_metadata(llm_config, intel_stats_stub):
    reviewer = CandidateReviewer(
        llm_config=llm_config,
        intel_stats=intel_stats_stub({
            "卖号群": {"high": 12, "medium": 30, "total_msgs": 800}
        }),
        raw_lookup=None,
    )
    cands = [_candidate_dict(key="douyinhao88")]
    prompt = reviewer._build_stage1_prompt(cands)

    assert "douyinhao88" in prompt
    assert "卖号群" in prompt
    assert '"high": 12' in prompt or "high: 12" in prompt
    assert '"index": 0' in prompt or "[0]" in prompt


def test_parse_stage1_response_happy_path(llm_config, intel_stats_stub):
    reviewer = CandidateReviewer(
        llm_config=llm_config,
        intel_stats=intel_stats_stub(),
        raw_lookup=None,
    )
    raw = json.dumps([
        {"index": 0, "decision": "advance",   "confidence": "high",
         "reason": "looks like account-trading channel"},
        {"index": 1, "decision": "reject",    "confidence": "high",
         "reason": "irrelevant freebie group"},
        {"index": 2, "decision": "uncertain", "confidence": "low",
         "reason": "not enough signal"},
    ])
    parsed = reviewer._parse_stage1_response(raw, expected_count=3)
    assert len(parsed) == 3
    assert parsed[0].decision == Stage1Decision.ADVANCE
    assert parsed[1].decision == Stage1Decision.REJECT
    assert parsed[2].decision == Stage1Decision.UNCERTAIN


def test_parse_stage1_response_count_mismatch_returns_empty(llm_config, intel_stats_stub):
    reviewer = CandidateReviewer(
        llm_config=llm_config,
        intel_stats=intel_stats_stub(),
        raw_lookup=None,
    )
    raw = json.dumps([{"index": 0, "decision": "advance", "confidence": "high", "reason": "x"}])
    parsed = reviewer._parse_stage1_response(raw, expected_count=2)
    assert parsed == []


def test_parse_stage1_response_unknown_decision_treated_as_uncertain(llm_config, intel_stats_stub):
    reviewer = CandidateReviewer(
        llm_config=llm_config,
        intel_stats=intel_stats_stub(),
        raw_lookup=None,
    )
    raw = json.dumps([
        {"index": 0, "decision": "maybe", "confidence": "high", "reason": "weird"},
    ])
    parsed = reviewer._parse_stage1_response(raw, expected_count=1)
    assert len(parsed) == 1
    assert parsed[0].decision == Stage1Decision.UNCERTAIN


@pytest.mark.asyncio
async def test_stage1_review_batches_calls(llm_config, intel_stats_stub):
    """7 candidates with batch_size=5 → 2 LLM calls, indices rebased correctly."""
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=[
        # batch 1: 5 candidates
        MagicMock(choices=[MagicMock(message=MagicMock(content=json.dumps([
            {"index": i, "decision": "advance", "confidence": "high", "reason": "x"}
            for i in range(5)
        ])))]),
        # batch 2: 2 candidates
        MagicMock(choices=[MagicMock(message=MagicMock(content=json.dumps([
            {"index": 0, "decision": "reject",   "confidence": "high", "reason": "y"},
            {"index": 1, "decision": "uncertain","confidence": "low",  "reason": "z"},
        ])))]),
    ])
    reviewer = CandidateReviewer(
        llm_config=llm_config,
        intel_stats=intel_stats_stub(),
        raw_lookup=None,
        client=mock_client,
    )
    cands = [_candidate_dict(key=f"k{i}") for i in range(7)]
    out = await reviewer.stage1_review(cands, batch_size=5)
    assert mock_client.chat.completions.create.call_count == 2
    assert len(out) == 7
    assert out[5].decision == Stage1Decision.REJECT      # global index 5 = batch2 idx 0
    assert out[6].decision == Stage1Decision.UNCERTAIN


def test_apply_downgrades_no_change(llm_config, intel_stats_stub):
    reviewer = CandidateReviewer(
        llm_config=llm_config, intel_stats=intel_stats_stub(), raw_lookup=None,
    )
    out = reviewer._apply_downgrades("high", levels=0)
    assert out == "high"


def test_apply_downgrades_one_level(llm_config, intel_stats_stub):
    reviewer = CandidateReviewer(
        llm_config=llm_config, intel_stats=intel_stats_stub(), raw_lookup=None,
    )
    assert reviewer._apply_downgrades("high",   levels=1) == "medium"
    assert reviewer._apply_downgrades("medium", levels=1) == "low"
    assert reviewer._apply_downgrades("low",    levels=1) == "low"  # floor


def test_apply_downgrades_two_levels(llm_config, intel_stats_stub):
    reviewer = CandidateReviewer(
        llm_config=llm_config, intel_stats=intel_stats_stub(), raw_lookup=None,
    )
    assert reviewer._apply_downgrades("high",   levels=2) == "low"
    assert reviewer._apply_downgrades("medium", levels=2) == "low"


class _RawLookupStub:
    def __init__(self, m):
        self._m = m
    def get(self, group_name, msg_id):
        return self._m.get((group_name, int(msg_id)))


def test_build_stage2_prompt_includes_raw_text(llm_config, intel_stats_stub):
    reviewer = CandidateReviewer(
        llm_config=llm_config,
        intel_stats=intel_stats_stub(),
        raw_lookup=_RawLookupStub({("卖号群", 100): "出抖音老号 联系 @douyinhao88"}),
    )
    c = _candidate_dict(
        key="douyinhao88",
        sources=[{"group": "卖号群", "msg_id": 100, "channel": "text"}],
    )
    prompt, found_count = reviewer._build_stage2_prompt(c, stage1=None)
    assert "douyinhao88" in prompt
    assert "出抖音老号 联系 @douyinhao88" in prompt
    assert found_count == 1


def test_build_stage2_prompt_marks_missing_raw_text(llm_config, intel_stats_stub):
    """When raw lookup misses, prompt notes [原文未找到] and returns found=0."""
    reviewer = CandidateReviewer(
        llm_config=llm_config,
        intel_stats=intel_stats_stub(),
        raw_lookup=_RawLookupStub({}),  # nothing indexed
    )
    c = _candidate_dict(
        key="douyinhao88",
        sources=[{"group": "卖号群", "msg_id": 100, "channel": "text"}],
    )
    prompt, found_count = reviewer._build_stage2_prompt(c, stage1=None)
    assert "[原文未找到]" in prompt
    assert found_count == 0


def test_parse_stage2_response_happy_path(llm_config, intel_stats_stub):
    reviewer = CandidateReviewer(
        llm_config=llm_config,
        intel_stats=intel_stats_stub(),
        raw_lookup=None,
    )
    raw = json.dumps({
        "decision": "approve",
        "confidence": "high",
        "risk_type": "账号交易",
        "reason": "明确卖号语境",
    })
    s2 = reviewer._parse_stage2_response(raw)
    assert s2.decision == "approve"
    assert s2.confidence == "high"
    assert s2.risk_type == "账号交易"


def test_parse_stage2_response_invalid_returns_none(llm_config, intel_stats_stub):
    reviewer = CandidateReviewer(
        llm_config=llm_config,
        intel_stats=intel_stats_stub(),
        raw_lookup=None,
    )
    assert reviewer._parse_stage2_response("not json") is None


@pytest.mark.asyncio
async def test_review_one_stage1_reject_skips_stage2(llm_config, intel_stats_stub):
    """If Stage 1 says reject, Stage 2 LLM is not called."""
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock()  # should never be called for stage2

    reviewer = CandidateReviewer(
        llm_config=llm_config,
        intel_stats=intel_stats_stub(),
        raw_lookup=None,
        client=mock_client,
    )
    s1 = Stage1Result(index=0, decision=Stage1Decision.REJECT,
                      confidence="high", reason="freebie group")
    verdict = await reviewer.review_one(_candidate_dict(), stage1=s1)
    assert verdict["verdict"] == "llm_rejected"
    assert verdict["stage"] == 1
    mock_client.chat.completions.create.assert_not_called()


@pytest.mark.asyncio
async def test_review_one_advance_approve_high_public(llm_config, intel_stats_stub):
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=MagicMock(
        choices=[MagicMock(message=MagicMock(content=json.dumps({
            "decision": "approve", "confidence": "high",
            "risk_type": "账号交易", "reason": "明确卖号",
        })))],
    ))
    reviewer = CandidateReviewer(
        llm_config=llm_config,
        intel_stats=intel_stats_stub(),
        raw_lookup=_RawLookupStub({("卖号群", 100): "出抖音号 @douyinhao88"}),
        client=mock_client,
    )
    s1 = Stage1Result(index=0, decision=Stage1Decision.ADVANCE,
                      confidence="high", reason="ok")
    c = _candidate_dict(key="douyinhao88",
                        sources=[{"group": "卖号群", "msg_id": 100, "channel": "text"}])
    verdict = await reviewer.review_one(c, stage1=s1)
    assert verdict["verdict"] == "llm_approved_high"
    assert verdict["confidence"] == "high"
    assert verdict["stage"] == 2
    assert verdict["risk_type"] == "账号交易"


@pytest.mark.asyncio
async def test_review_one_uncertain_downgrades_one_level(llm_config, intel_stats_stub):
    """uncertain Stage1 + approve high Stage2 → llm_approved_medium."""
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=MagicMock(
        choices=[MagicMock(message=MagicMock(content=json.dumps({
            "decision": "approve", "confidence": "high",
            "risk_type": "账号交易", "reason": "ok",
        })))],
    ))
    reviewer = CandidateReviewer(
        llm_config=llm_config,
        intel_stats=intel_stats_stub(),
        raw_lookup=_RawLookupStub({("卖号群", 100): "x"}),
        client=mock_client,
    )
    s1 = Stage1Result(index=0, decision=Stage1Decision.UNCERTAIN,
                      confidence="low", reason="ambig")
    verdict = await reviewer.review_one(
        _candidate_dict(sources=[{"group": "卖号群", "msg_id": 100, "channel": "text"}]),
        stage1=s1,
    )
    assert verdict["verdict"] == "llm_approved_medium"


@pytest.mark.asyncio
async def test_review_one_private_group_downgrades_one_level(llm_config, intel_stats_stub):
    """private candidate (+hash) + advance + approve high → llm_approved_medium."""
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=MagicMock(
        choices=[MagicMock(message=MagicMock(content=json.dumps({
            "decision": "approve", "confidence": "high",
            "risk_type": "账号交易", "reason": "ok",
        })))],
    ))
    reviewer = CandidateReviewer(
        llm_config=llm_config,
        intel_stats=intel_stats_stub(),
        raw_lookup=_RawLookupStub({("卖号群", 100): "x"}),
        client=mock_client,
    )
    s1 = Stage1Result(index=0, decision=Stage1Decision.ADVANCE,
                      confidence="high", reason="ok")
    c = _candidate_dict(
        key="+abcXYZ", invite_hash="abcXYZ",
        sources=[{"group": "卖号群", "msg_id": 100, "channel": "text"}],
    )
    verdict = await reviewer.review_one(c, stage1=s1)
    assert verdict["verdict"] == "llm_approved_medium"


@pytest.mark.asyncio
async def test_review_one_missing_raw_text_downgrades(llm_config, intel_stats_stub):
    """advance + approve high, but raw text not found → llm_approved_medium."""
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=MagicMock(
        choices=[MagicMock(message=MagicMock(content=json.dumps({
            "decision": "approve", "confidence": "high",
            "risk_type": "账号交易", "reason": "ok",
        })))],
    ))
    reviewer = CandidateReviewer(
        llm_config=llm_config,
        intel_stats=intel_stats_stub(),
        raw_lookup=_RawLookupStub({}),  # all lookups miss
        client=mock_client,
    )
    s1 = Stage1Result(index=0, decision=Stage1Decision.ADVANCE,
                      confidence="high", reason="ok")
    verdict = await reviewer.review_one(
        _candidate_dict(sources=[{"group": "卖号群", "msg_id": 100, "channel": "text"}]),
        stage1=s1,
    )
    assert verdict["verdict"] == "llm_approved_medium"


@pytest.mark.asyncio
async def test_review_one_stage2_reject_returns_llm_rejected(llm_config, intel_stats_stub):
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=MagicMock(
        choices=[MagicMock(message=MagicMock(content=json.dumps({
            "decision": "reject", "confidence": "high",
            "risk_type": "", "reason": "actually unrelated",
        })))],
    ))
    reviewer = CandidateReviewer(
        llm_config=llm_config,
        intel_stats=intel_stats_stub(),
        raw_lookup=_RawLookupStub({("卖号群", 100): "x"}),
        client=mock_client,
    )
    s1 = Stage1Result(index=0, decision=Stage1Decision.ADVANCE,
                      confidence="high", reason="ok")
    verdict = await reviewer.review_one(
        _candidate_dict(sources=[{"group": "卖号群", "msg_id": 100, "channel": "text"}]),
        stage1=s1,
    )
    assert verdict["verdict"] == "llm_rejected"
    assert verdict["stage"] == 2


@pytest.mark.asyncio
async def test_review_one_stage2_llm_failure_returns_none(llm_config, intel_stats_stub):
    """Stage 2 LLM error → return None so the candidate is skipped, not rejected."""
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        side_effect=RuntimeError("network down"))
    reviewer = CandidateReviewer(
        llm_config=llm_config,
        intel_stats=intel_stats_stub(),
        raw_lookup=_RawLookupStub({("卖号群", 100): "x"}),
        client=mock_client,
    )
    s1 = Stage1Result(index=0, decision=Stage1Decision.ADVANCE,
                      confidence="high", reason="ok")
    verdict = await reviewer.review_one(
        _candidate_dict(sources=[{"group": "卖号群", "msg_id": 100, "channel": "text"}]),
        stage1=s1,
    )
    assert verdict is None
