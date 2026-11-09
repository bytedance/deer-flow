# DeerFlow Offline Memory vs. Project Context Comparison Benchmark

**Issue**: bytedance/deer-flow#7884 (Release Smoke Matrix)  
**Slice**: Offline memory vs. project-context comparison (PR First Pass)

This benchmark suite implements deterministic, offline regression verification for the boundary between long-term memory (DeerMem) and run-level project context (instructions and document shelf).

## Core Verification Checks

1. **Scope Isolation across Unrelated Threads**:
   - Asserts strict boundary between project-scoped context (instructions, document shelf) and user/agent memory facts across unrelated threads.
   - Guarantees zero cross-thread crosstalk and zero project constraint contamination into global memory.
2. **Instant Deletion & Invalidation on Next Turn**:
   - Simulates multi-turn lifecycle replay: verifies that deleted or replaced facts (`factsToRemove`) are completely purged from prompt assembly on the very next turn.
   - Enforces zero stale prompt injection (`stale_prompt_injection_rate == 0.0`).
3. **Per-turn Prompt Token Overhead Measurement**:
   - Fine-grained breakdown and measurement of token overhead across each context layer:
     - User facts (global user preferences & facts)
     - Agent-scoped facts (agent-specific instructions & constraints)
     - Project instructions (`<project>` block)
     - Document shelf index (`<documents>` block)
   - Outputs clear layer aggregates and percentage breakdowns.

## Usage

From `backend/`:

```bash
# 1. Validate synthetic fixture contract
python -m scripts.benchmark.context_memory_comparison validate

# 2. Run deterministic offline benchmark
python -m scripts.benchmark.context_memory_comparison run-offline --output-dir scripts/benchmark/context_memory_comparison/runs/offline-v1

# 3. Generate summary report
python -m scripts.benchmark.context_memory_comparison report --output-dir scripts/benchmark/context_memory_comparison/runs/offline-v1
```

## Reproducibility & Security

- **Strict Offline Mode**: Pinned synthetic fixtures with canary assertions. Zero online network calls, zero provider credential leakage.
- **Self-Authenticating Row Hashes**: Rows are sealed with `result_sha256` and bound to source revision and manifest sha256. Tampered rows are rejected.
- **Idempotent Resumption**: Re-running an existing output directory safely reuses valid, un-tampered rows.
