"""Tests for CandidatePool — yaml-backed pool of group candidates."""

from datetime import datetime, timezone

import pytest
import yaml

from tg_intel_crawler.collector.candidate_pool import CandidatePool
from tg_intel_crawler.collector.group_extractor import CandidateSignal


def _signal(
    username: str | None = "douyinhao88",
    invite_hash: str | None = None,
    channel: str = "text",
    source_group: str = "src_grp",
    source_msg_id: int = 100,
    seen_at: datetime | None = None,
) -> CandidateSignal:
    return CandidateSignal(
        username=username,
        invite_hash=invite_hash,
        channel=channel,
        source_group=source_group,
        source_msg_id=source_msg_id,
        seen_at=seen_at or datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def pool_path(tmp_path):
    return tmp_path / "discovered_groups.yaml"


def test_merge_creates_new_candidate(pool_path):
    pool = CandidatePool(str(pool_path))
    pool.merge([_signal(username="newgrp")])
    pool.flush()

    raw = yaml.safe_load(pool_path.read_text(encoding="utf-8"))
    assert "newgrp" in raw["candidates"]
    entry = raw["candidates"]["newgrp"]
    assert entry["count"] == 1
    assert entry["status"] == "pending"
    assert len(entry["sources"]) == 1


def test_merge_increments_count_for_existing_username(pool_path):
    pool = CandidatePool(str(pool_path))
    pool.merge([_signal(username="dup", source_msg_id=1)])
    pool.merge([_signal(username="dup", source_msg_id=2)])
    pool.flush()

    raw = yaml.safe_load(pool_path.read_text(encoding="utf-8"))
    assert raw["candidates"]["dup"]["count"] == 2


def test_sources_capped_at_three(pool_path):
    pool = CandidatePool(str(pool_path))
    for i in range(5):
        pool.merge([_signal(username="busy", source_msg_id=i)])
    pool.flush()

    raw = yaml.safe_load(pool_path.read_text(encoding="utf-8"))
    sources = raw["candidates"]["busy"]["sources"]
    assert len(sources) == 3
    # Should preserve the FIRST 3, not the last 3 (per spec).
    assert [s["msg_id"] for s in sources] == [0, 1, 2]


def test_invite_hash_candidate_keyed_with_plus(pool_path):
    pool = CandidatePool(str(pool_path))
    pool.merge([_signal(username=None, invite_hash="abc123")])
    pool.flush()

    raw = yaml.safe_load(pool_path.read_text(encoding="utf-8"))
    assert "+abc123" in raw["candidates"]
    entry = raw["candidates"]["+abc123"]
    assert entry["invite_hash"] == "abc123"


def test_load_existing_yaml_round_trip(pool_path):
    pool1 = CandidatePool(str(pool_path))
    pool1.merge([_signal(username="persist")])
    pool1.flush()

    # New instance: should see the persisted candidate.
    pool2 = CandidatePool(str(pool_path))
    candidates = pool2.list_all()
    assert any(c["key"] == "persist" for c in candidates)


def test_approve_changes_status(pool_path):
    pool = CandidatePool(str(pool_path))
    pool.merge([_signal(username="tojoin")])
    pool.approve(["tojoin"])
    pool.flush()

    raw = yaml.safe_load(pool_path.read_text(encoding="utf-8"))
    assert raw["candidates"]["tojoin"]["status"] == "approved"


def test_reject_changes_status(pool_path):
    pool = CandidatePool(str(pool_path))
    pool.merge([_signal(username="badbot")])
    pool.reject(["badbot"])
    pool.flush()

    raw = yaml.safe_load(pool_path.read_text(encoding="utf-8"))
    assert raw["candidates"]["badbot"]["status"] == "rejected"


def test_rejected_candidates_not_re_added_on_merge(pool_path):
    """Once rejected, future signals shouldn't flip the status back to pending."""
    pool = CandidatePool(str(pool_path))
    pool.merge([_signal(username="spam")])
    pool.reject(["spam"])

    pool.merge([_signal(username="spam", source_msg_id=999)])  # seen again
    pool.flush()

    raw = yaml.safe_load(pool_path.read_text(encoding="utf-8"))
    assert raw["candidates"]["spam"]["status"] == "rejected"


def test_list_filtered_by_status(pool_path):
    pool = CandidatePool(str(pool_path))
    pool.merge([_signal(username="a")])
    pool.merge([_signal(username="b")])
    pool.merge([_signal(username="c")])
    pool.approve(["a"])
    pool.reject(["b"])

    pending = pool.list_all(status="pending")
    assert {c["key"] for c in pending} == {"c"}


def test_missing_file_treated_as_empty(pool_path):
    pool = CandidatePool(str(pool_path))
    assert pool.list_all() == []


def test_flush_creates_parent_directory(tmp_path):
    nested = tmp_path / "nested" / "config" / "discovered.yaml"
    pool = CandidatePool(str(nested))
    pool.merge([_signal(username="x")])
    pool.flush()
    assert nested.exists()


def test_last_seen_updates_on_repeated_merge(pool_path):
    pool = CandidatePool(str(pool_path))
    early = datetime(2026, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
    late = datetime(2026, 6, 5, 22, 0, 0, tzinfo=timezone.utc)

    pool.merge([_signal(username="ts", seen_at=early)])
    pool.merge([_signal(username="ts", seen_at=late, source_msg_id=2)])
    pool.flush()

    raw = yaml.safe_load(pool_path.read_text(encoding="utf-8"))
    entry = raw["candidates"]["ts"]
    # first_seen is the earliest; last_seen is the latest
    assert entry["first_seen"].startswith("2026-06-01")
    assert entry["last_seen"].startswith("2026-06-05")


def test_approved_candidate_returns_link_for_join(pool_path):
    pool = CandidatePool(str(pool_path))
    pool.merge([_signal(username="public_grp")])
    pool.merge([_signal(username=None, invite_hash="privhash")])

    links = pool.approved_links()
    assert links == []  # nothing approved yet

    pool.approve(["public_grp", "+privhash"])
    links = sorted(pool.approved_links())
    assert links == sorted([
        "https://t.me/public_grp",
        "https://t.me/+privhash",
    ])


def test_pending_for_review_returns_unreviewed_pending(pool_path):
    pool = CandidatePool(str(pool_path))
    pool.merge([_signal(username="a")])
    pool.flush()

    now = datetime(2026, 6, 6, 0, 0, 0, tzinfo=timezone.utc)
    items = pool.pending_for_review(now=now)

    assert len(items) == 1
    assert items[0]["key"] == "a"


def test_pending_for_review_skips_approved_and_rejected(pool_path):
    pool = CandidatePool(str(pool_path))
    pool.merge([_signal(username="a"), _signal(username="b"), _signal(username="c")])
    pool.approve(["a"])
    pool.reject(["c"])
    pool.flush()

    now = datetime(2026, 6, 6, 0, 0, 0, tzinfo=timezone.utc)
    items = pool.pending_for_review(now=now)

    keys = {it["key"] for it in items}
    assert keys == {"b"}


def test_pending_for_review_skips_recently_reviewed(pool_path):
    """Reviewed within stale_days, count not grown → skipped."""
    pool = CandidatePool(str(pool_path))
    pool.merge([_signal(username="a")])
    pool.set_llm_verdict("a", {
        "verdict": "llm_approved_high",
        "confidence": "high",
        "risk_type": "账号交易",
        "reason": "ok",
        "reviewed_at": "2026-06-05T00:00:00+00:00",
        "reviewed_count": 1,
        "stage": 2,
        "model": "ep-test",
    })
    pool.flush()

    now = datetime(2026, 6, 6, 0, 0, 0, tzinfo=timezone.utc)
    assert pool.pending_for_review(now=now) == []


def test_pending_for_review_picks_up_count_doubled(pool_path):
    pool = CandidatePool(str(pool_path))
    # First merge: count=1
    pool.merge([_signal(username="a", source_msg_id=1)])
    pool.set_llm_verdict("a", {
        "verdict": "llm_rejected",
        "confidence": "low",
        "risk_type": "",
        "reason": "ok",
        "reviewed_at": "2026-06-05T00:00:00+00:00",
        "reviewed_count": 1,
        "stage": 1,
        "model": "ep-test",
    })
    # Now mention 2 more times → count = 3 > 1 * 2 → re-review
    pool.merge([_signal(username="a", source_msg_id=2), _signal(username="a", source_msg_id=3)])
    pool.flush()

    now = datetime(2026, 6, 6, 0, 0, 0, tzinfo=timezone.utc)
    items = pool.pending_for_review(now=now)
    assert {it["key"] for it in items} == {"a"}


def test_pending_for_review_picks_up_stale(pool_path):
    pool = CandidatePool(str(pool_path))
    pool.merge([_signal(username="a")])
    pool.set_llm_verdict("a", {
        "verdict": "llm_approved_low",
        "confidence": "low",
        "risk_type": "",
        "reason": "ok",
        "reviewed_at": "2026-04-01T00:00:00+00:00",  # 60+ days old
        "reviewed_count": 1,
        "stage": 2,
        "model": "ep-test",
    })
    pool.flush()

    now = datetime(2026, 6, 6, 0, 0, 0, tzinfo=timezone.utc)
    items = pool.pending_for_review(now=now, stale_days=30)
    assert {it["key"] for it in items} == {"a"}


def test_pending_for_review_force_rereview_picks_up_everything_pending(pool_path):
    pool = CandidatePool(str(pool_path))
    pool.merge([_signal(username="a"), _signal(username="b")])
    pool.set_llm_verdict("a", {
        "verdict": "llm_approved_high",
        "confidence": "high",
        "risk_type": "账号交易",
        "reason": "ok",
        "reviewed_at": "2026-06-05T00:00:00+00:00",
        "reviewed_count": 1,
        "stage": 2,
        "model": "ep-test",
    })
    pool.flush()

    now = datetime(2026, 6, 6, 0, 0, 0, tzinfo=timezone.utc)
    items = pool.pending_for_review(now=now, force_rereview=True)
    assert {it["key"] for it in items} == {"a", "b"}


def test_set_llm_verdict_writes_field_and_does_not_touch_status(pool_path):
    pool = CandidatePool(str(pool_path))
    pool.merge([_signal(username="a")])
    pool.set_llm_verdict("a", {
        "verdict": "llm_approved_high",
        "confidence": "high",
        "risk_type": "账号交易",
        "reason": "ok",
        "reviewed_at": "2026-06-06T00:00:00+00:00",
        "reviewed_count": 1,
        "stage": 2,
        "model": "ep-test",
    })
    pool.flush()

    raw = yaml.safe_load(pool_path.read_text(encoding="utf-8"))
    entry = raw["candidates"]["a"]
    assert entry["status"] == "pending"  # unchanged
    assert entry["llm_verdict"]["verdict"] == "llm_approved_high"
    assert entry["llm_verdict"]["confidence"] == "high"


def test_set_llm_verdict_unknown_key_is_noop(pool_path):
    """Setting verdict on a key not in the pool must not crash."""
    pool = CandidatePool(str(pool_path))
    # Must use a valid verdict because validation runs BEFORE the unknown-key short-circuit.
    pool.set_llm_verdict("does_not_exist", {"verdict": "llm_rejected"})
    pool.flush()
    # Just shouldn't raise.


def test_set_llm_verdict_validates_verdict_field(pool_path):
    """Invalid 'verdict' value must raise ValueError."""
    pool = CandidatePool(str(pool_path))
    with pytest.raises(ValueError):
        pool.set_llm_verdict("k", {"verdict": "bogus"})


def test_apply_llm_approvals_promotes_high_and_medium(pool_path):
    pool = CandidatePool(str(pool_path))
    pool.merge([
        _signal(username="hi"),
        _signal(username="med"),
        _signal(username="lo"),
        _signal(username="rej"),
    ])
    pool.set_llm_verdict("hi", {"verdict": "llm_approved_high",   "confidence": "high",
                                 "reviewed_at": "2026-06-06T00:00:00+00:00",
                                 "reviewed_count": 1, "stage": 2, "model": "ep"})
    pool.set_llm_verdict("med", {"verdict": "llm_approved_medium", "confidence": "medium",
                                 "reviewed_at": "2026-06-06T00:00:00+00:00",
                                 "reviewed_count": 1, "stage": 2, "model": "ep"})
    pool.set_llm_verdict("lo", {"verdict": "llm_approved_low",     "confidence": "low",
                                 "reviewed_at": "2026-06-06T00:00:00+00:00",
                                 "reviewed_count": 1, "stage": 2, "model": "ep"})
    pool.set_llm_verdict("rej", {"verdict": "llm_rejected",        "confidence": "low",
                                 "reviewed_at": "2026-06-06T00:00:00+00:00",
                                 "reviewed_count": 1, "stage": 1, "model": "ep"})

    promoted = pool.apply_llm_approvals()

    keys = {p["key"] for p in promoted}
    assert keys == {"hi", "med"}
    # status side-effect
    statuses = {k: pool._candidates[k]["status"] for k in ("hi", "med", "lo", "rej")}
    assert statuses == {"hi": "approved", "med": "approved", "lo": "pending", "rej": "pending"}


def test_apply_llm_approvals_returns_links_for_public_and_private(pool_path):
    pool = CandidatePool(str(pool_path))
    pool.merge([
        _signal(username="pub"),
        _signal(username=None, invite_hash="abcXYZ"),
    ])
    pool.set_llm_verdict("pub", {"verdict": "llm_approved_high", "confidence": "high",
                                 "reviewed_at": "2026-06-06T00:00:00+00:00",
                                 "reviewed_count": 1, "stage": 2, "model": "ep"})
    pool.set_llm_verdict("+abcXYZ", {"verdict": "llm_approved_high", "confidence": "high",
                                 "reviewed_at": "2026-06-06T00:00:00+00:00",
                                 "reviewed_count": 1, "stage": 2, "model": "ep"})

    promoted = pool.apply_llm_approvals()
    by_key = {p["key"]: p for p in promoted}
    assert by_key["pub"]["link"] == "https://t.me/pub"
    assert by_key["+abcXYZ"]["link"] == "https://t.me/+abcXYZ"
    assert by_key["pub"]["confidence"] == "high"


def test_apply_llm_approvals_idempotent_on_already_approved(pool_path):
    """Already-approved candidates should not appear in the promoted list a second time."""
    pool = CandidatePool(str(pool_path))
    pool.merge([_signal(username="x")])
    pool.set_llm_verdict("x", {"verdict": "llm_approved_high", "confidence": "high",
                               "reviewed_at": "2026-06-06T00:00:00+00:00",
                               "reviewed_count": 1, "stage": 2, "model": "ep"})
    promoted_1 = pool.apply_llm_approvals()
    promoted_2 = pool.apply_llm_approvals()
    assert len(promoted_1) == 1
    assert promoted_2 == []
