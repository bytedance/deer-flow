# Conversation Sharing

Backend/API groundwork for #4548, disabled by default and SQL-only. The Share
dialog and public `/share/{token}` page remain a separate frontend phase.

Before changing sharing behavior, read the detailed
[security and delivery contract](../../../docs/CONVERSATION_SHARING.md).
It preserves the ownership, rendering, normalization, token, deployment and
logging decisions from this guide; do not weaken them to simplify a fix.

## Required invariants

- Create requires an existing thread row strictly owned by the caller. Legacy
  NULL-owner rows cannot be published. List/revoke scope by the share record's
  owner, so deleting/recreating a thread never transfers its shares.
- Public GET reads only the share record, never thread state or history. Unknown,
  revoked and expired links share one 404. Only GET is auth-exempt; reserve the
  namespace against extension routes. Share management requires `threads:read`, including for PAT callers.
- Create and public re-read rebuild allowlisted DTOs with snapshot-local ids.
  Assistant reasoning/tool metadata never passes through. User text is not
  assistant reasoning. Strip assistant `<think>` outside genuine Markdown code,
  then neutralize owner-only paths in both text and titles.
- Code protection is document-scoped. At the first possible quote/list line
  (empty markers included), discard the pending paragraph and stop granting
  protection through EOF, also in reference-definition regions. Do not guess
  container boundaries or re-pair ticks: this can create false code spans.
  Earlier emitted code and already-open root code blocks stay protected;
  literal examples in the pending paragraph or later may be over-stripped.
  Possible reference definitions and their nonblank continuations also stay
  unprotected; a skipped fence/HTML/math opener extends that policy to EOF.
- Private-path detection uses bounded normalized shadows; edits use original
  offsets, preserving public text. Retain sparse maps and linear/bounded scans.
  Never build per-character maps for an unchanged multi-megabyte message.
- Backward pages arrive newest-first with ascending rows: reverse page order
  only. Reject over-limit shares with 413, never truncate: 2000 public messages,
  2 MiB rendered UTF-8 bytes, and 50k raw scanned rows inside the canonical pager.
- Owner quotas count all stored rows and admit atomically using the SQL counter
  (`0028_conversation_share_quotas`). Pre-checks alone cannot enforce the limit.
- Store only HMAC-SHA-256 token digests. Return the random bearer once. Pepper
  creation is atomic, complete-length checked, 0600, and offloaded from async
  routes. Multi-replica deployments need a common `SHARE_TOKEN_PEPPER`.
- Public responses use no-store, no-referrer and frame-ancestors none. Resolve
  throttling uses trusted-proxy client IPs, remains process-local, and is not
  the ownership boundary. Preserve Helm ingress isolation and its proxy rules.
- Preserve share-token masking in Gateway text/JSON messages, tracebacks and
  trace ids; uvicorn logger AND handler coverage; all three nginx configs;
  and support-bundle final writers. URL redaction and share-token redaction must
  both remain installed. Keep non-retaining nginx error sinks and the documented
  pre-location error-log residual in the detailed contract.

## Verification

Use red-first regressions at creation and public re-read. Pair leak cases with
public passthrough/code-example controls, and use the frontend's actual Markdown
renderer for disputed boundaries. Pin intentional over-stripping as policy.

Run sharing/router/repository/token/logging/migration/config tests, the offline
backend suite and blocking-I/O gate, Ruff, guidance-size check, and relevant Helm
renders. Reparent unmerged sharing migrations after the latest upstream revision;
retain one Alembic head, upgrade/downgrade/retry tests and forward-compatibility
coverage. Bump config_version past upstream and synchronize Helm defaults.
