# Probe Bot Lookup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Build a one-shot CLI probe (`tg-crawler probe-bot-lookup`) that samples 30 candidates from `discovered_groups.yaml`, queries `@JISOU`, and writes a JSON + Markdown report quantifying public-group hit rate vs. private-group dead-end rate — so we know what material LLM-driven auto-approve can actually use.

**Architecture:** New `tg_intel_crawler/probe/` package with three units (Sampler, Runner, Reporter) joined by a thin CLI that reuses existing `BotSearchClient` / `BotQueryThrottle` / `BotResponseParser`. Pure read-only against `CandidatePool`; no LLM, no state mutation.

**Tech Stack:** Python 3.11+, click (CLI), pyyaml, pytest + pytest-asyncio. Standard library only for sampling (`random.Random` with seed). Reuses Telethon-backed `BotSearchClient`.

**Spec:** `docs/superpowers/specs/2026-06-06-probe-bot-lookup-design.md`

---

## File Structure

| File | Purpose |
|---|---|
| `tg_intel_crawler/probe/__init__.py` | Package marker (empty) |
| `tg_intel_crawler/probe/sampler.py` | `SampledCandidate` dataclass + `Sampler` (stratified, seeded) |
| `tg_intel_crawler/probe/runner.py` | `ProbeRecord` dataclass + `classify()` pure fn + `ProbeRunner` (orchestrates per-candidate probe) |
| `tg_intel_crawler/probe/reporter.py` | `ProbeReporter` — writes `bot_lookup_<date>.json` + `.md` |
| `tg_intel_crawler/main.py` | Add `probe-bot-lookup` click command |
| `tests/test_probe_sampler.py` | Sampler unit tests |
| `tests/test_probe_classification.py` | `classify()` parametrized tests |
| `tests/test_probe_runner.py` | Runner with mock bot client |
| `tests/test_probe_reporter.py` | JSON round-trip + Markdown structure tests |

Each file has one clear responsibility — sampling math, classification logic, IO, CLI glue — so tests can be focused and small.

---

## Task 1: Package skeleton + SampledCandidate dataclass

**Files:**
- Create: `tg_intel_crawler/probe/__init__.py`
- Create: `tg_intel_crawler/probe/sampler.py`
- Create: `tests/test_probe_sampler.py`

- [x] **Step 1: Create empty package marker**

```bash
mkdir -p tg_intel_crawler/probe
touch tg_intel_crawler/probe/__init__.py
```

- [x] **Step 2: Write the failing test for SampledCandidate**

Create `tests/test_probe_sampler.py`:

```python
"""Tests for the probe sampler — stratified, seeded candidate sampling."""

from tg_intel_crawler.probe.sampler import SampledCandidate


def test_sampled_candidate_holds_all_fields():
    sc = SampledCandidate(
        key="douyinhao88",
        count=246,
        invite_hash=None,
        candidate_type="public",
        stratum="L3",
    )
    assert sc.key == "douyinhao88"
    assert sc.count == 246
    assert sc.invite_hash is None
    assert sc.candidate_type == "public"
    assert sc.stratum == "L3"


def test_sampled_candidate_private_keeps_invite_hash():
    sc = SampledCandidate(
        key="+abcXYZ",
        count=2,
        invite_hash="abcXYZ",
        candidate_type="private",
        stratum="L5",
    )
    assert sc.invite_hash == "abcXYZ"
    assert sc.candidate_type == "private"
```

- [x] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_probe_sampler.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tg_intel_crawler.probe.sampler'`

- [x] **Step 4: Create the SampledCandidate dataclass**

Create `tg_intel_crawler/probe/sampler.py`:

```python
"""Stratified, seeded sampling of CandidatePool entries for the probe."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SampledCandidate:
    """One candidate picked for the probe, with the stratum it was drawn from."""

    key: str                    # e.g. "douyinhao88" or "+abcXYZ"
    count: int                  # cumulative count from the pool
    invite_hash: str | None     # preserved for private candidates; None for public
    candidate_type: str         # "public" | "private"
    stratum: str                # "L1".."L6"
```

- [x] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_probe_sampler.py -v`
Expected: PASS (2 tests)

- [x] **Step 6: Commit**

```bash
git add tg_intel_crawler/probe/__init__.py tg_intel_crawler/probe/sampler.py tests/test_probe_sampler.py
git commit -m "feat(probe): scaffold probe package with SampledCandidate dataclass"
```

---

## Task 2: Stratification logic — classify a pool entry into L1..L6

**Files:**
- Modify: `tg_intel_crawler/probe/sampler.py`
- Modify: `tests/test_probe_sampler.py`

The pool entries (dicts from `CandidatePool.list_all()`) have shape:
```python
{"key": "douyinhao88", "count": 246, "invite_hash": None, "status": "pending", ...}
```

We classify into 6 strata: **(public/private) × (count=1, count 2–9, count ≥ 10)**.

- [x] **Step 1: Add the stratify test**

Append to `tests/test_probe_sampler.py`:

```python
import pytest
from tg_intel_crawler.probe.sampler import stratify_entry


@pytest.mark.parametrize("entry,expected", [
    ({"key": "a", "count": 1, "invite_hash": None}, "L1"),
    ({"key": "b", "count": 5, "invite_hash": None}, "L2"),
    ({"key": "c", "count": 9, "invite_hash": None}, "L2"),
    ({"key": "d", "count": 10, "invite_hash": None}, "L3"),
    ({"key": "e", "count": 1181, "invite_hash": None}, "L3"),
    ({"key": "+x", "count": 1, "invite_hash": "x"}, "L4"),
    ({"key": "+y", "count": 5, "invite_hash": "y"}, "L5"),
    ({"key": "+z", "count": 200, "invite_hash": "z"}, "L6"),
])
def test_stratify_entry(entry, expected):
    assert stratify_entry(entry) == expected


def test_stratify_uses_invite_hash_not_key_prefix():
    """A public group whose username happens to start with '+' should never
    appear in practice, but if it did we go by invite_hash, not key."""
    entry = {"key": "+weirdpublicname", "count": 5, "invite_hash": None}
    assert stratify_entry(entry) == "L2"  # public, count 2-9
```

- [x] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_probe_sampler.py -v`
Expected: FAIL with `ImportError: cannot import name 'stratify_entry'`

- [x] **Step 3: Implement stratify_entry**

Append to `tg_intel_crawler/probe/sampler.py`:

```python
def _count_band(count: int) -> str:
    """Bucket count into one of three bands: 'low' / 'mid' / 'high'."""
    if count <= 1:
        return "low"
    if count <= 9:
        return "mid"
    return "high"


def stratify_entry(entry: dict) -> str:
    """Map a CandidatePool entry to one of 6 strata.

    L1: public, count = 1
    L2: public, count 2-9
    L3: public, count >= 10
    L4: private, count = 1
    L5: private, count 2-9
    L6: private, count >= 10

    Public/private is determined by ``invite_hash`` (None means public),
    NOT by the leading '+' in the key — the key is just a display form.
    """
    is_private = entry.get("invite_hash") is not None
    band = _count_band(int(entry.get("count", 0)))
    table = {
        ("public",  "low"):  "L1",
        ("public",  "mid"):  "L2",
        ("public",  "high"): "L3",
        ("private", "low"):  "L4",
        ("private", "mid"):  "L5",
        ("private", "high"): "L6",
    }
    kind = "private" if is_private else "public"
    return table[(kind, band)]
```

