# Local integration validation — 2026-10-15

A real local WeKnora deployment and local Ollama embeddings were exercised on
Apple Silicon macOS. The corpus is explicitly synthetic Chinese text; no
external model API, real customer corpus, or production credentials were used.

## Environment

- WeKnora API/UI: v0.8.3. API runtime reports version `0.8.3`, standard edition,
  Go 1.26.0, linux/arm64, build time 2026-10-14 07:53:47 UTC.
- API image: `wechatopenai/weknora-app:v0.8.3`, multi-platform manifest digest
  `sha256:b5f96b13c2f69779af8c7291264cafbda64c208398b019e3a6223c6f3ea82031`;
  selected arm64 manifest
  `sha256:e9b2f77cbd0edad22a693844d27029a1881718687e77804028f6d3306f7340b1`.
- PostgreSQL/vector retrieval: `paradedb/paradedb:v0.25.11-pg17`;
  task queue: `redis:7.0-alpine`; container runtime: OrbStack.
- Ollama 0.40.4, native macOS; model `bge-m3`, 1024 embedding dimensions,
  model context length 8192, embedding-only capability.
- Model weights: official Ollama `library/bge-m3` model blob, 1,157,671,200
  bytes, verified SHA-256
  `daec91ffb5dd0c27411bd71f29932917c49cf529a641d0168496c3a501e3062c`.
  The machine's Fake-IP DNS made Ollama reject the registry redirect. The
  official blob was downloaded over HTTPS, digest-verified, and imported with
  `ollama create bge-m3`; no redirect guard was disabled.
- All host ports are loopback-bound. Container API calls reach the native
  Ollama service through `host.docker.internal`.

## Corpus and credential setup

Created a dedicated local workspace and document knowledge base through the
WeKnora API. Its embedding model is local `bge-m3`; vector indexing is enabled.
Summary generation, generated questions, graph and Wiki are disabled, so this
fixture does not require a chat or rerank model. Manual Markdown ingestion
uses WeKnora's own processing and embedding pipeline.

Two documents reached `parse_status=completed`, `enable_status=enabled`:

1. Synthetic Cedar travel policy: nightly accommodation cap 680 CNY, submission
   within 15 days, unique marker `CEDAR-680-15`.
2. Synthetic Blue Whale training policy: budget 2400 CNY, report within 7 days,
   unique marker `BLUEWHALE-2400-7`.

The integration key has **only `retrieve` capability**, `full_access=false`,
and an upstream allowlist containing the test base. A second empty base exists
in the same workspace solely to test rejection by that API-key allowlist.
Secrets and local resource IDs are kept outside the repository.

## Observed checks

| Check | Result |
| --- | --- |
| Native Ollama embeds two Chinese strings | Two 1024-dimensional vectors |
| Container reaches native Ollama | Version endpoint succeeds |
| API health / frontend page / frontend-proxied login | HTTP 200 |
| Catalog → selected document → live retrieval → shared evidence | Passed opt-in pytest |
| Actual DeerFlow ToolNode with executing subagent identity | Live evidence returned |
| ToolMessage serialization/replay and parent source forwarding | Valid sources preserved |
| Source pruning after evidence removal | Empty source list |
| Select Cedar document | Cedar marker present; Blue Whale marker absent |
| Select Blue Whale document | Blue Whale marker present; Cedar marker absent |
| All-accessible scope within configured base | Cedar evidence retrieved |
| Unknown document selection | Rejected without unrestricted retry |
| Unbound DeerFlow user | Rejected |
| Restricted API key reads the second base | HTTP 403 |
| Read-only API key attempts a synthetic draft write | HTTP 403; no document created |

The live pytest is `backend/tests/test_weknora_extension_live.py`; it supplies a
deterministic tool call and requires an already indexed document. This tests
real retrieval and tool/artifact integration, **not generative answer quality**.
The separate boundary probes used the two synthetic documents described above.
No interactive DeerFlow browser chat or external provider deployment is claimed.

## Compatibility finding fixed during this run

The initial adapter used `/api/v1/knowledge-search`. With the correctly scoped
read-only key, WeKnora v0.8.3 returned HTTP 403:
`API key scope does not allow knowledge_ids without a verified knowledge base`.
Passing base IDs alongside document IDs is unsafe because that endpoint unions
those targets; granting broader key permissions would also weaken isolation.

The adapter now uses
`POST /api/v1/knowledge-bases/{id}/hybrid-search` with `query_text`, optional
`knowledge_ids`, and `skip_context_enrichment=true`. The path enforces the base
binding and document IDs narrow it. This endpoint supplies raw recall without
requiring a reranker. A failing offline regression was added before the change;
the restricted-key live test and the two-document isolation probes pass after it.

## Regression checks after the compatibility fix

- Full backend offline suite: **31,897 passed** (four duration-balanced shards;
  optional/environment-dependent tests retain their reported skips).
- Strict blocking-I/O suite: **257 passed, 1 skipped**.
- Focused adapter plus its SSL/blocking regression: **40 passed**.
- Opt-in live test against this deployment: **1 passed**, including the real
  ToolNode, replay, forwarding and pruning checks above.
- Ruff lint/format, extension wheel packaging and agent-guidance checks passed.
