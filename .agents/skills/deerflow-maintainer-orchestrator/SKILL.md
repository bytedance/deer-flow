---
name: deerflow-maintainer-orchestrator
description: "Use when a DeerFlow maintainer needs comment-only GitHub issue or PR handling: resolve issue/PR scopes with gh, analyze issues, post or draft issue comments, perform PR review comments, give fix strategy, risk classification, and validation guidance. Intended for maintainers and trusted local agents, not general contributors."
---

# DeerFlow Maintainer Orchestrator

## Core Rule

This is a comment-plane skill: resolve GitHub scope, inspect evidence, and prepare or post DeerFlow issue comments and PR review comments. Keep the work comment-scoped; do not turn it into coding, branch management, release work, artifact closure, or other maintainer operations.

When the maintainer asks to process, handle, comment on, or review a bounded set of issues or PRs, proceed without asking follow-up questions. Treat that request as authorization for one public issue comment per selected non-skipped issue and one PR review comment per selected PR with high-confidence findings. If a PR has no high-confidence findings, do not post a public comment; report that result to the maintainer only. If the maintainer explicitly asks for analysis only, return comment-ready drafts without posting.

The maintainer's normal interaction should be: provide scope; receive posted comment URLs, PR review URLs, clean results, skipped items, failures, or drafts. Do not offload technical analysis to the maintainer. Make the best evidence-backed recommendation in the comment itself: describe the risk, impact, likely fix, and validation path. Ask the reporter or PR author for missing evidence only when the artifact lacks enough data to diagnose.

Output only the maintainer run result or comment draft. Do not announce the skill name, mode, or that no code was edited unless the user asks for process details.

Match the dominant language of the issue or PR unless the maintainer asks for another language. Chinese issue or PR text gets Chinese output; English issue or PR text gets English output. For mixed artifacts, use the body language, not logs or code.

## Artifact Resolution

Use GitHub tooling to resolve artifact type and scope. Do not ask the maintainer to clarify when `gh` or GitHub API can determine the answer.

1. Default repository is `bytedance/deer-flow` unless a URL or explicit repo says otherwise.
2. For URLs, route `/issues/<number>` to Issue Flow and `/pull/<number>` to PR Review Flow.
3. For typed numbers, use the typed command:
   - Issue: `gh issue view <number> --repo <repo> --json number,title,url,state,body,labels,author,comments`
   - PR: `gh pr view <number> --repo <repo> --json number,title,url,state,body,author,files,comments,reviews,statusCheckRollup,baseRefName,headRefName`
4. Normalize multiple explicit references such as `#123`, `# 123`, and bare `123` into a number list, preserving order and de-duplicating exact repeats.
5. For untyped numbers, try `gh pr view <number> --repo <repo> --json number,url` first. If it fails, use `gh issue view <number> --repo <repo> --json number,url`. Do not ask which type it is.
6. For issue batches, use `gh issue list`, not the mixed GitHub issues endpoint. For PR batches, use `gh pr list`.
7. Respect maintainer-provided count or time window. There is no hard five-item cap. If the scope is broad and underspecified, choose a practical recent slice, state the slice used, prioritize newest and highest-risk items, and report any unprocessed remainder.
8. For "recent/latest" wording without a count, use a small default recent slice. For "recent hours" wording without a number, use six hours. Do not ask.
9. Use `gh api` when `gh issue/pr view/list` lacks required fields such as timeline events, review threads, or precise search filters.
10. Use GitHub search only as a fallback for natural-language filters that cannot be represented by view/list/API calls. Do not use web search for artifact routing unless GitHub tooling is unavailable.
11. If no artifact type, number, URL, count, time window, or searchable GitHub scope can be resolved, stop with a compact "scope unresolved" report. Do not ask a follow-up question.

Use concise repo-local references such as `#123` and `PR #123` in maintainer reports and comments. Include full GitHub URLs only for posted comment/review links returned by GitHub or when the maintainer supplied an explicit URL.

## Issue Flow

Use Issue Flow for GitHub issues, bug reports, feature requests, support questions, and issue batches.

Start every issue with a cheap duplicate-opinion precheck:

1. Fetch issue metadata, labels, author, body, and existing comments.
2. If labels, title, or body mark the issue as RFC (`rfc`, `[RFC]`, `RFC:`, or `Request for Comments`), classify it as `rfc-no-comment`, skip deep analysis, and do not post anything public unless the maintainer explicitly overrides the RFC skip for that item.
3. If an existing maintainer or trusted-agent issue comment already gives a materially equivalent diagnosis, modification suggestion, information request, or blocking decision, skip deep analysis and do not post anything public for that issue.
4. Treat ordinary reporter replies, thanks, unrelated discussion, or incomplete guesses as non-blocking.
5. Report skipped issues to the maintainer only as compact identifiers plus the skipped reason or existing comment URL when available.

