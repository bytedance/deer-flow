# Evaluating generated search queries

The [search query benchmark](../scripts/benchmark/search_query/README.md) compares
the lead agent's first web-search query with the human references associated
with the same dataset backstory. It reports semantic and lexical similarity.
Human baselines and retrieval effectiveness are outside this evaluation.

Datasets are caller-supplied and are not distributed with the benchmark. Supply
`--dataset`, its `--dataset-sha256`, and an immutable `--dataset-revision`; the
runner verifies the CSV hash and records the revision in run provenance. The
benchmark README documents the pinned UQV100 source, license metadata and
reproducible five-reference derivation. Keep source files and derived CSVs
outside the repository; offline tests use synthetic fixtures only.

Capture resumes preparatory tool batches on a fresh thread and stops before
executing the first batch containing `web_search`. Subagents are disabled so
delegated searches cannot bypass this breakpoint. A configurable checkpoint
budget bounds preparation; direct answers and exhausted budgets remain visible
as unscored outcomes alongside coverage.

Each run saves its evaluation configuration, deployment artifact hashes and
per-case Gateway assembly evidence. Supply the running Gateway's revision and
retain the original deployment snapshots privately. The local Git revision
identifies the runner only. Host evidence supplies effective sampling parameters
and fingerprints; its keyed fingerprints are comparable within a worker
lifetime. Retained artifact hashes identify deployments across restarts.
Runtime files contain human/system context, including recalled memory and dates,
and belong in ignored local directories. See the benchmark README for commands,
required token scopes, output schemas and reproduction limits.
