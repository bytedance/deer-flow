---
name: deerflow-maintainer-orchestrator
description: "Use when a DeerFlow maintainer needs comment-only GitHub issue or PR handling: resolve issue/PR scopes with gh, analyze issues, post or draft issue comments, perform PR review comments, review PR or issue batches, compare competing PRs that target the same issue, give fix strategy, risk classification, and validation guidance. Intended for maintainers and trusted local agents, not general contributors."
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
11. When an issue has more than one candidate resolving PR, gather them all before reviewing: the issue's linked/Development PRs, closing keywords (`Closes/Fixes #<issue>`) found via `gh api` timeline cross-reference events, and PRs that mention the issue. Route them into Competing PR Comparison.
12. If no artifact type, number, URL, count, time window, or searchable GitHub scope can be resolved, stop with a compact "scope unresolved" report. Do not ask a follow-up question.

Use concise repo-local references such as `#123` and `PR #123` in maintainer reports and comments. Include full GitHub URLs only for posted comment/review links returned by GitHub or when the maintainer supplied an explicit URL.

## Existing Coverage and Re-Runs

Existing comments suppress duplicate **posting**, not **analysis**. Always analyze the artifact in full, then post only the net-new delta over what is already covered.

1. Read existing maintainer/trusted-agent comments and reviews as prior coverage.
2. Analyze the artifact fully regardless of what already exists. A prior comment may be partial — catching A while missing B.
3. Keep only net-new, high-confidence items not already materially covered.
4. Non-empty delta: post one comment that explicitly builds on the prior coverage (for example `Adding to @reviewer's review:`) and states only the new items. Do not restate covered points.
5. Empty delta: post nothing public; report `Already covered` to the maintainer with the existing comment/review URL.
6. Idempotency: treat your own earlier skill-authored comments as already-covered. On a re-run, never stack a second comment that repeats an earlier one — post only genuinely new delta, or nothing.

RFC issues are the one hard skip: no analysis and no post unless the maintainer overrides.

## Issue Flow

Use Issue Flow for GitHub issues, bug reports, feature requests, support questions, and issue batches.

Start every issue with a cheap precheck:

1. Fetch issue metadata, labels, author, body, and existing comments.
2. If labels, title, or body mark the issue as RFC (`rfc`, `[RFC]`, `RFC:`, or `Request for Comments`), classify it as `rfc-no-comment`, skip deep analysis, and do not post anything public unless the maintainer explicitly overrides the RFC skip for that item.
3. Existing maintainer or trusted-agent comments are prior coverage, not an automatic skip. Analyze fully and post only the net-new delta (see Existing Coverage and Re-Runs).
4. Treat ordinary reporter replies, thanks, unrelated discussion, or incomplete guesses as non-blocking.
5. Report already-covered or skipped issues to the maintainer only as compact identifiers plus the reason or existing comment URL when available.

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
5. Immediately before posting, refresh comments; fold any equivalent comment that appeared during analysis into prior coverage and post only the remaining delta.
6. Post one issue comment when posting is authorized; otherwise return the same text as `Reply draft`.

Do not expose private reasoning, credentials, internal-only context, or unsupported promises. Do not say a fix was made unless a separate coding workflow actually changed code.

## PR Review Flow

Use PR Review Flow for GitHub pull requests and PR batches.

Start every PR with a cheap precheck:

1. Fetch PR metadata, changed file list, checks summary, existing PR reviews, existing PR comments, and review threads when available.
2. Existing maintainer or trusted-agent reviews are prior coverage, not an automatic skip. Review fully and post only the net-new delta (see Existing Coverage and Re-Runs).
3. Read `statusCheckRollup` as signal, not verdict. Failing required checks are themselves a reportable finding (build failure = P0; failing tests or lint = P1/P2 by impact). Green checks lower risk but never excuse reading the actual changed code path — confirm suspect logic by reading the source, not by trusting green CI. Tests passing does not prove the changed branch is exercised.
4. Treat author replies, thanks, unrelated discussion, or incomplete guesses as non-blocking.
5. Report already-covered or clean PRs to the maintainer only, with the existing review/comment URL when available.

### Diff Base Rule

Before reviewing a local PR branch or local diff, fetch the base repository's target branch and compare against that fresh remote-tracking ref, not a possibly stale local `main`.

