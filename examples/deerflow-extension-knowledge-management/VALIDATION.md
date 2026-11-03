# Stage 2 acceptance record

Date: 2026-10-22. Base revision: `29ba806fc`, plus this uncommitted
knowledge-management extension and tests. All ingested documents were synthetic.
This records the first Stage 2 management slice, not completion of the whole
knowledge-platform roadmap.

## Real environment

- macOS with OrbStack; authenticated DeerFlow Gateway, Next.js and nginx.
- WeKnora `v0.8.3` (adapter source pin
  `3e22822c1d2397be730c458c7539d0eb8c113a24`), ParadeDB/PostgreSQL 17, Redis.
- Official WeKnora DocReader `v0.8.3`; Neo4j `2025.10.1` with APOC.
- GLM-5.3 using the operator's `.env.local` endpoint/credentials; DeerFlow
  acceptance model used `chat_template_kwargs.enable_thinking=false`.
- Local Ollama BGE-M3, 1024-dimensional vectors (actual embedding request checked).
- LightRAG `v1.5.7` with an existing synthetic graph for retrieval regression.
- Separate restricted management and retrieval keys; exact administrator/base
  grants. Authentication and CSRF remained enabled.

Private configuration, credentials, scripts, complete logs and screenshots remain
outside the repository in the local `knowledge-phase2-local` evidence directory.
No credential values or private model URLs are part of this report.

## Observed outcomes

| Check | Actual outcome |
| --- | --- |
| Manual text ingestion | `202`, then completed/searchable; unique marker retrieved from the selected document |
| Markdown file ingestion | `202`, then completed/searchable |
| URL ingestion | Initial DocReader failure; explicit reprocessing completed after the environment repair below |
| Capability discovery | Plain document and Wiki/graph-enabled bases advertised different optional capabilities |
| Cancel and explicit recovery | Cancellation returned `202`; cancelled/not searchable observed; explicit reprocess returned `202`, then completed with graph and Wiki spans done |
| Graph extraction/indexing | Graph span done; Neo4j contained two actual relations for the synthetic project; entity node chunk IDs resolved to the original source text |
| Wiki generation | Published entity/project/organization/summary pages and Index observed; exact keyword retrieval returned attributable evidence |
| Browser GLM question | One base/one document selected; correct allowance, deadline and synthetic marker, with clickable source text |
| Citation persistence | Source opened after refresh and after Gateway restart; prior answer and source excerpt persisted |
| API live regression | Management ingestion → selected retrieval → serialized citation replay, plus selected retrieval and Wiki regressions: 3 passed |
| Three-tool GLM regression | Explicit Wiki keyword: 3 passed in 15.64 seconds, including real document/Wiki/LightRAG evidence and citation serialization/forwarding/pruning |

Nine real authorization/input checks passed: anonymous `401`, missing CSRF `403`,
ungranted base `403`, cross-base document `403`, forged identity field `422`,
unsupported graph option `422`, ordinary user `403`, retrieval-only upstream key
write `403`, and upstream outside-base access `403`.

The browser synthetic answer was 735 CNY/night, submission within 12 calendar
days, marker `PHASE2-YEW-735-12`. Graph evidence contained project → leader and
organization → project relationships. Node provenance was checked; the upstream
edges had no direct chunk properties. This is not proof of edge-specific
provenance, arbitrary graph quality or multi-hop reasoning.

## Failures and environment repairs

The existing local stack lacked DocReader and Neo4j. URL ingestion initially
reported `DOCREADER_UNAVAILABLE`. Official DocReader and Neo4j were added only
to the private Compose configuration, without publishing their ports. Reparse
then exposed missing APOC functions; installing the official APOC plugin allowed
explicit reconciliation/reprocessing to succeed. The local DNS returned Fake-IP
addresses, requiring exact upstream SSRF allowlist entries for the model host
and the synthetic URL host. No broad SSRF bypass was added.

Free-form three-tool model runs failed the Wiki evidence assertion (two checks
passed, one failed). Diagnostic tool calls showed the query
`紫杉研发项目负责人 资助组织`. WeKnora's Wiki endpoint is lexical; neither that
phrase nor its whitespace-separated terms matched the published page titles.
A subsequent prompt explicitly requesting the keyword `紫杉` passed all three
checks. The fixed-keyword result establishes integration, not unrestricted
natural-language Wiki recall. No retrieval assertion was removed or weakened.

One pipeline document remained `finalizing`/searchable during an additional
upstream Wiki update after publishing pages. Final inspection confirmed
`completed`, with chunking, embedding, graph and both Wiki update spans done.
The separate cancellation recovery case also reached `completed` with all
relevant spans done. The intermediate searchable state was not treated as
terminal completion.

## Offline regression and reproduction

Before live acceptance, the full backend suite passed 35,467 tests across four
shards (796 skipped); strict blocking-I/O coverage passed 276 tests (one skipped).
The extension's focused contract and blocking-I/O tests passed 46 checks.
The final focused run including agent-guidance checks passed 60 tests, with the
non-opted-in live test skipped. Ruff lint/format and package wheel building passed. Live acceptance added a
separately gated test; it does not alter normal offline test behavior.

See [README.md](README.md#opt-in-live-regression) for the live environment variables
and command. That test deliberately writes one unique synthetic document per run,
retains its ID and does not automatically retry or delete it. Browser acceptance
requires selecting the resulting document in the existing chat scope selector,
asking a question unique to the fixture, opening its source, refreshing, then
restarting Gateway and opening the persisted source again. Wiki/graph acceptance
must additionally inspect the upstream spans, published pages and actual graph
records; document parse completion alone is insufficient.

Out of scope: a management frontend, platform spaces/sharing, arbitrary parser or
model configuration, Trace persistence, standalone Wiki editing, upstream user
impersonation, multi-Gateway ingestion admission and exactly-once writes.

## PR review follow-up

Review regressions now reject parent-child chunk overrides on manual, URL, file
and reprocess paths before any upstream mutation; empty and non-chunk overrides
remain supported. All four rejection cases failed before the fix and passed
afterward. The oversized-upload case has a compact explicit pytest ID, avoiding
Windows environment-variable limits (native Windows was not rerun locally).
Frontend discovery includes the package's actual namespace and localized copy.
Focused backend/guidance checks: 64 passed, 1 skipped. Frontend catalog: 9 passed;
frontend lint/typecheck and backend formatting passed.

Further review: capabilities now omit unsupported per-base controls, and invalid
local credentials return a distinct pre-request 503. Seven new cases failed
before the fix; focused backend/guidance checks now pass 77 tests (1 live skip).
The three failing CI catalog E2E cases used the obsolete fixed count 11; they
now use the catalog length plus explicit localized management-entry assertions.
All three pass locally against an isolated Next.js development server. Catalog
unit tests (9), frontend lint/typecheck and backend formatting also pass.