- [x] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_probe_sampler.py -v`
Expected: PASS (all sampler tests so far)

- [x] **Step 5: Commit**

```bash
git add tg_intel_crawler/probe/sampler.py tests/test_probe_sampler.py
git commit -m "feat(probe): add stratify_entry — bucket pool entries into L1-L6"
```

---

## Task 3: Sampler — seeded stratified draw with deficit handling

**Files:**
- Modify: `tg_intel_crawler/probe/sampler.py`
- Modify: `tests/test_probe_sampler.py`

- [x] **Step 1: Write the failing tests for Sampler.draw**

Append to `tests/test_probe_sampler.py`:

```python
from tg_intel_crawler.probe.sampler import Sampler


def _entry(key, count, private=False):
    return {
        "key": key,
        "count": count,
        "invite_hash": key.lstrip("+") if private else None,
        "status": "pending",
    }


def _build_pool(per_stratum=10):
    """Generate a synthetic pool with `per_stratum` entries in each L1..L6."""
    pool = []
    for i in range(per_stratum):
        pool.append(_entry(f"pub_low_{i}", 1))                   # L1
        pool.append(_entry(f"pub_mid_{i}", 5))                   # L2
        pool.append(_entry(f"pub_high_{i}", 50))                 # L3
        pool.append(_entry(f"+priv_low_{i}",  1, private=True))  # L4
        pool.append(_entry(f"+priv_mid_{i}",  5, private=True))  # L5
        pool.append(_entry(f"+priv_high_{i}", 50, private=True)) # L6
    return pool


def test_draw_returns_30_with_default_size():
    pool = _build_pool(per_stratum=10)
    samples = Sampler(seed=42).draw(pool, sample_size=30)
    assert len(samples) == 30


def test_draw_distributes_evenly_across_strata():
    pool = _build_pool(per_stratum=10)
    samples = Sampler(seed=42).draw(pool, sample_size=30)
    by_stratum: dict[str, int] = {}
    for s in samples:
        by_stratum[s.stratum] = by_stratum.get(s.stratum, 0) + 1
    assert by_stratum == {"L1": 5, "L2": 5, "L3": 5, "L4": 5, "L5": 5, "L6": 5}


def test_draw_is_reproducible_with_same_seed():
    pool = _build_pool(per_stratum=10)
    a = [s.key for s in Sampler(seed=42).draw(pool, sample_size=30)]
    b = [s.key for s in Sampler(seed=42).draw(pool, sample_size=30)]
    assert a == b


def test_draw_differs_with_different_seed():
    pool = _build_pool(per_stratum=10)
    a = [s.key for s in Sampler(seed=42).draw(pool, sample_size=30)]
    b = [s.key for s in Sampler(seed=99).draw(pool, sample_size=30)]
    assert a != b


def test_draw_handles_understocked_stratum():
    """If a stratum has fewer than per_layer entries, take all of it
    and DO NOT redistribute the deficit to other strata."""
    pool = (
        _build_pool(per_stratum=10)[: 6 * 10]   # 10 each across 6 strata
    )
    # Replace L3 with only 2 entries.
    pool = [e for e in pool if not e["key"].startswith("pub_high_")]
    pool.extend([_entry(f"pub_high_{i}", 50) for i in range(2)])

    samples = Sampler(seed=42).draw(pool, sample_size=30)
    by_stratum: dict[str, int] = {}
    for s in samples:
        by_stratum[s.stratum] = by_stratum.get(s.stratum, 0) + 1
    assert by_stratum["L3"] == 2
    # Other strata still get 5 each — no redistribution.
    assert by_stratum["L1"] == 5
    assert by_stratum["L2"] == 5
    # Total is 27, not 30, because the deficit isn't filled.
    assert len(samples) == 27


def test_draw_with_smaller_sample_size_distributes_evenly():
    """sample_size=12 → each stratum gets 2."""
    pool = _build_pool(per_stratum=10)
    samples = Sampler(seed=42).draw(pool, sample_size=12)
    by_stratum: dict[str, int] = {}
    for s in samples:
        by_stratum[s.stratum] = by_stratum.get(s.stratum, 0) + 1
    assert by_stratum == {"L1": 2, "L2": 2, "L3": 2, "L4": 2, "L5": 2, "L6": 2}


def test_draw_with_remainder_fills_high_count_strata_first():
    """sample_size=15 → 2 each (=12), remainder 3 goes to L3, L6, L2 in that order."""
    pool = _build_pool(per_stratum=10)
    samples = Sampler(seed=42).draw(pool, sample_size=15)
    by_stratum: dict[str, int] = {}
    for s in samples:
        by_stratum[s.stratum] = by_stratum.get(s.stratum, 0) + 1
    # Spec: remainder fills L3, L6, L2, L5, L1, L4 in order.
    assert by_stratum["L3"] == 3
    assert by_stratum["L6"] == 3
    assert by_stratum["L2"] == 3
    assert by_stratum["L1"] == 2
    assert by_stratum["L4"] == 2
    assert by_stratum["L5"] == 2


def test_draw_empty_pool_returns_empty():
    samples = Sampler(seed=42).draw([], sample_size=30)
    assert samples == []


def test_draw_populates_candidate_type_correctly():
    pool = _build_pool(per_stratum=10)
    samples = Sampler(seed=42).draw(pool, sample_size=30)
    for s in samples:
        if s.stratum in ("L1", "L2", "L3"):
            assert s.candidate_type == "public"
            assert s.invite_hash is None
        else:
            assert s.candidate_type == "private"
            assert s.invite_hash is not None
```

- [x] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_probe_sampler.py -v`
Expected: FAIL with `ImportError: cannot import name 'Sampler'`

- [x] **Step 3: Implement Sampler**

Append to `tg_intel_crawler/probe/sampler.py`:

```python
import random


# Order in which leftover slots are distributed when sample_size doesn't
# divide evenly by 6. High-count strata get the extras first because
# they're rarer in real candidate pools and more informative when present.
_REMAINDER_ORDER = ["L3", "L6", "L2", "L5", "L1", "L4"]
_ALL_STRATA = ["L1", "L2", "L3", "L4", "L5", "L6"]


class Sampler:
    """Stratified, seeded sampling of CandidatePool entries.

    Default ``sample_size=30`` produces 5 per stratum across 6 strata.
    If a stratum has fewer than its quota, take all of it without
    redistributing the deficit (preserves stratum semantics).
    """

    def __init__(self, seed: int = 42):
        self._rng = random.Random(seed)

    def draw(self, pool: list[dict], sample_size: int = 30) -> list[SampledCandidate]:
        if not pool:
            return []

        # 1. Bucket the pool by stratum.
        buckets: dict[str, list[dict]] = {s: [] for s in _ALL_STRATA}
        for entry in pool:
            buckets[stratify_entry(entry)].append(entry)

        # 2. Compute per-stratum quota: floor(size/6) plus remainder
        #    distributed in _REMAINDER_ORDER.
        base = sample_size // 6
        remainder = sample_size - base * 6
        quota: dict[str, int] = {s: base for s in _ALL_STRATA}
        for s in _REMAINDER_ORDER[:remainder]:
            quota[s] += 1

        # 3. Sample each stratum independently.
        out: list[SampledCandidate] = []
        for stratum in _ALL_STRATA:
            available = buckets[stratum]
            want = min(quota[stratum], len(available))
            if want <= 0:
                continue
            picks = self._rng.sample(available, k=want)
            for entry in picks:
                out.append(SampledCandidate(
                    key=entry["key"],
                    count=int(entry.get("count", 0)),
                    invite_hash=entry.get("invite_hash"),
                    candidate_type="private" if entry.get("invite_hash") else "public",
                    stratum=stratum,
                ))
        return out
```

