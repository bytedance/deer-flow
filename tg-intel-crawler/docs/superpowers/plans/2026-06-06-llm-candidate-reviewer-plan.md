# LLM 候选群组自动审查实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 加一条 `tg-crawler candidates llm-review` 命令，让 LLM 用两阶段方式审查 `discovered_groups.yaml` 里的 pending 候选群，给出置信度 verdict，可选地把高置信度候选写入 `config.groups` 并触发限流加群。

**Architecture:** 两阶段判决。Stage 1 仅 metadata + 来源群信誉粗筛（批量 / 便宜 token）。Stage 2 加来源消息原文细判（单条 / 贵 token）。判决落到 candidate yaml 的 `llm_verdict` 字段；status 修改和 join 行为各由独立 flag 控制；LLM 永远不写 `status: rejected`。

**Tech Stack:** Python 3.11 / pytest + pytest-asyncio / openai (AsyncOpenAI 兼容协议) / pyyaml / click。复用现有 `JoinThrottle` / `LLMFilter` 客户端配置。

**Spec:** `docs/superpowers/specs/2026-06-06-llm-candidate-reviewer-design.md`

---

## File Structure

### 新建

| 文件 | 职责 |
|---|---|
| `tg_intel_crawler/storage/raw_lookup.py` | `RawMessageLookup` —— 启动时建索引、按 `(group_name, msg_id)` 反查 `output/raw/*.json` 里的消息原文 |
| `tg_intel_crawler/storage/intel_stats.py` | `IntelStatsAggregator` —— 扫 `output/filtered/intel_*.json`，按 `source_group` 聚合 high/medium intel 计数 |
| `tg_intel_crawler/filter/candidate_reviewer.py` | `CandidateReviewer` —— 编排 Stage1/Stage2 LLM 调用、降级规则、verdict 生成 |
| `tests/test_raw_lookup.py` | 反查索引的命中 / 缺失 / 多日期文件路径 |
| `tests/test_intel_stats.py` | 聚合器：缺失目录、多日期合并、字段缺失保护 |
| `tests/test_candidate_reviewer.py` | 两阶段编排 + 降级规则 + 错误处理（mock LLM） |
| `tests/test_main_llm_review.py` | CLI 子命令端到端（mock LLM + 临时 yaml） |

### 修改

| 文件 | 变更 |
|---|---|
| `tg_intel_crawler/collector/candidate_pool.py` | 新增 `pending_for_review`、`set_llm_verdict`、`apply_llm_approvals` 方法；`_VALID_STATUSES` 不变 |
| `tg_intel_crawler/main.py` | 新增 `candidates llm-review` 子命令；在 `candidates list` 上加 `--llm-verdict` 过滤 |
| `tests/test_candidate_pool.py` | 给新方法加测试用例 |
| `README.md` | 加 "LLM 自动审查" 章节，给典型命令序列 |

---

## Task 1: `RawMessageLookup` —— 按 (group_name, msg_id) 反查原文

**Files:**
- Create: `tg_intel_crawler/storage/raw_lookup.py`
- Test: `tests/test_raw_lookup.py`

按 spec §3 / §5.2，Stage 2 需要从 `output/raw/<date>_<group_name>.json` 里反查消息原文。raw 文件按"日期+群名"切分，一个候选可能在多个日期文件里被引用，因此索引建一次后所有反查都要快。

- [x] **Step 1: Write failing test for empty / missing dir**

```python
# tests/test_raw_lookup.py
from pathlib import Path

import pytest

from tg_intel_crawler.storage.raw_lookup import RawMessageLookup


def test_missing_dir_returns_empty_lookup(tmp_path):
    """Missing raw/ dir is not an error — every lookup just misses."""
    lookup = RawMessageLookup(str(tmp_path / "does_not_exist"))
    assert lookup.get("any_group", 123) is None
    assert lookup.size() == 0


def test_empty_dir_returns_empty_lookup(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    lookup = RawMessageLookup(str(raw_dir))
    assert lookup.get("any_group", 123) is None
```

- [x] **Step 2: Run tests to confirm failure**

```bash
cd /Users/sunnymei/project/original-黑灰产情报分析Agent/tg-intel-crawler
pytest tests/test_raw_lookup.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'tg_intel_crawler.storage.raw_lookup'`

- [x] **Step 3: Write minimal `RawMessageLookup` for empty case**

```python
# tg_intel_crawler/storage/raw_lookup.py
"""Index of raw Telegram messages keyed by (group_name, msg_id).

Built once at startup by scanning output/raw/<date>_<group>.json files.
Returns None for missing keys — callers must handle the miss path.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger("tg_crawler")


class RawMessageLookup:
    """In-memory index of raw messages, keyed by (group_name, msg_id) -> text."""

    def __init__(self, raw_dir: str | Path):
        self._raw_dir = Path(raw_dir)
        self._index: dict[tuple[str, int], str] = {}
        if self._raw_dir.exists():
            self._build_index()

    def _build_index(self) -> None:
        for path in self._raw_dir.glob("*.json"):
            try:
                records = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("raw_lookup: skip %s: %s", path, e)
                continue
            if not isinstance(records, list):
                continue
            for rec in records:
                if not isinstance(rec, dict):
                    continue
                msg_id = rec.get("msg_id")
                group_name = rec.get("group_name")
                text = rec.get("text") or ""
                if msg_id is None or not group_name:
                    continue
                self._index[(group_name, int(msg_id))] = text

    def get(self, group_name: str, msg_id: int) -> str | None:
        return self._index.get((group_name, int(msg_id)))

    def size(self) -> int:
        return len(self._index)
```

- [x] **Step 4: Run tests to confirm pass**

```bash
pytest tests/test_raw_lookup.py -v
```
Expected: PASS (2/2)

- [x] **Step 5: Add tests for the happy path + multi-file merge**

Add to `tests/test_raw_lookup.py`:

```python
import json


def _write_raw(raw_dir, date_str, group_name, records):
    path = raw_dir / f"{date_str}_{group_name}.json"
    path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")


def test_index_finds_message_in_single_file(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    _write_raw(raw_dir, "2026-06-05", "group_a", [
        {"msg_id": 100, "group_name": "group_a", "text": "卖抖音号 联系 @x"},
        {"msg_id": 101, "group_name": "group_a", "text": "今天天气好"},
    ])
    lookup = RawMessageLookup(str(raw_dir))
    assert lookup.size() == 2
    assert lookup.get("group_a", 100) == "卖抖音号 联系 @x"
    assert lookup.get("group_a", 999) is None


def test_index_merges_across_dates(tmp_path):
    """Same group across multiple date files all get indexed."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    _write_raw(raw_dir, "2026-06-05", "g", [
        {"msg_id": 1, "group_name": "g", "text": "t1"},
    ])
    _write_raw(raw_dir, "2026-06-06", "g", [
        {"msg_id": 2, "group_name": "g", "text": "t2"},
    ])
    lookup = RawMessageLookup(str(raw_dir))
    assert lookup.size() == 2
    assert lookup.get("g", 1) == "t1"
    assert lookup.get("g", 2) == "t2"


def test_index_skips_malformed_files(tmp_path):
    """A broken JSON file shouldn't kill the whole index."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "2026-06-05_broken.json").write_text("{not json", encoding="utf-8")
    _write_raw(raw_dir, "2026-06-05", "good", [
        {"msg_id": 1, "group_name": "good", "text": "ok"},
    ])
    lookup = RawMessageLookup(str(raw_dir))
    assert lookup.get("good", 1) == "ok"


def test_index_skips_records_without_required_fields(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    _write_raw(raw_dir, "2026-06-05", "g", [
        {"text": "no msg_id"},
        {"msg_id": 1, "text": "no group"},
        {"msg_id": 2, "group_name": "g", "text": "valid"},
    ])
    lookup = RawMessageLookup(str(raw_dir))
    assert lookup.size() == 1
    assert lookup.get("g", 2) == "valid"
```

- [x] **Step 6: Run tests to confirm pass**

```bash
pytest tests/test_raw_lookup.py -v
```
Expected: PASS (6/6)

- [x] **Step 7: Commit**