For non-skipped issues:

1. Read enough context to avoid guessing: issue body, comments, screenshots, logs, reproduction details, linked artifacts, and relevant DeerFlow code/docs.
2. Classify the surface:
   - Frontend UI
   - Backend API
   - Agents / LangGraph
   - Sandbox
   - Skills
   - MCP
   - Dependencies
   - Default behavior
   - Docs / tests / CI only
3. Classify actionability:
   - `ready-to-fix`: bounded, evidence sufficient, validation path clear.
   - `needs-more-evidence`: repro, logs, environment, screenshots, exact expected behavior, or failing case missing.
   - `defer-or-close`: duplicate, stale, unsupported, unactionable, or out of scope.
   - `rfc-no-comment`: RFC issue; skip public comments by default.
4. Produce a public-safe comment from the analysis, not the analysis labels:
   - Start with one natural opener that connects to the issue context. Prefer `Thanks @author.` for reporter-authored issues when it reads naturally; omit the mention for bots, maintainer-authored tracking issues, or cases where it would add noise.
   - The opener must say something specific about the next step or boundary, not a generic assessment. Do not use generic phrases such as "This is actionable", "I would treat this as", "ready to fix", or surface/actionability/risk labels.
   - Use the smallest stable template that fits:

```text
Thanks @author. <one specific sentence that frames the fix, investigation, or missing evidence.>

Recommended solution:
- ...

Validation:
- ...
```

   - Add `Evidence:` only when citing concrete code, logs, reproduction details, or other proof helps the author act.
   - Add `Risk:` only when architecture, security, public API, default behavior, or compatibility impact must be called out explicitly; make the risk specific.
   - Add `Missing info:` only when the issue cannot be diagnosed without more evidence; ask for the smallest useful data.
   - Put relevant files/components inside `Evidence:` or `Recommended solution:` bullets instead of separate metadata fields.
   - Every posted issue comment should contain concrete modification guidance and validation guidance unless the only useful response is `Missing info:`.
5. Immediately before posting, refresh comments and skip if an equivalent maintainer or trusted-agent comment appeared during analysis.
6. Post one issue comment when posting is authorized; otherwise return the same text as `Reply draft`.

Do not expose private reasoning, credentials, internal-only context, or unsupported promises. Do not say a fix was made unless a separate coding workflow actually changed code.

## PR Review Flow

Use PR Review Flow for GitHub pull requests and PR batches.

Start every PR with a cheap duplicate-review precheck:

1. Fetch PR metadata, changed file list, checks summary, existing PR reviews, existing PR comments, and review threads when available.
2. If an existing maintainer or trusted-agent review already gives materially equivalent findings or a blocking decision, skip deep review and do not post anything public for that PR.
3. Treat author replies, thanks, unrelated discussion, or incomplete guesses as non-blocking.
4. Report skipped PRs to the maintainer only as compact identifiers plus the existing review/comment URL when available.

### Diff Base Rule

Before reviewing a local PR branch or local diff, fetch the base repository's target branch and compare against that fresh remote-tracking ref, not a possibly stale local `main`.

- For fork checkouts, prefer `upstream/<base-branch>` when `upstream` points to the base repository.
- For direct upstream checkouts, use the base remote's fetched branch, usually `origin/<base-branch>`.
- Prefer GitHub PR base metadata for the target branch. For non-PR local diffs, use the base repository default branch. If metadata is unavailable, default to `main` only after fetching the base remote.
- Refresh the comparison ref explicitly, for example `git fetch <base-remote> +refs/heads/<base-branch>:refs/remotes/<base-remote>/<base-branch>`, then inspect `BASE=$(git merge-base HEAD <base-remote>/<base-branch>)` and `git diff "$BASE"...HEAD`.
- If using `FETCH_HEAD` from a single-branch fetch instead, diff against that verified `FETCH_HEAD` immediately and do not later substitute a possibly stale remote-tracking ref.
- For uncommitted local changes, review committed branch changes against the fresh base first, then include working-tree changes separately.
- If the base remote or base branch cannot be established, use the GitHub PR files/diff as the source of truth. If neither local nor GitHub diff can be read, return a compact failure report and do not post a review.

Before posting a PR review comment:

1. Review only the current diff against the fresh base and changed files. Do not comment on unrelated pre-existing code unless the diff makes it newly risky.
2. Do not report low-confidence guesses. If evidence is insufficient, omit the finding.
3. Prioritize correctness, safety, maintainability, production risk, compatibility, and missing critical tests over style.
4. Report concrete architecture, security, public API, default-behavior, and compatibility problems as findings when the diff causes or exposes them.
5. Check changed behavior, edge cases, error paths, state mutation, transactions, locks, cache invalidation, cleanup, security boundaries, missing tests, performance/reliability, and API compatibility.
6. Immediately before posting, refresh reviews/comments and skip if an equivalent maintainer or trusted-agent review appeared during analysis.
7. If there are high-confidence findings, post a PR review comment using the PR language. If there are no high-confidence findings, do not post a public PR review/comment; report `No high-confidence review findings.` to the maintainer in the run result.

For public PR reviews with findings, start with one short opener that fits the review context and matches the finding count. Use singular wording only for exactly one finding, for example `Thanks @author. I found one issue that should be addressed before this is ready.` Use plural wording for multiple findings, for example `Thanks @author. I found a few issues that should be addressed before this is ready.` Omit the mention for bots or when it adds noise.

For each finding, use:

```text
[P0/P1/P2] Title

- Location: file and line/range
- Problem: what can go wrong
- Evidence: why the diff causes it
- Suggested fix: concrete minimal fix
- Test: what test should cover it
```

Severity guide:

- `P0`: causes outage, data loss, security breach, or build failure.
- `P1`: likely production bug, serious regression, broken compatibility, or high-risk security/architecture issue.
- `P2`: correctness, maintainability, or test concern with lower risk.

Do not produce compliments, summaries, or general advice. For sensitive security issues, describe impact and remediation without exploit instructions.

## No-Question Policy

Do not ask the maintainer routine clarification questions. The skill should save maintainer time by turning scope into comments through a fixed workflow.

Stop without asking only when:

- no issue/PR scope can be resolved through URLs, numbers, `gh` view/list, `gh api`, or GitHub search fallback;
- GitHub authentication, repository access, or comment posting fails;
- the requested action is outside comment-only scope;
- posting would require private credentials, private security details, or non-public context.

In these cases, return a compact failure report with the attempted command path and the smallest next action. Do not phrase it as a question unless the maintainer explicitly asked to be prompted.

## DeerFlow Review Heuristics

Treat these as high-signal areas for issue comments and PR findings:

- `backend/packages/harness/deerflow/` must not import `app.*`.
- App may depend on harness; harness must stay publishable and app-agnostic.
- Frontend thread/message behavior and Gateway/LangGraph-compatible SSE are contract surfaces.
- Sandbox permissions, bash/file-write tools, skill installation, and remote execution are security-sensitive.
- Default model/provider behavior, config migration, persistence schema, public API/SSE, and LangGraph thread/run lifecycle are compatibility-sensitive.
- Runtime docs should track user-facing or developer-facing behavior changes.
- Security-sensitive comments should provide proof and remediation, not vague assertions.

## Validation Guidance

Recommend the checks matching the touched surface:

| Surface | Suggested validation |
| --- | --- |
| Backend API / harness / agents / MCP / skills runtime | `cd backend && make lint && make test` |
| Blocking IO or async file/network work | `cd backend && make test-blocking-io` or a focused blocking-IO regression |
| Harness/app boundary | `cd backend && uv run pytest tests/test_harness_boundary.py` |
| Frontend UI/core | `cd frontend && pnpm format && pnpm lint && pnpm typecheck && BETTER_AUTH_SECRET=local-dev-secret pnpm build && make test` |
| Front/back thread or SSE contract | backend replay golden and full-stack replay render where feasible |
| Frontend user workflow | Playwright E2E or browser proof with screenshot/DOM assertion |
| Docker/sandbox/provisioner | focused backend tests plus Docker/provisioner smoke when feasible |
| Docs-only | targeted markdown review |

## Output

For Issue Flow:

```text
Run result:
Posted:
Skipped:
Failed:
Per issue:
  Issue:
  Surface:
  Actionability:
  Risk:
  Comment:
  Validation:
  Comment status:
```

For PR Review Flow:

```text
Run result:
Reviewed:
Skipped:
Clean:
Failed:
Per PR:
  PR:
  Public review:
  Findings:
  Review status:
```

For analysis-only requests, replace `Posted`/`Reviewed` with `Drafted` and include the comment/review text without posting.

For batches, prefer a compact maintainer-facing table after the headline counts:

```text
| Artifact | Status | Public action | Notes |
| --- | --- | --- | --- |
| #123 | posted | comment URL | short reason |
| PR #456 | reviewed | review URL | P1: finding title |
| PR #789 | clean | none | No high-confidence review findings. |
| #321 | skipped | none | existing maintainer comment |
```

Omit empty categories, no-op fields, routine command output, and raw logs. Report meaningful changes, evidence, and options.