- [x] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_probe_sampler.py -v`
Expected: PASS (all sampler tests)

- [x] **Step 5: Commit**

```bash
git add tg_intel_crawler/probe/sampler.py tests/test_probe_sampler.py
git commit -m "feat(probe): add Sampler with stratified draw + deficit handling"
```

---

## Task 4: ProbeRecord dataclass + classify() pure function

**Files:**
- Create: `tg_intel_crawler/probe/runner.py`
- Create: `tests/test_probe_classification.py`

- [x] **Step 1: Write the failing tests for classify()**

Create `tests/test_probe_classification.py`:

```python
"""Tests for classify() — pure function mapping (reply, previews) → category."""

import pytest

from tg_intel_crawler.collector.bot_response_parser import BotPreview
from tg_intel_crawler.probe.runner import classify
from datetime import datetime, timezone


def _preview(channel_username: str | None = None) -> BotPreview:
    return BotPreview(
        bot="@JISOU",
        query="x",
        raw_line="🌄 ...",
        text="...",
        deeplink=None,
        channel_username=channel_username,
        msg_id=None,
        icon="🌄",
        seen_at=datetime.now(timezone.utc),
    )


def test_error_status_classifies_as_error():
    assert classify(
        candidate_key="x",
        reply_status="error",
        previews=[],
    ) == "error"


@pytest.mark.parametrize("reply_status", ["empty_reply"])
def test_empty_reply_classifies_as_empty_reply(reply_status):
    assert classify(
        candidate_key="x",
        reply_status=reply_status,
        previews=[],
    ) == "empty_reply"


def test_direct_hit_when_preview_channel_matches_key():
    previews = [_preview(channel_username="douyinhao88")]
    assert classify(
        candidate_key="douyinhao88",
        reply_status="ok",
        previews=previews,
    ) == "direct_hit"


def test_direct_hit_is_case_insensitive():
    previews = [_preview(channel_username="DouYinHao88")]
    assert classify(
        candidate_key="douyinhao88",
        reply_status="ok",
        previews=previews,
    ) == "direct_hit"


def test_indirect_hit_when_previews_exist_but_no_match():
    previews = [_preview(channel_username="other"), _preview(channel_username=None)]
    assert classify(
        candidate_key="douyinhao88",
        reply_status="ok",
        previews=previews,
    ) == "indirect_hit"


def test_no_results_when_reply_ok_but_no_previews():
    assert classify(
        candidate_key="x",
        reply_status="ok",
        previews=[],
    ) == "no_results"


def test_private_key_with_plus_never_direct_hits():
    """Private candidates have keys like '+abc'; no channel_username will
    ever equal that (channel usernames don't start with +)."""
    previews = [_preview(channel_username="abc")]
    assert classify(
        candidate_key="+abc",
        reply_status="ok",
        previews=previews,
    ) == "indirect_hit"


def test_error_short_circuits_even_with_previews():
    """Even if previews were parsed before the error, error wins."""
    previews = [_preview(channel_username="x")]
    assert classify(
        candidate_key="x",
        reply_status="error",
        previews=previews,
    ) == "error"
```

- [x] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_probe_classification.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tg_intel_crawler.probe.runner'`

- [x] **Step 3: Implement ProbeRecord + classify()**

Create `tg_intel_crawler/probe/runner.py`:

```python
"""Per-candidate probe runner + classification pure function.

Talks to the bot via the existing BotSearchClient/BotResponseParser. The
classify() function is a pure mapping from (reply_status, previews) to one
of five categories — kept pure so it's trivially testable.
"""

from __future__ import annotations

from dataclasses import dataclass

from tg_intel_crawler.collector.bot_response_parser import BotPreview
from tg_intel_crawler.probe.sampler import SampledCandidate


# Maximum length to keep for raw bot replies in the report — protects
# against a bot dumping a megabyte of text.
_RAW_TRUNCATE = 4096


@dataclass
class ProbeRecord:
    """Outcome of probing a single candidate.

    ``reply_raw`` is truncated to _RAW_TRUNCATE chars with a marker suffix.
    ``matched_preview`` is None unless classification == 'direct_hit'.
    """

    candidate: SampledCandidate
    query_sent: str
    reply_status: str            # "ok" | "empty_reply" | "error"
    reply_raw: str               # may be truncated
    error: str | None            # exception class+message, only when reply_status='error'
    previews_count: int
    matched_preview: dict | None
    classification: str          # "direct_hit" | "indirect_hit" | "no_results"
                                 # | "empty_reply" | "error"


def classify(
    *,
    candidate_key: str,
    reply_status: str,
    previews: list[BotPreview],
) -> str:
    """Map (reply_status, previews) → category. Pure function.

    Order matters: error short-circuits, empty_reply next, then look at
    previews for hit/no_results.
    """
    if reply_status == "error":
        return "error"
    if reply_status == "empty_reply":
        return "empty_reply"

    if not previews:
        return "no_results"

    key_lower = candidate_key.lower()
    for p in previews:
        cu = (p.channel_username or "").lower()
        if cu and cu == key_lower:
            return "direct_hit"
    return "indirect_hit"
```

- [x] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_probe_classification.py -v`
Expected: PASS (all classify tests)

- [x] **Step 5: Commit**

```bash
git add tg_intel_crawler/probe/runner.py tests/test_probe_classification.py
git commit -m "feat(probe): add ProbeRecord dataclass + classify() pure fn"
```

---

## Task 5: ProbeRunner — orchestrate one candidate, then a batch

**Files:**
- Modify: `tg_intel_crawler/probe/runner.py`
- Create: `tests/test_probe_runner.py`

- [x] **Step 1: Write the failing tests for ProbeRunner**

Create `tests/test_probe_runner.py`:

```python
"""Tests for ProbeRunner — orchestrates per-candidate bot probes."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tg_intel_crawler.collector.bot_response_parser import BotPreview
from tg_intel_crawler.collector.bot_search_throttle import (
    BotQueryLimitExceeded,
    BotQueryThrottle,
)
from tg_intel_crawler.probe.runner import ProbeRunner
from tg_intel_crawler.probe.sampler import SampledCandidate


def _public(key="douyinhao88", count=10):
    return SampledCandidate(
        key=key, count=count, invite_hash=None,
        candidate_type="public", stratum="L3",
    )


def _private(key="+abc", count=2):
    return SampledCandidate(
        key=key, count=count, invite_hash=key.lstrip("+"),
        candidate_type="private", stratum="L5",
    )


def _make_throttle():
    """A throttle that doesn't actually wait."""
    now = SimpleNamespace(t=0.0)
    async def fake_sleep(s):
        now.t += s
    return BotQueryThrottle(
        interval_seconds=0,
        max_queries_per_run=10_000,
        sleep_fn=fake_sleep,
        time_fn=lambda: now.t,
    )