```bash
git add tg_intel_crawler/storage/raw_lookup.py tests/test_raw_lookup.py
git commit -m "feat(storage): add RawMessageLookup — (group, msg_id) → text index over output/raw/"
```

---

## Task 2: `IntelStatsAggregator` —— 来源群历史信誉

**Files:**
- Create: `tg_intel_crawler/storage/intel_stats.py`
- Test: `tests/test_intel_stats.py`

按 spec §5.1，Stage 1 输入里的 `source_groups_intel_score` 衍生字段：扫 `output/filtered/intel_*.json`，按 `source_group` 聚合 high/medium/total 计数。这让 LLM 能看出 "传播该候选的群本身是否高价值"。

- [x] **Step 1: Write failing test for missing dir**

```python
# tests/test_intel_stats.py
import json

from tg_intel_crawler.storage.intel_stats import IntelStatsAggregator


def test_missing_dir_returns_empty_scores(tmp_path):
    agg = IntelStatsAggregator(str(tmp_path / "filtered_does_not_exist"))
    assert agg.score_for("any_group") == {"high": 0, "medium": 0, "total_msgs": 0}


def test_empty_dir_returns_empty_scores(tmp_path):
    filt = tmp_path / "filtered"
    filt.mkdir()
    agg = IntelStatsAggregator(str(filt))
    assert agg.score_for("any_group") == {"high": 0, "medium": 0, "total_msgs": 0}
```

- [x] **Step 2: Run tests to confirm failure**

```bash
pytest tests/test_intel_stats.py -v
```
Expected: FAIL with `ModuleNotFoundError`

- [x] **Step 3: Write minimal `IntelStatsAggregator`**

```python
# tg_intel_crawler/storage/intel_stats.py
"""Per-source-group intel reputation, derived from output/filtered/intel_*.json.

Scans every intel_*.json file once at startup and tallies how many high /
medium / total records each ``source_group`` produced. Used by the LLM
candidate reviewer's Stage 1 to weigh signals from already-known black/gray
groups higher than signals from low-value groups.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger("tg_crawler")


class IntelStatsAggregator:
    """Aggregate filtered intel by source_group."""

    def __init__(self, filtered_dir: str | Path):
        self._dir = Path(filtered_dir)
        # group_name -> {"high": int, "medium": int, "total_msgs": int}
        self._scores: dict[str, dict[str, int]] = {}
        if self._dir.exists():
            self._build()

    def _build(self) -> None:
        # Match all intel*.json files (intel_2026-06-05.json,
        # intel_twitter_2026-06-05.json, intel_bot_2026-06-05.json, ...).
        for path in self._dir.glob("intel*.json"):
            try:
                records = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("intel_stats: skip %s: %s", path, e)
                continue
            if not isinstance(records, list):
                continue
            for rec in records:
                if not isinstance(rec, dict):
                    continue
                grp = rec.get("source_group")
                if not grp:
                    continue
                level = (rec.get("risk_level") or "").lower()
                bucket = self._scores.setdefault(
                    grp, {"high": 0, "medium": 0, "total_msgs": 0}
                )
                bucket["total_msgs"] += 1
                if level == "high":
                    bucket["high"] += 1
                elif level == "medium":
                    bucket["medium"] += 1

    def score_for(self, group_name: str) -> dict[str, int]:
        return self._scores.get(
            group_name, {"high": 0, "medium": 0, "total_msgs": 0}
        )

    def all_scores(self) -> dict[str, dict[str, int]]:
        return dict(self._scores)
```

- [x] **Step 4: Run tests to confirm pass**

```bash
pytest tests/test_intel_stats.py -v
```
Expected: PASS (2/2)

- [x] **Step 5: Add aggregation tests**

Append to `tests/test_intel_stats.py`:

```python
def _write_intel(filt, name, records):
    (filt / name).write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")


def test_aggregates_within_one_file(tmp_path):
    filt = tmp_path / "filtered"
    filt.mkdir()
    _write_intel(filt, "intel_2026-06-05.json", [
        {"source_group": "卖号群", "risk_level": "high"},
        {"source_group": "卖号群", "risk_level": "high"},
        {"source_group": "卖号群", "risk_level": "medium"},
        {"source_group": "卖号群", "risk_level": "low"},
        {"source_group": "其他群", "risk_level": "high"},
    ])
    agg = IntelStatsAggregator(str(filt))
    assert agg.score_for("卖号群") == {"high": 2, "medium": 1, "total_msgs": 4}
    assert agg.score_for("其他群") == {"high": 1, "medium": 0, "total_msgs": 1}


def test_aggregates_across_multiple_files(tmp_path):
    """intel_2026-06-05.json + intel_2026-06-06.json + intel_twitter_*.json all merge."""
    filt = tmp_path / "filtered"
    filt.mkdir()
    _write_intel(filt, "intel_2026-06-05.json", [
        {"source_group": "g", "risk_level": "high"},
    ])
    _write_intel(filt, "intel_2026-06-06.json", [
        {"source_group": "g", "risk_level": "medium"},
    ])
    _write_intel(filt, "intel_twitter_2026-06-05.json", [
        {"source_group": "g", "risk_level": "high"},
    ])
    agg = IntelStatsAggregator(str(filt))
    assert agg.score_for("g") == {"high": 2, "medium": 1, "total_msgs": 3}


def test_skips_records_with_missing_source_group(tmp_path):
    filt = tmp_path / "filtered"
    filt.mkdir()
    _write_intel(filt, "intel_2026-06-05.json", [
        {"risk_level": "high"},  # no source_group → skip
        {"source_group": "g", "risk_level": "high"},
    ])
    agg = IntelStatsAggregator(str(filt))
    assert agg.score_for("g") == {"high": 1, "medium": 0, "total_msgs": 1}
```

- [x] **Step 6: Run tests to confirm pass**

```bash
pytest tests/test_intel_stats.py -v
```
Expected: PASS (5/5)

- [x] **Step 7: Commit**

```bash
git add tg_intel_crawler/storage/intel_stats.py tests/test_intel_stats.py
git commit -m "feat(storage): add IntelStatsAggregator — per-source-group reputation from output/filtered/"
```

---

## Task 3: 扩 `CandidatePool` —— `pending_for_review` 选择逻辑

**Files:**
- Modify: `tg_intel_crawler/collector/candidate_pool.py`
- Test: `tests/test_candidate_pool.py`

按 spec §4，新增方法 `pending_for_review(now, count_growth_factor=2.0, stale_days=30, force_rereview=False)` 返回需要 review 的候选。

- [x] **Step 1: Write failing test for never-reviewed pending candidate**

Add to `tests/test_candidate_pool.py`:

```python
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
```

- [x] **Step 2: Run tests to confirm failure**

```bash
pytest tests/test_candidate_pool.py::test_pending_for_review_returns_unreviewed_pending -v
```
Expected: FAIL with `AttributeError: 'CandidatePool' object has no attribute 'pending_for_review'`

- [x] **Step 3: Implement minimal `pending_for_review`**

In `tg_intel_crawler/collector/candidate_pool.py`, add after `approved_links`:

```python
    def pending_for_review(
        self,
        *,
        now: datetime,
        count_growth_factor: float = 2.0,
        stale_days: int = 30,
        force_rereview: bool = False,
    ) -> list[dict]:
        """Return pending candidates that need (or want) an LLM review.

        A candidate is selected if its status is ``pending`` AND any of:
        - never reviewed (no ``llm_verdict`` field), OR
        - ``count > reviewed_count * count_growth_factor`` (heat doubled), OR
        - ``now - reviewed_at > stale_days``, OR
        - ``force_rereview=True``.

        Note: re-review applies to ALL pending candidates including those
        previously stamped ``llm_rejected`` — see spec §4 互斥规则.
        """
        out: list[dict] = []
        stale_threshold = now - timedelta(days=stale_days)
        for key, entry in self._candidates.items():
            if entry.get("status") != "pending":
                continue
            verdict = entry.get("llm_verdict")
            if verdict is None or force_rereview:
                out.append({"key": key, **entry})
                continue

            reviewed_count = int(verdict.get("reviewed_count", 0))
            cur_count = int(entry.get("count", 0))
            if cur_count > reviewed_count * count_growth_factor:
                out.append({"key": key, **entry})
                continue

            reviewed_at_str = verdict.get("reviewed_at") or ""
            try:
                reviewed_at = datetime.fromisoformat(reviewed_at_str)
            except ValueError:
                reviewed_at = None
            if reviewed_at is None or reviewed_at < stale_threshold:
                out.append({"key": key, **entry})
        return out
```