- For fork checkouts, prefer `upstream/<base-branch>` when `upstream` points to the base repository.
- For direct upstream checkouts, use the base remote's fetched branch, usually `origin/<base-branch>`.
- Prefer GitHub PR base metadata for the target branch. For non-PR local diffs, use the base repository default branch. If metadata is unavailable, default to `main` only after fetching the base remote.
- Refresh the comparison ref explicitly, for example `git fetch <base-remote> +refs/heads/<base-branch>:refs/remotes/<base-remote>/<base-branch>`, then inspect `BASE=$(git merge-base HEAD <base-remote>/<base-branch>)` and `git diff "$BASE"...HEAD`.
- If using `FETCH_HEAD` from a single-branch fetch instead, diff against that verified `FETCH_HEAD` immediately and do not later substitute a possibly stale remote-tracking ref.
- Resolve the PR head explicitly. For fork PRs whose head branch is not on the base repo, fetch the PR ref: `git fetch <base-remote> pull/<n>/head:pr-<n>`. The fork's own branch ref and `gh api .../contents?ref=<fork-branch>` will 404 against the base repo. Record the head SHA you reviewed.
- Re-check the head SHA immediately before posting. If the PR head moved during analysis, re-review the new diff or abort — never post a review against a diff the PR no longer has.
- For uncommitted local changes, review committed branch changes against the fresh base first, then include working-tree changes separately.
- If the base remote or base branch cannot be established, use the GitHub PR files/diff as the source of truth. If neither local nor GitHub diff can be read, return a compact failure report and do not post a review.

Before posting a PR review comment:

1. Review only the current diff against the fresh base and changed files. Do not comment on unrelated pre-existing code unless the diff makes it newly risky.
2. Do not report low-confidence guesses. If evidence is insufficient, omit the finding.
3. Prioritize correctness, safety, maintainability, production risk, compatibility, and missing critical tests over style.
4. Report concrete architecture, security, public API, default-behavior, and compatibility problems as findings when the diff causes or exposes them.
5. Check changed behavior, edge cases, error paths, state mutation, transactions, locks, cache invalidation, cleanup, security boundaries, missing tests, performance/reliability, and API compatibility.
6. Immediately before posting, refresh reviews/comments and fold any equivalent review that appeared during analysis into prior coverage; post only the remaining delta.
7. Apply the Posting Gate. If the gate yields public findings, post one PR review comment in the PR language. Otherwise post nothing public and report the result (`No high-confidence review findings.` or `Already covered`) plus any sub-threshold items as `Maintainer notes`.

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

### Posting Gate

Posting depends on BOTH confidence (is the problem real?) and severity (how bad if real). They are independent axes — "no high-confidence findings" means none across P0/P1/P2, not merely "no P0".

- Post publicly only items that are high-confidence AND at least P2.
- For a public P2, additionally require that the diff itself introduces or worsens the issue. Do not raise a public P2 for pre-existing behavior the diff only touches, or for a change that is a net improvement over the prior state.
- A high-confidence P0/P1 is always worth posting. A low-confidence P1 is not — omit it, or route it to `Maintainer notes` framed as a hypothesis to verify.
- Sub-threshold but real observations (net-improvement nits, bounded or low-risk concerns, pre-existing issues, low-confidence hypotheses) go to the `Maintainer notes` channel in the run result, never to a public comment.

Do not produce compliments, summaries, or general advice. For sensitive security issues, describe impact and remediation without exploit instructions.

## Batch Handling

When the scope has multiple artifacts, cluster before reviewing and synthesize after.

Cluster by relatedness, not by type. Group artifacts that share files, interfaces, or the same issue/feature into one cluster; same-type artifacts that touch disjoint files are independent.

- Related cluster: review in ONE shared context so cross-artifact reasoning is possible — parallel agents cannot see each other's findings. If it cannot fit one context, fan out per sub-group and reconcile in the synthesis pass; never split it blind, without that re-aggregation.
- Independent clusters: may run in parallel. Offloading a large or independent batch to one subagent per cluster keeps the main context clean — consider it for big batches, prefer offering it to the maintainer over silently spawning, and do not spawn for two or three related items or when the cold-start cost is not earned.

After per-artifact review, run one synthesis pass over the whole batch and report it to the maintainer (decision-support, not a public comment):

- Overlapping files and merge-order/conflict surface — which PRs touch the same files and will conflict pairwise.
- Duplicate or competing solutions to the same problem.
- Composition risk — changes each safe alone but interacting (for example, two PRs editing the same module or table).

## Competing PR Comparison

When several PRs target the same issue, compare them instead of reviewing each in isolation.

1. Pull the issue's acceptance criteria (reported problem and expected behavior); that is the rubric anchor.
2. Score each PR on: does it actually resolve the issue's ask; correctness and edge/error-path coverage; test quality; blast radius and compatibility; maintainability. Use the same DeerFlow Review Heuristics and Posting Gate as a single review.
3. Report a maintainer-facing comparison — strongest PR and why, what each is missing — in the run result.
4. Keep the public surface constructive and per-PR: post each PR's own gate-passing findings normally. Do not publicly rank PRs against each other or tell an author their PR is worse than a competitor's; winner selection stays in the maintainer report.

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
Already covered:
Failed:
Maintainer notes:
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
Already covered:
Failed:
Maintainer notes:
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
| #321 | already covered | none | existing maintainer comment |
```

For multi-artifact batches, follow the table with a `Batch synthesis` block (overlapping files, merge-order/conflict surface, duplicate or competing solutions, composition risk) and, when issues had competing PRs, a `Competing PR comparison` block. Both are maintainer-only.

Omit empty categories, no-op fields, routine command output, and raw logs. Report meaningful changes, evidence, and options.