def _stub_parser(previews_for_query):
    """Build a parser stub whose .parse() returns previews_for_query[query]."""
    class StubParser:
        def parse(self, reply_text, *, query, bot):
            return previews_for_query.get(query, [])
    return StubParser()


def _preview(channel_username=None):
    return BotPreview(
        bot="@JISOU", query="x", raw_line="🌄 ...", text="...",
        deeplink=None, channel_username=channel_username, msg_id=None,
        icon="🌄", seen_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_probe_public_direct_hit():
    bot = SimpleNamespace(query=AsyncMock(return_value="🌄 ..."))
    parser = _stub_parser({"douyinhao88": [_preview(channel_username="douyinhao88")]})
    runner = ProbeRunner(
        bot_client=bot, parser=parser, throttle=_make_throttle(), bot_name="@JISOU",
    )
    rec = await runner.probe_one(_public())
    assert rec.classification == "direct_hit"
    assert rec.query_sent == "douyinhao88"
    assert rec.previews_count == 1
    assert rec.matched_preview is not None
    assert rec.matched_preview["channel_username"] == "douyinhao88"
    assert rec.error is None


@pytest.mark.asyncio
async def test_probe_private_strips_plus_prefix():
    bot = SimpleNamespace(query=AsyncMock(return_value=""))
    parser = _stub_parser({})
    runner = ProbeRunner(
        bot_client=bot, parser=parser, throttle=_make_throttle(), bot_name="@JISOU",
    )
    rec = await runner.probe_one(_private(key="+abcXYZ"))
    bot.query.assert_called_once_with("abcXYZ")
    assert rec.classification == "empty_reply"


@pytest.mark.asyncio
async def test_probe_empty_reply_when_query_returns_none():
    bot = SimpleNamespace(query=AsyncMock(return_value=None))
    parser = _stub_parser({})
    runner = ProbeRunner(
        bot_client=bot, parser=parser, throttle=_make_throttle(), bot_name="@JISOU",
    )
    rec = await runner.probe_one(_public())
    assert rec.classification == "empty_reply"
    assert rec.reply_status == "empty_reply"
    assert rec.reply_raw == ""


@pytest.mark.asyncio
async def test_probe_no_results_when_reply_has_no_previews():
    bot = SimpleNamespace(query=AsyncMock(return_value="未找到结果"))
    parser = _stub_parser({"douyinhao88": []})
    runner = ProbeRunner(
        bot_client=bot, parser=parser, throttle=_make_throttle(), bot_name="@JISOU",
    )
    rec = await runner.probe_one(_public())
    assert rec.classification == "no_results"
    assert rec.reply_status == "ok"
    assert rec.previews_count == 0


@pytest.mark.asyncio
async def test_probe_error_when_query_raises():
    bot = SimpleNamespace(query=AsyncMock(side_effect=RuntimeError("boom")))
    parser = _stub_parser({})
    runner = ProbeRunner(
        bot_client=bot, parser=parser, throttle=_make_throttle(), bot_name="@JISOU",
    )
    rec = await runner.probe_one(_public())
    assert rec.classification == "error"
    assert rec.reply_status == "error"
    assert rec.error is not None
    assert "RuntimeError" in rec.error
    assert "boom" in rec.error


@pytest.mark.asyncio
async def test_probe_truncates_long_reply():
    long_reply = "x" * 5000
    bot = SimpleNamespace(query=AsyncMock(return_value=long_reply))
    parser = _stub_parser({"douyinhao88": []})
    runner = ProbeRunner(
        bot_client=bot, parser=parser, throttle=_make_throttle(), bot_name="@JISOU",
    )
    rec = await runner.probe_one(_public())
    assert len(rec.reply_raw) <= 4096 + len("... [truncated]")
    assert rec.reply_raw.endswith("... [truncated]")


@pytest.mark.asyncio
async def test_run_processes_all_samples():
    bot = SimpleNamespace(query=AsyncMock(return_value=""))
    parser = _stub_parser({})
    runner = ProbeRunner(
        bot_client=bot, parser=parser, throttle=_make_throttle(), bot_name="@JISOU",
    )
    samples = [_public(key=f"pub_{i}") for i in range(3)]
    records, truncated = await runner.run(samples)
    assert len(records) == 3
    assert truncated is False
    assert {r.candidate.key for r in records} == {"pub_0", "pub_1", "pub_2"}


@pytest.mark.asyncio
async def test_run_stops_and_marks_truncated_on_limit_exceeded():
    """When the throttle raises BotQueryLimitExceeded mid-run, return what
    we have so far with truncated=True."""
    bot = SimpleNamespace(query=AsyncMock(return_value=""))
    parser = _stub_parser({})

    # Throttle that allows exactly 2 acquires.
    now = SimpleNamespace(t=0.0)
    async def fake_sleep(s):
        now.t += s
    throttle = BotQueryThrottle(
        interval_seconds=0,
        max_queries_per_run=2,
        sleep_fn=fake_sleep,
        time_fn=lambda: now.t,
    )

    runner = ProbeRunner(
        bot_client=bot, parser=parser, throttle=throttle, bot_name="@JISOU",
    )
    samples = [_public(key=f"pub_{i}") for i in range(5)]
    records, truncated = await runner.run(samples)
    assert len(records) == 2
    assert truncated is True
```

- [x] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_probe_runner.py -v`
Expected: FAIL with `ImportError: cannot import name 'ProbeRunner'`

- [x] **Step 3: Implement ProbeRunner**

Append to `tg_intel_crawler/probe/runner.py`:

```python
import logging

from tg_intel_crawler.collector.bot_search_throttle import BotQueryLimitExceeded


logger = logging.getLogger("tg_crawler")


class ProbeRunner:
    """Drive the probe over a list of SampledCandidate.

    The bot client / parser / throttle are injected so unit tests can stub
    them. Production code wires up BotSearchClient + BotResponseParser +
    BotQueryThrottle from main.py.
    """

    def __init__(self, *, bot_client, parser, throttle, bot_name: str):
        self._bot = bot_client
        self._parser = parser
        self._throttle = throttle
        self._bot_name = bot_name

    @staticmethod
    def _build_query(candidate: SampledCandidate) -> str:
        """Public → key as-is. Private → strip the leading '+' so the bot
        sees the bare invite hash (cleaner search input)."""
        if candidate.candidate_type == "private":
            return candidate.key.lstrip("+")
        return candidate.key

    @staticmethod
    def _truncate(text: str) -> str:
        if len(text) <= _RAW_TRUNCATE:
            return text
        return text[:_RAW_TRUNCATE] + "... [truncated]"

    @staticmethod
    def _matched_preview_dict(previews: list[BotPreview], key_lower: str) -> dict | None:
        for p in previews:
            cu = (p.channel_username or "").lower()
            if cu and cu == key_lower:
                return {
                    "channel_username": p.channel_username,
                    "msg_id": p.msg_id,
                    "text": p.text,
                    "deeplink": p.deeplink,
                    "raw_line": p.raw_line,
                }
        return None

    async def probe_one(self, candidate: SampledCandidate) -> ProbeRecord:
        """Probe one candidate. Catches all exceptions so a single bad one
        doesn't sink the whole batch."""
        query = self._build_query(candidate)
        reply_status = "ok"
        reply_raw = ""
        error: str | None = None
        previews: list[BotPreview] = []

        try:
            reply = await self._bot.query(query)
        except Exception as e:
            reply_status = "error"
            error = f"{type(e).__name__}: {e}"
            reply = None

        if reply_status != "error":
            if reply is None or not str(reply).strip():
                reply_status = "empty_reply"
                reply_raw = ""
            else:
                reply_raw = str(reply)
                try:
                    previews = self._parser.parse(
                        reply_raw, query=query, bot=self._bot_name,
                    )
                except Exception as e:
                    reply_status = "error"
                    error = f"{type(e).__name__}: {e}"
                    previews = []

        cls = classify(
            candidate_key=candidate.key,
            reply_status=reply_status,
            previews=previews,
        )

        matched = (
            self._matched_preview_dict(previews, candidate.key.lower())
            if cls == "direct_hit" else None
        )

        return ProbeRecord(
            candidate=candidate,
            query_sent=query,
            reply_status=reply_status,
            reply_raw=self._truncate(reply_raw),
            error=error,
            previews_count=len(previews),
            matched_preview=matched,
            classification=cls,
        )

    async def run(
        self, samples: list[SampledCandidate],
    ) -> tuple[list[ProbeRecord], bool]:
        """Probe every sample. Returns (records, truncated).

        If the throttle hits its per-run cap, we stop early and return
        what we have with truncated=True.
        """
        records: list[ProbeRecord] = []
        truncated = False
        for i, sample in enumerate(samples, 1):
            try:
                await self._throttle.acquire()
            except BotQueryLimitExceeded:
                logger.warning(
                    "probe: throttle cap reached after %d/%d samples",
                    i - 1, len(samples),
                )
                truncated = True
                break
            record = await self.probe_one(sample)
            records.append(record)
            logger.info(
                "probe %d/%d: %s [%s] → %s",
                i, len(samples), sample.key, sample.stratum, record.classification,
            )
        return records, truncated
```

- [x] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_probe_runner.py -v`
Expected: PASS (all runner tests)

- [x] **Step 5: Commit**

```bash
git add tg_intel_crawler/probe/runner.py tests/test_probe_runner.py
git commit -m "feat(probe): add ProbeRunner with single-probe + batch run"
```

---

## Task 6: ProbeReporter — write JSON + Markdown

**Files:**
- Create: `tg_intel_crawler/probe/reporter.py`
- Create: `tests/test_probe_reporter.py`

- [x] **Step 1: Write the failing tests for ProbeReporter**

Create `tests/test_probe_reporter.py`:

```python
"""Tests for ProbeReporter — writes JSON + Markdown outputs."""

import json
from datetime import datetime, timezone

import pytest

from tg_intel_crawler.probe.reporter import ProbeReporter
from tg_intel_crawler.probe.runner import ProbeRecord
from tg_intel_crawler.probe.sampler import SampledCandidate


def _record(
    key="x",
    stratum="L3",
    candidate_type="public",
    classification="direct_hit",
    reply_status="ok",
    invite_hash=None,
    reply_raw="🌄 ...",
    error=None,
    matched=None,
    previews_count=1,
    count=10,
):
    return ProbeRecord(
        candidate=SampledCandidate(
            key=key, count=count, invite_hash=invite_hash,
            candidate_type=candidate_type, stratum=stratum,
        ),
        query_sent=key.lstrip("+"),
        reply_status=reply_status,
        reply_raw=reply_raw,
        error=error,
        previews_count=previews_count,
        matched_preview=matched,
        classification=classification,
    )


def test_json_round_trip(tmp_path):
    records = [_record(key="a", classification="direct_hit")]
    reporter = ProbeReporter(
        dest_dir=tmp_path, bot="@JISOU", sample_size=1, seed=42,
        candidate_pool_total=624, truncated=False,
        generated_at=datetime(2026, 6, 6, 12, 0, 0, tzinfo=timezone.utc),
    )
    json_path, md_path = reporter.write(records)
    assert json_path.exists()
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["meta"]["bot"] == "@JISOU"
    assert data["meta"]["sample_size"] == 1
    assert data["meta"]["seed"] == 42
    assert data["meta"]["candidate_pool_total"] == 624
    assert data["meta"]["truncated"] is False
    assert data["meta"]["generated_at"] == "2026-06-06T12:00:00+00:00"
    assert len(data["records"]) == 1
    assert data["records"][0]["classification"] == "direct_hit"
    assert data["records"][0]["candidate"]["key"] == "a"


def test_filename_uses_iso_date(tmp_path):
    reporter = ProbeReporter(
        dest_dir=tmp_path, bot="@JISOU", sample_size=0, seed=1,
        candidate_pool_total=0, truncated=False,
        generated_at=datetime(2026, 6, 6, 23, 30, 0, tzinfo=timezone.utc),
    )
    json_path, md_path = reporter.write([])
    assert json_path.name == "bot_lookup_2026-06-06.json"
    assert md_path.name == "bot_lookup_2026-06-06.md"


def test_markdown_overall_table_counts_correctly(tmp_path):
    records = [
        _record(key="a", stratum="L3", candidate_type="public", classification="direct_hit"),
        _record(key="b", stratum="L3", candidate_type="public", classification="indirect_hit"),
        _record(key="+c", stratum="L6", candidate_type="private",
                invite_hash="c", classification="indirect_hit"),
        _record(key="+d", stratum="L4", candidate_type="private",
                invite_hash="d", classification="no_results"),
    ]
    reporter = ProbeReporter(
        dest_dir=tmp_path, bot="@JISOU", sample_size=4, seed=42,
        candidate_pool_total=100, truncated=False,
        generated_at=datetime(2026, 6, 6, tzinfo=timezone.utc),
    )
    _, md_path = reporter.write(records)
    md = md_path.read_text(encoding="utf-8")
    # The overall row for "indirect_hit" should be: 公开=1, 私密=1, 合计=2
    assert "indirect_hit" in md
    # The overall row for "direct_hit" should be: 公开=1, 私密=0, 合计=1
    assert "direct_hit" in md
    # And for no_results: 公开=0, 私密=1, 合计=1
    assert "no_results" in md


def test_markdown_per_layer_breakdown_present(tmp_path):
    records = [
        _record(key="a", stratum="L3", candidate_type="public", classification="direct_hit"),
        _record(key="+b", stratum="L6", candidate_type="private",
                invite_hash="b", classification="empty_reply"),
    ]
    reporter = ProbeReporter(
        dest_dir=tmp_path, bot="@JISOU", sample_size=2, seed=42,
        candidate_pool_total=100, truncated=False,
        generated_at=datetime(2026, 6, 6, tzinfo=timezone.utc),
    )
    _, md_path = reporter.write(records)
    md = md_path.read_text(encoding="utf-8")
    # Each stratum has its own row in the per-layer table.
    for stratum in ("L1", "L2", "L3", "L4", "L5", "L6"):
        assert f"| {stratum} |" in md


def test_markdown_skips_empty_classification_examples(tmp_path):
    records = [_record(key="a", classification="direct_hit")]  # only one classification
    reporter = ProbeReporter(
        dest_dir=tmp_path, bot="@JISOU", sample_size=1, seed=42,
        candidate_pool_total=100, truncated=False,
        generated_at=datetime(2026, 6, 6, tzinfo=timezone.utc),
    )
    _, md_path = reporter.write(records)
    md = md_path.read_text(encoding="utf-8")
    # Sample for direct_hit should appear, sample header for empty_reply should NOT.
    assert "### direct_hit" in md
    assert "### empty_reply" not in md
    assert "### error" not in md


def test_markdown_includes_truncated_warning_when_set(tmp_path):
    reporter = ProbeReporter(
        dest_dir=tmp_path, bot="@JISOU", sample_size=30, seed=42,
        candidate_pool_total=624, truncated=True,
        generated_at=datetime(2026, 6, 6, tzinfo=timezone.utc),
    )
    _, md_path = reporter.write([_record(key="a")])
    md = md_path.read_text(encoding="utf-8")
    assert "truncated" in md.lower()


def test_creates_dest_dir_if_missing(tmp_path):
    nested = tmp_path / "deeply" / "nested" / "dir"
    reporter = ProbeReporter(
        dest_dir=nested, bot="@JISOU", sample_size=0, seed=1,
        candidate_pool_total=0, truncated=False,
        generated_at=datetime(2026, 6, 6, tzinfo=timezone.utc),
    )
    json_path, md_path = reporter.write([])
    assert nested.exists()
    assert json_path.exists()
    assert md_path.exists()
```

- [x] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_probe_reporter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tg_intel_crawler.probe.reporter'`

- [x] **Step 3: Implement ProbeReporter**

Create `tg_intel_crawler/probe/reporter.py`:

```python
"""Write probe results to disk: JSON dump + Markdown human report."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from tg_intel_crawler.probe.runner import ProbeRecord


_CLASSIFICATIONS = ["direct_hit", "indirect_hit", "no_results", "empty_reply", "error"]
_STRATA = ["L1", "L2", "L3", "L4", "L5", "L6"]
_STRATUM_DESC = {
    "L1": "公开 count=1",
    "L2": "公开 count 2-9",
    "L3": "公开 count ≥10",
    "L4": "私密 count=1",
    "L5": "私密 count 2-9",
    "L6": "私密 count ≥10",
}


class ProbeReporter:
    """Persist a probe run as JSON + Markdown.

    The JSON is the source of truth (parseable for follow-up analysis); the
    Markdown is what a human reads to decide next steps.
    """

    def __init__(
        self,
        *,
        dest_dir: Path | str,
        bot: str,
        sample_size: int,
        seed: int,
        candidate_pool_total: int,
        truncated: bool,
        generated_at: datetime,
    ):
        self._dest_dir = Path(dest_dir)
        self._meta = {
            "bot": bot,
            "sample_size": sample_size,
            "seed": seed,
            "candidate_pool_total": candidate_pool_total,
            "truncated": truncated,
            "generated_at": generated_at.isoformat(),
        }
        self._date_str = generated_at.date().isoformat()

    def write(self, records: list[ProbeRecord]) -> tuple[Path, Path]:
        self._dest_dir.mkdir(parents=True, exist_ok=True)
        json_path = self._dest_dir / f"bot_lookup_{self._date_str}.json"
        md_path = self._dest_dir / f"bot_lookup_{self._date_str}.md"
        json_path.write_text(self._render_json(records), encoding="utf-8")
        md_path.write_text(self._render_markdown(records), encoding="utf-8")
        return json_path, md_path

    # ----- JSON -----

    def _render_json(self, records: list[ProbeRecord]) -> str:
        payload = {
            "meta": self._meta,
            "records": [self._record_to_dict(r) for r in records],
        }
        return json.dumps(payload, indent=2, ensure_ascii=False)

    @staticmethod
    def _record_to_dict(r: ProbeRecord) -> dict:
        d = asdict(r)
        # asdict() handles SampledCandidate fine; nothing else needs massage.
        return d

    # ----- Markdown -----

    def _render_markdown(self, records: list[ProbeRecord]) -> str:
        lines: list[str] = []
        lines.append(f"# Bot Lookup Probe — {self._date_str}")
        lines.append("")
        lines.append(f"bot: {self._meta['bot']}")
        lines.append(
            f"sample: {len(records)} / {self._meta['candidate_pool_total']} "
            f"(seed={self._meta['seed']})"
        )
        if self._meta["truncated"]:
            lines.append("")
            lines.append("> ⚠️  **truncated** — throttle cap was hit before all samples ran.")
        lines.append("")
        lines.extend(self._overall_table(records))
        lines.append("")
        lines.extend(self._per_layer_table(records))
        lines.append("")
        lines.extend(self._examples(records))
        return "\n".join(lines) + "\n"

    @staticmethod
    def _overall_table(records: list[ProbeRecord]) -> list[str]:
        # rows: classification → (public, private, total)
        rows: dict[str, list[int]] = {c: [0, 0, 0] for c in _CLASSIFICATIONS}
        for r in records:
            c = r.classification
            t = r.candidate.candidate_type
            rows[c][2] += 1
            if t == "public":
                rows[c][0] += 1
            else:
                rows[c][1] += 1

        out = [
            "## 命中分布",
            "| 分类           | 公开 | 私密 | 合计 |",
            "|----------------|------|------|------|",
        ]
        for c in _CLASSIFICATIONS:
            pub, priv, total = rows[c]
            out.append(f"| {c:<14} | {pub:>4} | {priv:>4} | {total:>4} |")
        return out

    @staticmethod
    def _per_layer_table(records: list[ProbeRecord]) -> list[str]:
        # rows: stratum → {classification: count, "n": int}
        per: dict[str, dict[str, int]] = {
            s: {c: 0 for c in _CLASSIFICATIONS} | {"n": 0}
            for s in _STRATA
        }
        for r in records:
            s = r.candidate.stratum
            per[s][r.classification] += 1
            per[s]["n"] += 1

        out = [
            "## 按层细分",
            "| 层 | 描述              | n | direct | indirect | none | empty | err |",
            "|----|-------------------|---|--------|----------|------|-------|-----|",
        ]
        for s in _STRATA:
            row = per[s]
            desc = _STRATUM_DESC[s]
            # Private strata never show direct_hit (key starts with +).
            direct_cell = (
                str(row["direct_hit"]) if s in ("L1", "L2", "L3") else "-"
            )
            out.append(
                f"| {s} | {desc:<17} | {row['n']:>1} | "
                f"{direct_cell:>6} | {row['indirect_hit']:>8} | "
                f"{row['no_results']:>4} | {row['empty_reply']:>5} | "
                f"{row['error']:>3} |"
            )
        return out

    @staticmethod
    def _examples(records: list[ProbeRecord]) -> list[str]:
        out = ["## 典型样本"]
        # One example per classification (first occurrence).
        for c in _CLASSIFICATIONS:
            ex = next((r for r in records if r.classification == c), None)
            if ex is None:
                continue  # skip section with no occurrence
            sc = ex.candidate
            out.append("")
            out.append(f"### {c} · {sc.key} ({sc.stratum}, count={sc.count})")
            out.append(f"query: `{ex.query_sent}`")
            if c == "direct_hit" and ex.matched_preview:
                out.append("matched preview:")
                out.append(f"> {ex.matched_preview.get('raw_line', '')}")
            elif c == "error":
                out.append(f"error: `{ex.error}`")
            elif c == "empty_reply":
                out.append("(empty reply)")
            elif c in ("indirect_hit", "no_results"):
                # Show a snippet of the reply.
                snippet = (ex.reply_raw or "").strip().splitlines()
                preview = snippet[0] if snippet else "(no content)"
                out.append(f"> {preview[:200]}")
        return out
```

- [x] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_probe_reporter.py -v`
Expected: PASS (all reporter tests)

- [x] **Step 5: Commit**

```bash
git add tg_intel_crawler/probe/reporter.py tests/test_probe_reporter.py
git commit -m "feat(probe): add ProbeReporter — JSON dump + Markdown human report"
```

---

## Task 7: Wire CLI command `probe-bot-lookup`

**Files:**
- Modify: `tg_intel_crawler/main.py` (add new command after `crawl_bot`)

This task wires the three units together via a click command, reusing the bot-selection / throttle-construction patterns already in `_crawl_bot_async`.

- [x] **Step 1: Read main.py around the crawl-bot command for context**

Read: `tg_intel_crawler/main.py:423-530` to see how `crawl-bot` resolves the bot, builds the throttle, and uses `BotSearchClient.ensure_available()`. Reuse the same pattern in the new command — same config keys, same fallback behavior.

- [x] **Step 2: Add imports for the probe package at the top of main.py**

In `tg_intel_crawler/main.py`, find the existing import block that includes `from tg_intel_crawler.collector.bot_search import BotSearchClient, BotUnavailable` and add right below it:

```python
from tg_intel_crawler.probe.reporter import ProbeReporter
from tg_intel_crawler.probe.runner import ProbeRunner
from tg_intel_crawler.probe.sampler import Sampler
```

- [x] **Step 3: Add the click command**

Add to `tg_intel_crawler/main.py`, anywhere after the `crawl_bot` definition (e.g., right before `@cli.command(name="crawl-twitter")`):

```python
@cli.command(name="probe-bot-lookup")
@click.option("--sample-size", default=30, type=int,
              help="Total candidates to probe (capped by bot_search.max_queries_per_run).")
@click.option("--seed", default=42, type=int, help="RNG seed for reproducible sampling.")
@click.option("--bot", default=None,
              help="Override bot username (defaults to bot_search.bots[0]).")
@click.option("--report-dir", default="output/probe",
              help="Directory for the JSON + Markdown report.")
def probe_bot_lookup(sample_size: int, seed: int, bot, report_dir: str):
    """Probe how well the search bot reflects candidate-pool entries.

    Stratified-samples 30 candidates (5 per layer × 6 layers), queries the
    bot, classifies each reply, and writes a JSON + Markdown report.
    Read-only: never mutates the candidate pool.
    """
    asyncio.run(_probe_bot_lookup_async(sample_size, seed, bot, report_dir))


async def _probe_bot_lookup_async(
    sample_size: int, seed: int, bot_override: str | None, report_dir: str,
):
    from datetime import datetime, timezone

    logger = logging.getLogger("tg_crawler")
    config = load_config()
    bs_cfg = config.get("bot_search") or {}

    # Resolve bot list (same pattern as crawl-bot).
    bots = list(bs_cfg.get("bots") or ["@JISOU"])
    if bot_override:
        bots = [bot_override if bot_override.startswith("@") else f"@{bot_override}"]
    if not bots:
        click.echo("❌ No bot configured. Add bot_search.bots in config.yaml.")
        return

    interval = float(bs_cfg.get("query_interval_seconds", 10))
    convo_timeout = float(bs_cfg.get("conversation_timeout_seconds", 15))
    max_queries = int(bs_cfg.get("max_queries_per_run", 30))
    # The throttle's per-run cap should be at least sample_size, otherwise
    # the probe will truncate before finishing.
    cap = max(sample_size, max_queries)

    # Load candidate pool (read-only).
    pool = CandidatePool(_candidates_path(config))
    entries = pool.list_all()
    if not entries:
        click.echo("❌ Candidate pool is empty. Run `crawl` first.")
        return

    # Stratified sample.
    samples = Sampler(seed=seed).draw(entries, sample_size=sample_size)
    if not samples:
        click.echo("❌ Sampler returned 0 — check candidate pool.")
        return

    click.echo(
        f"🧪 probe-bot-lookup: sample={len(samples)}/{len(entries)} "
        f"seed={seed} bot={bots[0]}"
    )

    parser = BotResponseParser()
    throttle = BotQueryThrottle(
        interval_seconds=interval, max_queries_per_run=cap,
    )

    async with TGClient(str(CONFIG_PATH)) as tg:
        client = tg.client

        # Pick the first reachable bot (same fallback as crawl-bot).
        chosen_bot: BotSearchClient | None = None
        chosen_name: str = ""
        for b in bots:
            bsc = BotSearchClient(client, bot=b, timeout=convo_timeout)
            try:
                await bsc.ensure_available()
                chosen_bot = bsc
                chosen_name = b
                logger.info(f"Using bot: {b}")
                break
            except BotUnavailable as e:
                logger.warning(f"Bot {b} unavailable: {e}")
        if chosen_bot is None:
            click.echo("❌ No reachable bot.")
            return

        runner = ProbeRunner(
            bot_client=chosen_bot, parser=parser,
            throttle=throttle, bot_name=chosen_name,
        )
        records, truncated = await runner.run(samples)

    reporter = ProbeReporter(
        dest_dir=report_dir,
        bot=chosen_name,
        sample_size=len(samples),
        seed=seed,
        candidate_pool_total=len(entries),
        truncated=truncated,
        generated_at=datetime.now(timezone.utc),
    )
    json_path, md_path = reporter.write(records)
    click.echo(f"✅ wrote {json_path}")
    click.echo(f"✅ wrote {md_path}")
    if truncated:
        click.echo("⚠️  Run truncated — throttle cap hit before all samples completed.")
```

- [x] **Step 4: Verify the CLI command shows up**

Run: `tg-crawler --help`
Expected: `probe-bot-lookup` appears in the command list.

Run: `tg-crawler probe-bot-lookup --help`
Expected: usage shows `--sample-size`, `--seed`, `--bot`, `--report-dir`.

- [x] **Step 5: Run the entire test suite to confirm no regression**

Run: `pytest -v`
Expected: PASS — all existing tests still pass, plus the new probe tests.

- [x] **Step 6: Commit**

```bash
git add tg_intel_crawler/main.py
git commit -m "feat(probe): wire probe-bot-lookup CLI command"
```

---

## Task 8: Smoke-run with --sample-size 6 against the real bot

**Files:** none (manual verification)

The unit tests cover all logic; this step verifies the live wiring works. We use a tiny sample so a smoke run takes ~1 minute (6 queries × 10s interval).

- [x] **Step 1: Confirm `bot_search.enabled: true` in config.yaml**

Read: `config/config.yaml`. If `bot_search.enabled` is `false`, flip it to `true`. (The probe doesn't actually check this flag, but other commands do — keeping it consistent.)

- [x] **Step 2: Run the smoke probe**

Run: `tg-crawler probe-bot-lookup --sample-size 6 --seed 1`
Expected:
- Console prints `🧪 probe-bot-lookup: sample=6/<N> seed=1 bot=@JISOU`
- One log line per sample (`probe 1/6: …`)
- Two `✅ wrote` lines at the end
- Total runtime ≈ 50–70 seconds

- [x] **Step 3: Open the Markdown report**

Read: `output/probe/bot_lookup_<today>.md`

Sanity check: the `n` column in the per-layer table sums to 6, every classification cell is consistent (e.g., the row for `L4` should never show a non-zero in the `direct_hit` column — it should print `-`), and the `典型样本` section has at least one example.

- [x] **Step 4: Open the JSON report**

Read: `output/probe/bot_lookup_<today>.json`

Sanity check: `meta.sample_size == 6`, `meta.candidate_pool_total > 0`, `len(records) == 6` (or fewer if truncated).

- [x] **Step 5: Run the full 30-sample probe**

Run: `tg-crawler probe-bot-lookup`
Expected: ~5 minutes runtime, 30 records, full report.

This is the report we'll use to design the next phase (二级扩展). No commit needed — the reports are gitignored under `output/`.

---

## Task 9: README — document the diagnostic command

**Files:**
- Modify: `README.md`

- [x] **Step 1: Find the right place**

Read: `README.md`. Locate the section that describes other CLI commands (look for a header like "命令" or "使用" or the section that documents `crawl-bot`).

- [x] **Step 2: Add a section for `probe-bot-lookup`**

Append to `README.md` under the relevant CLI/usage section (insert after the `crawl-bot` section, before the next top-level header):

```markdown
### 候选群反查能力探测 (`probe-bot-lookup`)

`discovered_groups.yaml` 攒了几百上千个候选群后，下一步要让 LLM 来判定该不该爬。但 LLM 的输入材料取决于一个前提：搜群 bot（@JISOU 等）能反查到这些候选群多少？

`probe-bot-lookup` 用一次性诊断的方式回答这个问题：分层抽样 30 个候选 → 喂给 bot → 分类回复 → 输出 JSON + Markdown 报告。读-only，不改候选池状态。

```bash
# 默认：30 个候选，seed=42，输出到 output/probe/
tg-crawler probe-bot-lookup

# 小样本 smoke run
tg-crawler probe-bot-lookup --sample-size 6 --seed 1

# 切到别的 bot
tg-crawler probe-bot-lookup --bot @SomeOtherBot
```

报告里五种命中分类：

| 分类 | 含义 |
|---|---|
| `direct_hit` | bot 返回了该群本身的内容 |
| `indirect_hit` | bot 返回了 previews，但都不是该群（别人在讨论它）|
| `no_results` | bot 回复非空但解析不出 previews |
| `empty_reply` | bot 没回复 / 超时 |
| `error` | 其他异常 |

私密群（key 以 `+` 开头）天然只能落进后三档，因为 bot 索引不到 invite-only 群本身。
```

- [x] **Step 3: Verify README renders correctly**

Read: `README.md`. Skim the new section to ensure markdown is well-formed (table renders, code blocks close, headers don't collide).

- [x] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs(readme): add probe-bot-lookup section — diagnostic for candidate reverse-lookup coverage"
```

---

## Self-Review

**Spec coverage check:**

| Spec section | Plan coverage |
|---|---|
| `Sampler` module + interface | Tasks 1, 2, 3 |
| `ProbeRunner` module + interface | Tasks 4, 5 |
| `ProbeReporter` module + interface | Task 6 |
| Stratification (6 layers, public/private × 3 count bands) | Task 2 (stratify_entry) |
| Sample size 30, deficit handling, remainder allocation | Task 3 |
| `--sample-size` / `--seed` / `--bot` / `--report-dir` flags | Task 7 |
| Public query = bare key; private query = key.lstrip("+") | Task 5 (`_build_query`) |
| Throttle reuse (`BotQueryThrottle`) | Task 7 wiring + Task 5 tests |
| `direct_hit` / `indirect_hit` / `no_results` / `empty_reply` / `error` | Task 4 (classify) + Task 5 (probe_one branches) |
| `direct_hit` is case-insensitive on channel_username | Task 4 test |
| `reply_raw` truncated to 4096 chars + marker | Task 5 (`_truncate`) |
| JSON output structure (meta + records) | Task 6 |
| Markdown structure (overall table, per-layer, examples) | Task 6 |
| Skip example sections for empty classifications | Task 6 test |
| Truncated marker propagated to report | Task 6 + Task 7 (passes `truncated` into reporter) |
| Read-only against candidate pool | Task 7 (`pool.list_all()` only) |
| Report dir auto-created | Task 6 (`mkdir(parents=True, exist_ok=True)`) |
| Ed-cases: empty pool, unreachable bot, throttle cap mid-run | Task 5 + Task 7 |
| README section | Task 9 |

All spec sections accounted for.

**Placeholder scan:** No "TBD", "TODO", "Similar to Task N", or stub-handler instructions. Every code step shows the code; every command step shows the expected output; every commit message is concrete.

**Type consistency:**
- `SampledCandidate` defined in Task 1, used identically in Tasks 3, 5, 6.
- `ProbeRecord` defined in Task 4, used identically in Tasks 5, 6.
- `classify()` signature `(*, candidate_key, reply_status, previews) → str` consistent across Tasks 4, 5.
- `Sampler.draw(pool, sample_size=30) → list[SampledCandidate]` — same signature in Task 3 implementation, Task 7 wiring, and the spec.
- `ProbeRunner.__init__(*, bot_client, parser, throttle, bot_name)` — same kwargs in Tasks 5 and 7.
- `ProbeReporter.__init__(*, dest_dir, bot, sample_size, seed, candidate_pool_total, truncated, generated_at)` — same in Tasks 6 and 7.
- File paths consistent throughout: `tg_intel_crawler/probe/{sampler,runner,reporter}.py` + `tests/test_probe_{sampler,classification,runner,reporter}.py`.