Also add `from datetime import timedelta` at top of file (currently only `datetime` is imported):

```python
from datetime import datetime, timedelta
```

- [x] **Step 4: Run tests to confirm pass**

```bash
pytest tests/test_candidate_pool.py::test_pending_for_review_returns_unreviewed_pending tests/test_candidate_pool.py::test_pending_for_review_skips_approved_and_rejected -v
```
Expected: PASS (2/2)

- [x] **Step 5: Add tests for the increment / staleness / force flags**

```python
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
```

- [x] **Step 6: Run all candidate pool tests**

```bash
pytest tests/test_candidate_pool.py -v
```
Expected: PASS (all existing + 6 new)

- [x] **Step 7: Commit**

```bash
git add tg_intel_crawler/collector/candidate_pool.py tests/test_candidate_pool.py
git commit -m "feat(candidate_pool): add pending_for_review — selects unreviewed/stale/heated candidates"
```

---

## Task 4: 扩 `CandidatePool` —— `set_llm_verdict`

**Files:**
- Modify: `tg_intel_crawler/collector/candidate_pool.py`
- Test: `tests/test_candidate_pool.py`

写入 `llm_verdict` 字段，不动 `status`。

- [x] **Step 1: Write failing test**

```python
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
    pool.set_llm_verdict("does_not_exist", {"verdict": "llm_rejected"})
    pool.flush()
    # Just shouldn't raise.


def test_set_llm_verdict_validates_verdict_field(pool_path):
    """Invalid 'verdict' value must raise ValueError."""
    import pytest
    pool = CandidatePool(str(pool_path))
    with pytest.raises(ValueError):
        pool.set_llm_verdict("k", {"verdict": "bogus"})
```

