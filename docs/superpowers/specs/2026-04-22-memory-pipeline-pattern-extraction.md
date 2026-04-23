# Memory Pipeline Pattern Extraction — Scope, Risks, and Upstream Path

**Date**: 2026-04-22
**Branch**: `docs-memory-pipeline/pattern-followup`
**Status**: Proposal / pattern package for follow-up discussion
**Related PRs**:
- Frozen memory-storage batch: `bytedance/deer-flow#2434`
- Attempted follow-up code batch with boundary drift: `bytedance/deer-flow#2456`

---

## 1. Goal

Capture the DeerFlow memory pipeline improvements from `meitu/develop` as an upstream-facing **pattern proposal**, while preserving the frozen boundary of PR#2434.

This document exists because the memory pipeline work is important and real, but it does **not** currently fit the same “small, clean, isolated code PR” shape as `thread_mapping` (`#2453`), baseline-sync (`#2454`), or model-feedback (`#2455`).

---

## 2. What the retained memory pipeline actually includes

The retained logic is not one file or one backend. In current `meitu/develop`, the pipeline spans at least:

- `backend/packages/harness/deerflow/agents/memory/message_processing.py`
- `backend/packages/harness/deerflow/agents/memory/summarization_hook.py`
- `backend/packages/harness/deerflow/agents/memory/queue.py`
- `backend/packages/harness/deerflow/agents/memory/updater.py`
- `backend/packages/harness/deerflow/agents/middlewares/memory_middleware.py`
- `backend/packages/harness/deerflow/agents/memory/storage.py`
- `backend/packages/harness/deerflow/config/memory_config.py`
- `backend/packages/harness/deerflow/config/paths.py`
- `backend/packages/harness/deerflow/agents/memory/__init__.py`

and focused tests such as:

- `backend/tests/test_memory_queue.py`
- `backend/tests/test_memory_queue_user_isolation.py`
- `backend/tests/test_memory_updater.py`
- `backend/tests/test_memory_updater_user_isolation.py`
- `backend/tests/test_cross_user_thread_cleanup.py`
- `backend/tests/test_memory_storage_backends_config.py`

This is a **runtime pipeline**, not just a storage backend extension.

---

## 3. Why PR #2456 drifted across the frozen boundary

`freeze-upstream-alignment-pr-scope/review-packet.md` freezes PR#2434 / PR#5 as the **memory storage backend** contract. That frozen contract allows:

- `PostgresMemoryStorage` / `MongoMemoryStorage`
- `memory_config.py`
- required exports
- schema / migration work
- backend loading / compatibility tests

and explicitly forbids:

- `message_processing.py`
- `summarization_hook.py`
- `updater.py`
- `queue.py`
- delete helpers
- broader memory pipeline redesign

PR `#2456` crossed that line because it mixed:

1. the retained pipeline logic (`message_processing`, `summarization_hook`, `queue`, `updater`)
2. with frozen PR#2434-owned files like `storage.py`, `memory_config.py`, `memory/__init__.py`, and `test_memory_storage_backends_config.py`

So the problem with `#2456` is **not that the code is broken** — targeted tests passed — but that the **PR shape redefined the frozen memory boundary**.

---

## 4. What the tests actually prove

On the reconstructed branch for `#2456`, the following targeted test set passed:

```bash
uv run pytest \
  tests/test_memory_queue.py \
  tests/test_memory_queue_user_isolation.py \
  tests/test_memory_updater.py \
  tests/test_memory_updater_user_isolation.py \
  tests/test_cross_user_thread_cleanup.py \
  tests/test_memory_storage_backends_config.py
```

Result: **65 passed**

That proves the code batch is internally runnable.

It does **not** prove the PR is correctly scoped relative to the already-frozen upstream memory-storage batch.

---

## 5. Recommended upstream path

### 5.1 Immediate recommendation

Treat the current memory pipeline as a **proposal/pattern track first**, not as a final accepted code PR shape.

This document should be used to explain to maintainers:

- what the pipeline does
- why it matters for multi-user / multi-instance memory consistency
- why its current coupling makes it hard to slice cleanly
- why a later code PR must first isolate a narrower reusable capability boundary

### 5.2 Later code PR criteria

Any future code PR for this track should satisfy **all** of the following:

1. It does **not** redefine or overlap the frozen PR#2434 storage contract.
2. It isolates a single review axis smaller than the current whole pipeline.
3. It can be explained without requiring reviewers to reason about the entire memory subsystem at once.
4. It comes with targeted tests proving the isolated capability in question.

### 5.3 Candidate future split directions

Possible later code-facing slices include:

- queue/user-isolation hardening only
- summarization flush hook only
- message preprocessing / upload filtering only
- memory cleanup semantics only

These are examples of narrower review axes, not yet committed recommendations.

---

## 6. Why this proposal still matters even if code already exists

The memory pipeline is one of the strongest practical capabilities in the `meitu/develop` fork.

The right corrective move is therefore **not** to abandon it, but to:

- preserve its value,
- explain its shape,
- and keep it moving on an upstream-friendly path without continuing the boundary mistake of `#2456`.

This document is that corrective bridge.

---

## 7. Summary

- The memory pipeline is **real** and **valuable**.
- The current code batch behind `#2456` is **runnable**, but **not cleanly scoped** against frozen PR#2434.
- The best immediate path is a **docs/pattern proposal**, followed by a later narrower code PR once a smaller reusable subset is isolated.