(The third test references a hypothetical schema check — we'll implement it.)

- [x] **Step 2: Run tests to confirm failure**

```bash
pytest tests/test_candidate_pool.py::test_set_llm_verdict_writes_field_and_does_not_touch_status -v
```
Expected: FAIL with `AttributeError: 'CandidatePool' object has no attribute 'set_llm_verdict'`

- [x] **Step 3: Implement `set_llm_verdict`**

In `tg_intel_crawler/collector/candidate_pool.py`, add a constant near `_VALID_STATUSES`:

```python
_VALID_VERDICTS = (
    "llm_approved_high",
    "llm_approved_medium",
    "llm_approved_low",
    "llm_rejected",
)
```

Add the method:

```python
    def set_llm_verdict(self, key: str, verdict: dict) -> None:
        """Attach an llm_verdict block to a candidate. Does NOT change status.

        Validates ``verdict["verdict"]`` against the closed set in spec §4.
        Unknown keys are silently no-op (so a stale verdict for a deleted
        candidate doesn't crash the run).
        """
        v_name = verdict.get("verdict")
        if v_name not in _VALID_VERDICTS:
            raise ValueError(f"invalid verdict: {v_name!r}")
        entry = self._candidates.get(key)
        if entry is None:
            return
        entry["llm_verdict"] = dict(verdict)
```

- [x] **Step 4: Run tests to confirm pass**

```bash
pytest tests/test_candidate_pool.py -v -k "llm_verdict"
```
Expected: PASS (3/3)

- [x] **Step 5: Commit**

```bash
git add tg_intel_crawler/collector/candidate_pool.py tests/test_candidate_pool.py
git commit -m "feat(candidate_pool): add set_llm_verdict — write verdict block, leave status untouched"
```

---

## Task 5: 扩 `CandidatePool` —— `apply_llm_approvals`

**Files:**
- Modify: `tg_intel_crawler/collector/candidate_pool.py`
- Test: `tests/test_candidate_pool.py`

按 spec §4：仅在 `--write-config` 时调用。把所有 `status=pending` 且 `llm_verdict.verdict ∈ {llm_approved_high, llm_approved_medium}` 的候选改为 `status=approved`，返回新批准候选的 `(key, link, verdict)` 三元组列表（caller 用它去 append `config.groups` 并决定哪些要 join）。

- [x] **Step 1: Write failing tests**

```python
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
```

- [x] **Step 2: Run tests to confirm failure**

```bash
pytest tests/test_candidate_pool.py -v -k "apply_llm_approvals"
```
Expected: FAIL with `AttributeError: 'CandidatePool' object has no attribute 'apply_llm_approvals'`

- [x] **Step 3: Implement `apply_llm_approvals`**

In `candidate_pool.py`:

```python
    def apply_llm_approvals(self) -> list[dict]:
        """Promote pending candidates with llm_approved_high/medium verdicts
        to status=approved. Returns a list of dicts:

            [{"key": str, "link": str, "verdict": str, "confidence": str}, ...]

        Caller is responsible for appending links to config.groups and
        deciding which (high vs medium) to feed into JoinThrottle.
        Idempotent — already-approved candidates are not returned again.
        """
        promoted: list[dict] = []
        for key, entry in self._candidates.items():
            if entry.get("status") != "pending":
                continue
            verdict = entry.get("llm_verdict") or {}
            v_name = verdict.get("verdict")
            if v_name not in ("llm_approved_high", "llm_approved_medium"):
                continue
            entry["status"] = "approved"
            link = (
                f"https://t.me/+{entry['invite_hash']}"
                if entry.get("invite_hash")
                else f"https://t.me/{key}"
            )
            promoted.append({
                "key": key,
                "link": link,
                "verdict": v_name,
                "confidence": verdict.get("confidence", ""),
            })
        return promoted
```

- [x] **Step 4: Run tests to confirm pass**

```bash
pytest tests/test_candidate_pool.py -v
```
Expected: PASS (all)

- [x] **Step 5: Commit**

```bash
git add tg_intel_crawler/collector/candidate_pool.py tests/test_candidate_pool.py
git commit -m "feat(candidate_pool): add apply_llm_approvals — promote llm_approved candidates to status=approved"
```

---

## Task 6: `CandidateReviewer` —— Stage 1 评审 (mock LLM)

**Files:**
- Create: `tg_intel_crawler/filter/candidate_reviewer.py`
- Test: `tests/test_candidate_reviewer.py`

按 spec §5.1。Stage 1 接受一个 candidate 列表，构建 metadata-only 提示词，调用 LLM，解析 `[{index, decision, confidence, reason}]` 数组，返回结构化结果。

- [x] **Step 1: Write failing tests for Stage 1 prompt building and parsing**

```python
# tests/test_candidate_reviewer.py
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from tg_intel_crawler.filter.candidate_reviewer import (
    CandidateReviewer, Stage1Decision,
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
```

- [x] **Step 2: Run tests to confirm failure**

```bash
pytest tests/test_candidate_reviewer.py -v
```
Expected: FAIL with `ModuleNotFoundError`

- [x] **Step 3: Implement minimal `CandidateReviewer` with Stage1 helpers**

```python
# tg_intel_crawler/filter/candidate_reviewer.py
"""LLM-driven candidate-group reviewer.

Two-stage decision pipeline (see
docs/superpowers/specs/2026-06-06-llm-candidate-reviewer-design.md):

  Stage 1 — cheap metadata triage (batched).
  Stage 2 — expensive raw-text adjudication (one candidate at a time).

This module owns the prompts, schemas, and downgrade rules. It does NOT
write yaml or join groups — that is the CLI orchestrator's job.
"""

from __future__ import annotations

import enum
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from openai import AsyncOpenAI

logger = logging.getLogger("tg_crawler")


class Stage1Decision(enum.Enum):
    ADVANCE = "advance"
    REJECT = "reject"
    UNCERTAIN = "uncertain"


@dataclass
class Stage1Result:
    index: int
    decision: Stage1Decision
    confidence: str  # "high" | "medium" | "low"
    reason: str


STAGE1_SYSTEM_PROMPT = """你是一个黑灰产情报分析专家。下面给你一批候选 Telegram 群组（candidates），\
每条候选包含：群名/邀请哈希、被提到的次数、最早/最近出现时间、被哪些来源群传播、来源群本身的历史情报\
信誉（high/medium 计数）。

判断每个候选是否值得进一步审查（是否可能是字节跳动/抖音/TikTok 相关黑灰产群）。

返回 JSON 数组（不要其他内容），每个元素：
- index: 候选编号（从0开始，与输入对应）
- decision: "advance" | "reject" | "uncertain"
  - advance: 信号明确，疑似黑灰产，进入下一阶段拿原文细看
  - reject: 明显无关（例如来源群是羊毛福利群、count 极低、群名无关键信号）
  - uncertain: 信号模糊，进入下一阶段但用更严标准
- confidence: "high" | "medium" | "low"，对你的 decision 有多确信
- reason: 一句话中文理由

只返回 JSON 数组，不要 markdown 围栏。"""


class CandidateReviewer:
    def __init__(
        self,
        *,
        llm_config: dict,
        intel_stats,           # IntelStatsAggregator-like (.score_for(group))
        raw_lookup,            # RawMessageLookup-like (.get(group, msg_id)) or None
        client: AsyncOpenAI | None = None,
    ):
        self._llm_config = llm_config
        self._intel_stats = intel_stats
        self._raw_lookup = raw_lookup
        self._client = client or AsyncOpenAI(
            api_key=llm_config["api_key"],
            base_url=llm_config["base_url"],
        )
        self._model = llm_config["model"]

    # ---------- Stage 1 ----------

    def _candidate_to_stage1_dict(self, c: dict) -> dict:
        key = c["key"]
        kind = "private" if key.startswith("+") else "public"
        sources = c.get("sources") or []
        score_table = {
            s["group"]: self._intel_stats.score_for(s["group"])
            for s in sources
            if s.get("group")
        }
        return {
            "key": key,
            "type": kind,
            "count": int(c.get("count", 0)),
            "first_seen": (c.get("first_seen") or "")[:10],
            "last_seen": (c.get("last_seen") or "")[:10],
            "sources": [
                {"group": s.get("group", ""), "channel": s.get("channel", "")}
                for s in sources
            ],
            "source_groups_intel_score": score_table,
        }

    def _build_stage1_prompt(self, candidates: list[dict]) -> str:
        items = []
        for i, c in enumerate(candidates):
            items.append({"index": i, **self._candidate_to_stage1_dict(c)})
        body = json.dumps(items, ensure_ascii=False, indent=2)
        return f"请审查以下 {len(candidates)} 个候选群组：\n\n{body}"

    def _parse_stage1_response(
        self, response_text: str, expected_count: int
    ) -> list[Stage1Result]:
        text = response_text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning("stage1 parse failed: %s", e)
            return []
        if not isinstance(data, list) or len(data) != expected_count:
            logger.warning(
                "stage1 count mismatch: got %s expected %d",
                len(data) if isinstance(data, list) else "non-list",
                expected_count,
            )
            return []
        out: list[Stage1Result] = []
        for item in data:
            try:
                idx = int(item["index"])
            except (KeyError, TypeError, ValueError):
                continue
            dec_raw = (item.get("decision") or "").lower()
            try:
                dec = Stage1Decision(dec_raw)
            except ValueError:
                dec = Stage1Decision.UNCERTAIN
            out.append(Stage1Result(
                index=idx,
                decision=dec,
                confidence=(item.get("confidence") or "").lower(),
                reason=item.get("reason") or "",
            ))
        return out

    async def stage1_review(
        self, candidates: list[dict], *, batch_size: int = 30
    ) -> list[Stage1Result]:
        """Run Stage 1 over all candidates, batching by ``batch_size``."""
        results: list[Stage1Result] = []
        for start in range(0, len(candidates), batch_size):
            batch = candidates[start:start + batch_size]
            prompt = self._build_stage1_prompt(batch)
            try:
                resp = await self._client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": STAGE1_SYSTEM_PROMPT},
                        {"role": "user",   "content": prompt},
                    ],
                    temperature=0.1,
                )
                content = resp.choices[0].message.content
            except Exception as e:
                logger.warning("stage1 LLM call failed for batch %d: %s", start, e)
                continue
            parsed = self._parse_stage1_response(content, expected_count=len(batch))
            # Re-base the local index back to the global candidate index.
            for r in parsed:
                if 0 <= r.index < len(batch):
                    r.index = start + r.index
                    results.append(r)
        return results
```

- [x] **Step 4: Run tests to confirm pass**

```bash
pytest tests/test_candidate_reviewer.py -v
```
Expected: PASS (4/4)

- [x] **Step 5: Add integration test for batched stage1_review with mocked LLM**

Append to `tests/test_candidate_reviewer.py`:

```python
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
```

- [x] **Step 6: Run tests to confirm pass**

```bash
pytest tests/test_candidate_reviewer.py -v
```
Expected: PASS (5/5)

- [x] **Step 7: Commit**

```bash
git add tg_intel_crawler/filter/candidate_reviewer.py tests/test_candidate_reviewer.py
git commit -m "feat(filter): add CandidateReviewer Stage 1 — metadata-only batched LLM triage"
```

---

## Task 7: `CandidateReviewer` —— Stage 2 评审 (raw-text adjudication)

**Files:**
- Modify: `tg_intel_crawler/filter/candidate_reviewer.py`
- Test: `tests/test_candidate_reviewer.py`

按 spec §5.2。Stage 2 一次审一条候选，用 `RawMessageLookup` 拉来源消息原文（最多取 sources 里前 3 条），调用 LLM 拿单对象 verdict，再应用降级规则得到最终 verdict 字符串。

降级规则（spec §5.2 末尾）：
- 私密群（key 以 `+` 开头）→ 降一级
- Stage1 是 `uncertain` → 降一级
- raw 原文一条都没找到 → 降一级
- 三种降级**累加**，最低封顶在 `low`（不会变成 reject）。
- LLM Stage 2 原本就 `reject` → 直接 `llm_rejected`，跳过降级链路。

- [x] **Step 1: Write failing test for confidence downgrade pure function**

```python
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
```

- [x] **Step 2: Run tests to confirm failure**

```bash
pytest tests/test_candidate_reviewer.py -v -k "downgrade"
```
Expected: FAIL

- [x] **Step 3: Add `_apply_downgrades` to `CandidateReviewer`**

In `candidate_reviewer.py`:

```python
    _CONFIDENCE_LADDER = ("high", "medium", "low")

    def _apply_downgrades(self, confidence: str, levels: int) -> str:
        """Lower confidence by N steps along high → medium → low. Floors at low."""
        if confidence not in self._CONFIDENCE_LADDER:
            return "low"
        idx = self._CONFIDENCE_LADDER.index(confidence)
        return self._CONFIDENCE_LADDER[min(idx + max(levels, 0), len(self._CONFIDENCE_LADDER) - 1)]
```

- [x] **Step 4: Run tests to confirm pass**

```bash
pytest tests/test_candidate_reviewer.py -v -k "downgrade"
```
Expected: PASS (3/3)

- [x] **Step 5: Write failing tests for stage2 prompt building and parsing**

```python
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
```

- [x] **Step 6: Run tests to confirm failure**

```bash
pytest tests/test_candidate_reviewer.py -v -k "stage2"
```
Expected: FAIL

- [x] **Step 7: Implement Stage 2 prompt + parse + dataclass**

Add to `candidate_reviewer.py`:

```python
@dataclass
class Stage2Result:
    decision: str           # "approve" | "reject"
    confidence: str         # "high" | "medium" | "low"
    risk_type: str
    reason: str


STAGE2_SYSTEM_PROMPT = """你是一个黑灰产情报分析专家。下面给你一个 Telegram 候选群组以及它在已知群里被传播\
时的来源消息原文。判断它是否值得加入字节系黑灰产监控。

返回 JSON 对象（不要其他内容）：
- decision: "approve" | "reject"
- confidence: "high" | "medium" | "low"
- risk_type: 账号交易 | 刷量作弊 | 引流诈骗 | 数据泄露 | 工具交易 | 其他（reject 时为空）
- reason: 一句话中文理由

只返回 JSON 对象。"""
```

(The `Stage2Result` dataclass goes near the top, beside `Stage1Result`.)

```python
    def _build_stage2_prompt(
        self, candidate: dict, stage1: Optional[Stage1Result]
    ) -> tuple[str, int]:
        """Build Stage 2 prompt; returns (prompt_text, raw_text_found_count)."""
        key = candidate["key"]
        sources = candidate.get("sources") or []
        s1_note = (
            f"[Stage1: decision={stage1.decision.value}, confidence={stage1.confidence}, "
            f"reason={stage1.reason}]\n"
            if stage1 is not None
            else ""
        )

        lines = [s1_note + f"候选：{key}"]
        lines.append(
            f"出现 {candidate.get('count', 0)} 次, "
            f"first_seen={candidate.get('first_seen','')[:10]}, "
            f"last_seen={candidate.get('last_seen','')[:10]}"
        )
        lines.append("来源记录（最多 3 条）：")

        found = 0
        for i, s in enumerate(sources[:3]):
            grp = s.get("group", "")
            msg_id = s.get("msg_id")
            channel = s.get("channel", "")
            if self._raw_lookup is not None and msg_id is not None:
                text = self._raw_lookup.get(grp, msg_id)
            else:
                text = None
            if text:
                found += 1
                lines.append(f"[{i+1}] 群={grp}, msg_id={msg_id}, channel={channel}")
                lines.append(f'原文："{text}"')
            else:
                lines.append(
                    f"[{i+1}] 群={grp}, msg_id={msg_id}, channel={channel} — [原文未找到]"
                )

        return "\n".join(lines), found

    def _parse_stage2_response(self, response_text: str) -> Optional[Stage2Result]:
        text = response_text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning("stage2 parse failed: %s", e)
            return None
        if not isinstance(data, dict):
            return None
        decision = (data.get("decision") or "").lower()
        if decision not in ("approve", "reject"):
            logger.warning("stage2 unknown decision: %r", decision)
            return None
        return Stage2Result(
            decision=decision,
            confidence=(data.get("confidence") or "").lower() or "low",
            risk_type=data.get("risk_type") or "",
            reason=data.get("reason") or "",
        )
```

- [x] **Step 8: Run tests to confirm pass**

```bash
pytest tests/test_candidate_reviewer.py -v -k "stage2"
```
Expected: PASS (4/4)

- [x] **Step 9: Write failing test for `review_one` orchestration**

```python
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
```

- [x] **Step 10: Run tests to confirm failure**

```bash
pytest tests/test_candidate_reviewer.py -v -k "review_one"
```
Expected: FAIL with `AttributeError: 'CandidateReviewer' object has no attribute 'review_one'`

- [x] **Step 11: Implement `review_one` orchestration**

```python
    async def review_one(
        self, candidate: dict, *, stage1: Optional[Stage1Result],
    ) -> Optional[dict]:
        """Run Stage 2 (or short-circuit on Stage1 reject) and return a verdict
        block ready to hand to ``CandidatePool.set_llm_verdict``.

        Returns None on LLM failure (caller should skip writing verdict so
        increment-rereview will pick this candidate up next run).
        """
        from datetime import datetime, timezone

        now_iso = datetime.now(timezone.utc).isoformat()
        cur_count = int(candidate.get("count", 0))

        # --- Short-circuit: Stage 1 reject ---
        if stage1 is not None and stage1.decision is Stage1Decision.REJECT:
            return {
                "verdict": "llm_rejected",
                "confidence": stage1.confidence or "low",
                "risk_type": "",
                "reason": stage1.reason or "stage1 rejected",
                "reviewed_at": now_iso,
                "reviewed_count": cur_count,
                "stage": 1,
                "model": self._model,
            }

        # --- Stage 2 LLM call ---
        prompt, raw_found = self._build_stage2_prompt(candidate, stage1=stage1)
        try:
            resp = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": STAGE2_SYSTEM_PROMPT},
                    {"role": "user",   "content": prompt},
                ],
                temperature=0.1,
            )
            content = resp.choices[0].message.content
        except Exception as e:
            logger.warning("stage2 LLM call failed for %s: %s", candidate.get("key"), e)
            return None

        s2 = self._parse_stage2_response(content)
        if s2 is None:
            return None

        # --- Stage 2 reject ---
        if s2.decision == "reject":
            return {
                "verdict": "llm_rejected",
                "confidence": s2.confidence or "low",
                "risk_type": "",
                "reason": s2.reason,
                "reviewed_at": now_iso,
                "reviewed_count": cur_count,
                "stage": 2,
                "model": self._model,
            }

        # --- Stage 2 approve: apply downgrades ---
        downgrade = 0
        if stage1 is not None and stage1.decision is Stage1Decision.UNCERTAIN:
            downgrade += 1
        if candidate["key"].startswith("+"):
            downgrade += 1
        if raw_found == 0:
            downgrade += 1

        final_conf = self._apply_downgrades(s2.confidence, levels=downgrade)
        verdict_name = {
            "high":   "llm_approved_high",
            "medium": "llm_approved_medium",
            "low":    "llm_approved_low",
        }[final_conf]

        return {
            "verdict": verdict_name,
            "confidence": final_conf,
            "risk_type": s2.risk_type,
            "reason": s2.reason,
            "reviewed_at": now_iso,
            "reviewed_count": cur_count,
            "stage": 2,
            "model": self._model,
        }
```

- [x] **Step 12: Run all reviewer tests to confirm pass**

```bash
pytest tests/test_candidate_reviewer.py -v
```
Expected: PASS (all)

- [x] **Step 13: Commit**

```bash
git add tg_intel_crawler/filter/candidate_reviewer.py tests/test_candidate_reviewer.py
git commit -m "feat(filter): add CandidateReviewer Stage 2 — raw-text adjudication + downgrade rules"
```

---

## Task 8: CLI 子命令 `candidates llm-review` —— 编排 + 写盘 + 加群

**Files:**
- Modify: `tg_intel_crawler/main.py`
- Test: `tests/test_main_llm_review.py`

按 spec §6。把组件粘起来：score → pick → stage1 → stage2 → write verdict → optional write_config → optional auto_join → 汇总打印。

- [x] **Step 1: Write failing test for the `--auto-join` without `--write-config` guard**

```python
# tests/test_main_llm_review.py
"""End-to-end-ish tests for `tg-crawler candidates llm-review`.

We mock the LLM client (so no real API), the TGClient (so no real Telegram),
and use tmp_path for the candidate yaml + output dirs.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from click.testing import CliRunner

from tg_intel_crawler.main import cli


def _seed_config(tmp_path: Path, candidates_path: Path) -> Path:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.safe_dump({
        "telegram": {"api_id": 1, "api_hash": "x", "phone": "+1", "session_name": "s"},
        "llm": {"api_key": "k", "base_url": "https://example.com/v1",
                "model": "ep-test", "batch_size": 5},
        "crawl": {"delay_min": 0, "delay_max": 0, "history_days": 7, "download_media": False},
        "output": {"dir": str(tmp_path / "output"), "format": ["json"]},
        "groups": [],
        "discovery": {"candidates_path": str(candidates_path)},
        "join": {"min_interval": 0, "max_interval": 0, "daily_limit": 5},
    }, allow_unicode=True), encoding="utf-8")
    return cfg_path


def _seed_candidates(path: Path):
    payload = {"candidates": {
        "douyinhao88": {
            "invite_hash": None,
            "first_seen": "2026-06-05T00:00:00+00:00",
            "last_seen":  "2026-06-08T00:00:00+00:00",
            "count": 7,
            "status": "pending",
            "sources": [{"group": "卖号群", "msg_id": 100, "channel": "text"}],
        },
    }}
    path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")


def test_auto_join_without_write_config_errors(tmp_path, monkeypatch):
    cands = tmp_path / "discovered_groups.yaml"
    _seed_candidates(cands)
    cfg = _seed_config(tmp_path, cands)
    monkeypatch.setattr("tg_intel_crawler.main.CONFIG_PATH", cfg)

    runner = CliRunner()
    result = runner.invoke(cli, ["candidates", "llm-review", "--auto-join"])
    assert result.exit_code != 0
    assert "--auto-join requires --write-config" in result.output
```

- [x] **Step 2: Run test to confirm failure**

```bash
pytest tests/test_main_llm_review.py::test_auto_join_without_write_config_errors -v
```
Expected: FAIL — command does not exist yet.

- [x] **Step 3: Add the click command + flag guard in `main.py`**

In `tg_intel_crawler/main.py`, add after the `candidates_stats` function (around line 1183):

```python
@candidates_cmd.command(name="llm-review")
@click.option("--max-candidates", default=200, type=int,
              help="Cap candidates per run (top-N by score).")
@click.option("--stage1-batch-size", default=30, type=int,
              help="Stage 1 LLM batch size.")
@click.option("--write-config", is_flag=True, default=False,
              help="Promote llm_approved_high/medium to status=approved and "
                   "append to config.groups.")
@click.option("--auto-join", is_flag=True, default=False,
              help="Also limit-rate-join llm_approved_high candidates "
                   "(requires --write-config).")
@click.option("--force-rereview", is_flag=True, default=False,
              help="Re-review all pending candidates regardless of cache.")
@click.option("--dry-run", is_flag=True, default=False,
              help="Run review but do not persist verdicts, status, or joins.")
@click.option("--include-private/--no-include-private", default=True,
              help="Include private (+hash) candidates (auto-downgraded one level).")
def candidates_llm_review(
    max_candidates, stage1_batch_size, write_config, auto_join,
    force_rereview, dry_run, include_private,
):
    """LLM-driven review of pending candidates → verdicts in yaml."""
    if auto_join and not write_config:
        raise click.UsageError("--auto-join requires --write-config")
    asyncio.run(_candidates_llm_review_async(
        max_candidates=max_candidates,
        stage1_batch_size=stage1_batch_size,
        write_config=write_config,
        auto_join=auto_join,
        force_rereview=force_rereview,
        dry_run=dry_run,
        include_private=include_private,
    ))


async def _candidates_llm_review_async(*, **_):
    raise NotImplementedError  # filled in by next steps
```

(The `**_` placeholder is so the click handler exists for the guard test; the body comes next step.)

- [x] **Step 4: Run guard test to confirm pass**

```bash
pytest tests/test_main_llm_review.py::test_auto_join_without_write_config_errors -v
```
Expected: PASS

- [x] **Step 5: Write failing test for the dry-run end-to-end happy path**

```python
def _make_mock_llm(stage1_advance=True, stage2_approve=True):
    """Returns a function that produces an LLM client whose responses match
    the stage we're hitting."""
    stage1_payload = json.dumps([
        {"index": 0,
         "decision": "advance" if stage1_advance else "reject",
         "confidence": "high", "reason": "ok"},
    ])
    stage2_payload = json.dumps({
        "decision": "approve" if stage2_approve else "reject",
        "confidence": "high",
        "risk_type": "账号交易",
        "reason": "明确卖号",
    })
    client = MagicMock()
    # Stage1 happens first; stage2 follows. Use side_effect list.
    client.chat.completions.create = AsyncMock(side_effect=[
        MagicMock(choices=[MagicMock(message=MagicMock(content=stage1_payload))]),
        MagicMock(choices=[MagicMock(message=MagicMock(content=stage2_payload))]),
    ])
    return client


def test_dry_run_does_not_write_verdict_or_change_status(tmp_path, monkeypatch):
    cands = tmp_path / "discovered_groups.yaml"
    _seed_candidates(cands)
    cfg = _seed_config(tmp_path, cands)
    monkeypatch.setattr("tg_intel_crawler.main.CONFIG_PATH", cfg)

    fake_client = _make_mock_llm(stage1_advance=True, stage2_approve=True)
    monkeypatch.setattr(
        "tg_intel_crawler.filter.candidate_reviewer.AsyncOpenAI",
        lambda **kw: fake_client,
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["candidates", "llm-review", "--dry-run"])
    assert result.exit_code == 0, result.output

    raw = yaml.safe_load(cands.read_text(encoding="utf-8"))
    entry = raw["candidates"]["douyinhao88"]
    assert "llm_verdict" not in entry
    assert entry["status"] == "pending"
```

- [x] **Step 6: Implement `_candidates_llm_review_async`**

Replace the placeholder `_candidates_llm_review_async`:

```python
async def _candidates_llm_review_async(
    *,
    max_candidates: int,
    stage1_batch_size: int,
    write_config: bool,
    auto_join: bool,
    force_rereview: bool,
    dry_run: bool,
    include_private: bool,
):
    from datetime import datetime, timezone

    from tg_intel_crawler.collector.candidate_pool import CandidatePool
    from tg_intel_crawler.collector.client import TGClient
    from tg_intel_crawler.collector.group_finder import GroupFinder
    from tg_intel_crawler.collector.join_throttle import DailyLimitExceeded
    from tg_intel_crawler.collector.joined_scanner import JoinedGroupsScanner
    from tg_intel_crawler.filter.candidate_reviewer import (
        CandidateReviewer, Stage1Decision,
    )
    from tg_intel_crawler.storage.intel_stats import IntelStatsAggregator
    from tg_intel_crawler.storage.raw_lookup import RawMessageLookup

    logger = logging.getLogger("tg_crawler")
    config = load_config()
    out_dir = Path(config["output"]["dir"])

    pool = CandidatePool(_candidates_path(config))
    intel_stats = IntelStatsAggregator(str(out_dir / "filtered"))
    raw_lookup = RawMessageLookup(str(out_dir / "raw"))

    if not (out_dir / "raw").exists():
        click.echo("⚠️  output/raw/ missing — Stage 2 will rely on metadata only "
                   "and downgrade confidence.")
    if not (out_dir / "filtered").exists():
        click.echo("⚠️  output/filtered/ missing — source-group reputation will be empty.")

    # --- Pick candidates ---
    now = datetime.now(timezone.utc)
    pending = pool.pending_for_review(now=now, force_rereview=force_rereview)
    if not include_private:
        pending = [c for c in pending if not c["key"].startswith("+")]
    # Filter out empty-source candidates (no evidence at all).
    pending = [c for c in pending if c.get("sources")]

    def _score(c):
        sources = c.get("sources") or []
        max_high = max(
            (intel_stats.score_for(s.get("group", "")).get("high", 0) for s in sources),
            default=0,
        )
        return int(c.get("count", 0)) * max(max_high, 1)

    pending.sort(key=_score, reverse=True)
    selected = pending[:max_candidates]

    if not selected:
        click.echo("ℹ️  No candidates need review.")
        return

    click.echo(f"🔎 Reviewing {len(selected)} of {len(pending)} candidates "
               f"(max-candidates={max_candidates}).")

    reviewer = CandidateReviewer(
        llm_config=config["llm"],
        intel_stats=intel_stats,
        raw_lookup=raw_lookup,
    )

    # --- Stage 1 ---
    stage1_results = await reviewer.stage1_review(
        selected, batch_size=stage1_batch_size,
    )
    stage1_by_idx = {r.index: r for r in stage1_results}

    # --- Stage 2 (per candidate) ---
    counters = {
        "stage1_reject": 0, "stage1_advance": 0, "stage1_uncertain": 0,
        "stage2_approve_high": 0, "stage2_approve_medium": 0,
        "stage2_approve_low": 0, "stage2_reject": 0,
        "skipped_no_stage1": 0,
        "verdicts_written": 0,
    }

    for i, candidate in enumerate(selected):
        s1 = stage1_by_idx.get(i)
        if s1 is None:
            counters["skipped_no_stage1"] += 1
            continue

        if s1.decision is Stage1Decision.REJECT:
            counters["stage1_reject"] += 1
        elif s1.decision is Stage1Decision.ADVANCE:
            counters["stage1_advance"] += 1
        else:
            counters["stage1_uncertain"] += 1

        verdict = await reviewer.review_one(candidate, stage1=s1)
        if verdict is None:
            continue

        v_name = verdict["verdict"]
        if v_name == "llm_approved_high":
            counters["stage2_approve_high"] += 1
        elif v_name == "llm_approved_medium":
            counters["stage2_approve_medium"] += 1
        elif v_name == "llm_approved_low":
            counters["stage2_approve_low"] += 1
        elif v_name == "llm_rejected" and verdict["stage"] == 2:
            counters["stage2_reject"] += 1

        if not dry_run:
            pool.set_llm_verdict(candidate["key"], verdict)
            counters["verdicts_written"] += 1

    if not dry_run:
        pool.flush()

    # --- Optional: write_config + auto_join ---
    promoted = []
    joined_count = 0
    daily_limit_hit = False

    if not dry_run and write_config:
        promoted = pool.apply_llm_approvals()
        pool.flush()

        # append to config.groups (dedup)
        config.setdefault("groups", [])
        existing = set(config["groups"])
        for p in promoted:
            if p["link"] not in existing:
                config["groups"].append(p["link"])
                existing.add(p["link"])
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)

        if auto_join:
            high_only = [p for p in promoted if p["confidence"] == "high"]
            if high_only:
                throttle = _make_join_throttle(config)
                async with TGClient(str(CONFIG_PATH)) as tg:
                    scanner = JoinedGroupsScanner(tg.client)
                    joined = await scanner.list_joined()
                    throttle.warmup(
                        usernames={g.username for g in joined if g.username},
                        chat_ids={g.chat_id for g in joined},
                    )
                    finder = GroupFinder(tg.client)
                    for p in high_only:
                        target = p["key"]
                        try:
                            await throttle.run_join(
                                target, lambda t=target: finder.join_group(t),
                            )
                            joined_count += 1
                        except DailyLimitExceeded:
                            daily_limit_hit = True
                            break
                        except Exception as e:
                            logger.warning("auto-join %s failed: %s", target, e)

    # --- Summary ---
    click.echo("")
    click.echo("📊 LLM Review Summary")
    click.echo(f"  Reviewed:           {len(selected)} candidates "
               f"(out of {len(pending)} pending)")
    click.echo(f"  Stage 1 reject:     {counters['stage1_reject']}   → llm_rejected")
    click.echo(f"  Stage 1 advance:    {counters['stage1_advance']}   → Stage 2")
    click.echo(f"  Stage 1 uncertain:  {counters['stage1_uncertain']}   → Stage 2")
    s2_approve = (counters["stage2_approve_high"]
                  + counters["stage2_approve_medium"]
                  + counters["stage2_approve_low"])
    click.echo(f"  Stage 2 approve:    {s2_approve}   "
               f"(high={counters['stage2_approve_high']} / "
               f"medium={counters['stage2_approve_medium']} / "
               f"low={counters['stage2_approve_low']})")
    click.echo(f"  Stage 2 reject:     {counters['stage2_reject']}   → llm_rejected")
    if dry_run:
        click.echo("  [dry-run] no verdicts written, no status changed.")
    else:
        click.echo(f"  Verdicts written:   {counters['verdicts_written']}")
        if write_config:
            click.echo(f"  --write-config: appended {len(promoted)} links to config.groups")
        if auto_join:
            tail = " (hit daily_limit)" if daily_limit_hit else ""
            click.echo(f"  --auto-join:    joined {joined_count} groups{tail}")
```

Note: `Path` and `logging` are already imported at the top of `main.py`; no extra imports needed there.

- [x] **Step 7: Run dry-run test to confirm pass**

```bash
pytest tests/test_main_llm_review.py::test_dry_run_does_not_write_verdict_or_change_status -v
```
Expected: PASS

- [x] **Step 8: Add tests for verdict-write and write-config paths**

```python
def test_review_writes_verdict_to_yaml(tmp_path, monkeypatch):
    cands = tmp_path / "discovered_groups.yaml"
    _seed_candidates(cands)
    cfg = _seed_config(tmp_path, cands)
    monkeypatch.setattr("tg_intel_crawler.main.CONFIG_PATH", cfg)

    fake_client = _make_mock_llm(stage1_advance=True, stage2_approve=True)
    monkeypatch.setattr(
        "tg_intel_crawler.filter.candidate_reviewer.AsyncOpenAI",
        lambda **kw: fake_client,
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["candidates", "llm-review"])
    assert result.exit_code == 0, result.output

    raw = yaml.safe_load(cands.read_text(encoding="utf-8"))
    entry = raw["candidates"]["douyinhao88"]
    assert entry["status"] == "pending"  # not changed without --write-config
    assert entry["llm_verdict"]["verdict"] == "llm_approved_high"


def test_write_config_promotes_high_to_approved_and_appends_groups(tmp_path, monkeypatch):
    cands = tmp_path / "discovered_groups.yaml"
    _seed_candidates(cands)
    cfg = _seed_config(tmp_path, cands)
    monkeypatch.setattr("tg_intel_crawler.main.CONFIG_PATH", cfg)

    fake_client = _make_mock_llm(stage1_advance=True, stage2_approve=True)
    monkeypatch.setattr(
        "tg_intel_crawler.filter.candidate_reviewer.AsyncOpenAI",
        lambda **kw: fake_client,
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["candidates", "llm-review", "--write-config"])
    assert result.exit_code == 0, result.output

    raw = yaml.safe_load(cands.read_text(encoding="utf-8"))
    assert raw["candidates"]["douyinhao88"]["status"] == "approved"

    cfg_after = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert "https://t.me/douyinhao88" in cfg_after["groups"]


def test_stage1_reject_does_not_call_stage2(tmp_path, monkeypatch):
    """A candidate Stage 1 rejects must result in 1 LLM call total, not 2."""
    cands = tmp_path / "discovered_groups.yaml"
    _seed_candidates(cands)
    cfg = _seed_config(tmp_path, cands)
    monkeypatch.setattr("tg_intel_crawler.main.CONFIG_PATH", cfg)

    fake_client = _make_mock_llm(stage1_advance=False, stage2_approve=True)
    monkeypatch.setattr(
        "tg_intel_crawler.filter.candidate_reviewer.AsyncOpenAI",
        lambda **kw: fake_client,
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["candidates", "llm-review"])
    assert result.exit_code == 0, result.output
    # Stage 1 has 1 call, Stage 2 should NOT happen because stage1=reject.
    assert fake_client.chat.completions.create.call_count == 1

    raw = yaml.safe_load(cands.read_text(encoding="utf-8"))
    assert raw["candidates"]["douyinhao88"]["llm_verdict"]["verdict"] == "llm_rejected"
    assert raw["candidates"]["douyinhao88"]["llm_verdict"]["stage"] == 1
```

- [x] **Step 9: Run all main tests**

```bash
pytest tests/test_main_llm_review.py -v
```
Expected: PASS (4/4)

- [x] **Step 10: Run full suite to check for regressions**

```bash
pytest -q
```
Expected: PASS (all tests)

- [x] **Step 11: Commit**

```bash
git add tg_intel_crawler/main.py tests/test_main_llm_review.py
git commit -m "feat(cli): add 'candidates llm-review' subcommand — LLM-driven candidate triage with optional auto-join"
```

---

## Task 9: 给 `candidates list` 加 `--llm-verdict` 过滤

**Files:**
- Modify: `tg_intel_crawler/main.py`
- Test: `tests/test_main_llm_review.py`

按 spec §8 附带改动。

- [x] **Step 1: Write failing test**

Append to `tests/test_main_llm_review.py`:

```python
def test_list_filter_by_llm_verdict(tmp_path, monkeypatch):
    cands = tmp_path / "discovered_groups.yaml"
    payload = {"candidates": {
        "a": {"invite_hash": None, "first_seen": "2026-06-05T00:00:00+00:00",
              "last_seen": "2026-06-05T00:00:00+00:00", "count": 1,
              "status": "pending", "sources": [{"group": "g", "msg_id": 1, "channel": "text"}],
              "llm_verdict": {"verdict": "llm_approved_high", "confidence": "high",
                              "risk_type": "账号交易", "reason": "x",
                              "reviewed_at": "2026-06-06T00:00:00+00:00",
                              "reviewed_count": 1, "stage": 2, "model": "ep"}},
        "b": {"invite_hash": None, "first_seen": "2026-06-05T00:00:00+00:00",
              "last_seen": "2026-06-05T00:00:00+00:00", "count": 1,
              "status": "pending", "sources": [{"group": "g", "msg_id": 2, "channel": "text"}],
              "llm_verdict": {"verdict": "llm_rejected", "confidence": "high",
                              "risk_type": "", "reason": "y",
                              "reviewed_at": "2026-06-06T00:00:00+00:00",
                              "reviewed_count": 1, "stage": 1, "model": "ep"}},
        "c": {"invite_hash": None, "first_seen": "2026-06-05T00:00:00+00:00",
              "last_seen": "2026-06-05T00:00:00+00:00", "count": 1,
              "status": "pending", "sources": [{"group": "g", "msg_id": 3, "channel": "text"}]},
    }}
    cands.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
    cfg = _seed_config(tmp_path, cands)
    monkeypatch.setattr("tg_intel_crawler.main.CONFIG_PATH", cfg)

    runner = CliRunner()
    r1 = runner.invoke(cli, ["candidates", "list", "--status", "all", "--llm-verdict", "llm_approved_high"])
    assert r1.exit_code == 0
    assert "a " in r1.output or "a\n" in r1.output or "  a " in r1.output
    assert "b " not in r1.output and "c " not in r1.output

    r2 = runner.invoke(cli, ["candidates", "list", "--status", "all", "--llm-verdict", "none"])
    assert r2.exit_code == 0
    assert "c " in r2.output or "c\n" in r2.output or "  c " in r2.output
```

- [x] **Step 2: Run test to confirm failure**

```bash
pytest tests/test_main_llm_review.py::test_list_filter_by_llm_verdict -v
```
Expected: FAIL — `--llm-verdict` not recognized.

- [x] **Step 3: Modify `candidates_list` in `main.py`**

Find the existing `candidates_list` function (around line 1066) and replace with:

```python
@candidates_cmd.command(name="list")
@click.option(
    "--status",
    type=click.Choice(["pending", "approved", "rejected", "all"]),
    default="pending",
)
@click.option(
    "--llm-verdict",
    type=click.Choice([
        "llm_approved_high", "llm_approved_medium", "llm_approved_low",
        "llm_rejected", "none", "any",
    ]),
    default="any",
    help='Filter by llm_verdict.verdict; "none" = never reviewed, "any" = no filter.',
)
def candidates_list(status: str, llm_verdict: str):
    """List candidates discovered from crawled messages."""
    config = load_config()
    pool = CandidatePool(_candidates_path(config))
    items = pool.list_all(status=None if status == "all" else status)

    if llm_verdict != "any":
        if llm_verdict == "none":
            items = [c for c in items if not c.get("llm_verdict")]
        else:
            items = [
                c for c in items
                if (c.get("llm_verdict") or {}).get("verdict") == llm_verdict
            ]

    if not items:
        click.echo(f"No candidates match status={status} llm_verdict={llm_verdict}.")
        return

    click.echo(f"{len(items)} candidate(s) [{status}]:\n")
    for c in sorted(items, key=lambda x: -x["count"]):
        v = (c.get("llm_verdict") or {}).get("verdict") or "-"
        click.echo(
            f"  {c['key']:<32} count={c['count']:<3} status={c['status']:<8} "
            f"verdict={v:<22} first={c['first_seen'][:19]}"
        )
```

- [x] **Step 4: Run test to confirm pass**

```bash
pytest tests/test_main_llm_review.py::test_list_filter_by_llm_verdict -v
```
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add tg_intel_crawler/main.py tests/test_main_llm_review.py
git commit -m "feat(cli): add --llm-verdict filter to 'candidates list'"
```

---

## Task 10: README 更新 —— 加 "LLM 自动审查" 章节

**Files:**
- Modify: `README.md`

按 spec §6 的 "典型用法序列"。把 LLM review 章节插到 "群组自动扩展" 章节后面，与 `candidates approve/reject` 配套。

- [x] **Step 1: Open the README and locate the candidates table**

Find the CLI 命令汇总 table (line ~458) and add this row right after `candidates stats`:

```markdown
| `tg-crawler candidates llm-review`        | 用 LLM 自动审查 pending 候选，写 verdict + 可选加群     |
```

- [x] **Step 2: Add a new section after "用法 C" (line ~641)**

Insert this new section after the "三种用法的搭配" subsection (after the existing line ~654 with the table headed "你想要的效果"):

```markdown

#### 用法 D：让 LLM 自动审查候选池（替代手动 `candidates approve`）

当候选池长到几千条时，逐条 `candidates approve` 看不过来。`llm-review` 让 LLM 用两阶段方式批量初审：

1. **Stage 1（便宜）**：仅看候选 metadata（key、count、被哪些群传播、来源群历史信誉），批量过滤掉明显无关的（如"今日有羊毛🦙"群里偶尔被 mention 一次的私密群）。
2. **Stage 2（贵）**：对 Stage 1 通过的候选，从 `output/raw/` 拉来源消息原文，让 LLM 在真实上下文里判定是否高价值。

判决落到 yaml 里每个候选的 `llm_verdict` 字段，**不直接动 status**。要让 LLM 的 high/medium 判决真正写入 `config.groups`，需要显式 `--write-config`；要真正加群还需 `--auto-join`（仅对 high 生效，medium 只写 config 不加群）。

```bash
# 1. 试水：跑 50 条看看 LLM 选了啥（不写盘）
tg-crawler candidates llm-review --max-candidates 50 --dry-run

# 2. 正式跑一遍，写 verdict 到 yaml（不动 status）
tg-crawler candidates llm-review --max-candidates 200

# 3. 看 LLM 给了哪些 high
tg-crawler candidates list --status all --llm-verdict llm_approved_high

# 4. 觉得合理后落到 config.groups（仍不加群）
tg-crawler candidates llm-review --write-config

# 5. 真要自动加群：仅对 confidence=high 走 JoinThrottle (30~90s/个，daily_limit=20)
tg-crawler candidates llm-review --write-config --auto-join
```

关键约束：
- LLM 永远不写 `status: rejected`。被 LLM 否决的候选只是 verdict=`llm_rejected`，仍然留在 pending，你想推翻仍能手动 `candidates approve`。
- 重审增量：候选 `count` 翻倍 或 距上次 review 超 30 天，下次 `llm-review` 会自动重看（`--force-rereview` 可强制全部重审）。
- 私密群（`+hash`）置信度自动降一级；用 `--no-include-private` 可彻底跳过。
- `--auto-join` 必须配合 `--write-config`，否则报错（避免"加了群却没记 config"）。
```

- [x] **Step 3: Verify README renders sanely**

```bash
grep -n "llm-review" README.md | head -20
```
Expected output: at least 5 hits, including the table row and the new section.

- [x] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs(readme): add 'LLM 自动审查' section + cli table entry for candidates llm-review"
```

---

## Task 11: 全量测试 + smoke check

最后跑一次完整测试套件，确认没有回归。

- [x] **Step 1: Run full pytest**

```bash
pytest -q
```
Expected: all green; new tests +21 (approx) total.

- [x] **Step 2: Smoke-check the CLI command exists and shows help**

```bash
tg-crawler candidates llm-review --help
```
Expected: prints flag list including `--max-candidates`, `--write-config`, `--auto-join`, `--dry-run`, `--include-private/--no-include-private`, `--force-rereview`, `--stage1-batch-size`.

- [x] **Step 3: Confirm no committed test artifacts**

```bash
git status
```
Expected: clean working tree.

- [x] **Step 4 (optional, manual)**

If you have working credentials in `config/config.yaml` and a candidate pool with real entries, run a tiny live smoke:

```bash
tg-crawler candidates llm-review --max-candidates 3 --dry-run
```
Expected: real LLM calls, summary printed, no yaml mutation. **Do not skip if your `discovered_groups.yaml` is large** — this is the only check that confirms the LLM prompts produce the expected JSON shape against your real model.
