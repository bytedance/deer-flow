# DeerFlow Maintainer Orchestrator SOP

This SOP defines how DeerFlow maintainers should use the repository-local `deerflow-maintainer-orchestrator` skill for comment-only GitHub issue handling and PR review.

The goal is practical automation: the maintainer provides an issue or PR scope, and the agent resolves the artifacts with GitHub tools, analyzes DeerFlow context, and posts or drafts useful comments. The skill should not turn routine judgment into maintainer questions or offload technical analysis back to the maintainer.

The local skill lives at `.agent/skills/deerflow-maintainer-orchestrator/SKILL.md`.

## Scope

- **Issue Flow** analyzes GitHub issues and posts or drafts issue comments.
- **PR Review Flow** reviews GitHub pull request diffs and posts or drafts PR review comments.
- **Batch Handling** clusters multiple artifacts and synthesizes cross-artifact interactions.
- **Competing PR Comparison** compares several PRs that target the same issue.
- The skill is a comment-plane workflow. It does not implement code changes, manage branches, close artifacts, publish releases, or perform non-comment maintainer actions.

## Comment Authorization

When the maintainer asks to process, handle, comment on, or review a bounded set of issues or PRs, the skill may post one public issue comment per selected non-skipped issue and one PR review comment per selected PR with high-confidence findings.

If a PR has no high-confidence findings, the skill should not post a public review/comment. It should report that clean result to the maintainer only.

When the maintainer explicitly asks for analysis only, the skill should return comment-ready drafts without posting.

Sub-threshold observations that are real but below the public bar go to a maintainer-only notes channel in the run result, never to a public comment.

The maintainer's normal interaction should be: provide scope; receive posted comment URLs, PR review URLs, clean results, already-covered results, skipped items, failures, maintainer notes, or drafts.

The skill should not announce its own name, mode, or "no code edited" status in normal output. Those are process details, not maintainer signal.

## Language

The output language should match the issue or PR language unless the maintainer asks otherwise. Chinese issues/PRs get Chinese analysis and comments; English issues/PRs get English analysis and comments. Logs, stack traces, and code snippets do not determine the response language.

## Artifact Resolution

The skill should resolve issue/PR scope through GitHub tools before considering any clarification.

1. Default repository: `bytedance/deer-flow`, unless a URL or explicit repo says otherwise.
2. URLs route directly: `/issues/<number>` uses Issue Flow; `/pull/<number>` uses PR Review Flow.
3. Typed numbers use typed commands:
   - Issue: `gh issue view <number> --repo <repo> --json number,title,url,state,body,labels,author,comments`
   - PR: `gh pr view <number> --repo <repo> --json number,title,url,state,body,author,files,comments,reviews,statusCheckRollup,baseRefName,headRefName`
4. Normalize multiple explicit references such as `#123`, `# 123`, and bare `123` into a number list, preserving order and de-duplicating exact repeats.
5. Untyped numbers are resolved by trying `gh pr view <number>` first, then `gh issue view <number>`.
6. Issue batches use `gh issue list`; PR batches use `gh pr list`. Do not use a mixed issue endpoint as the source for both queues.
7. Respect the maintainer's requested count or time window. There is no hard five-item cap.
8. If the scope is broad and underspecified, choose a practical recent slice, state the slice used, prioritize newest and highest-risk items, and report unprocessed remainder.
9. Use `gh api` when view/list commands lack fields such as review threads or precise filters.
10. Use GitHub search only as a fallback for natural-language filters that cannot be represented by view/list/API calls.
11. When an issue has more than one candidate resolving PR, gather them all before reviewing — the issue's linked/Development PRs, closing keywords (`Closes/Fixes #<issue>`) found via `gh api` timeline cross-reference events, and PRs that mention the issue — and route them into Competing PR Comparison.
12. If no artifact scope can be resolved through URLs, numbers, `gh`, API, or search fallback, return a compact failure report instead of asking a question.

Maintainer reports and comments can use concise repo-local references such as `#123` and `PR #123`. Include full GitHub URLs only for posted comment/review links returned by GitHub or when the maintainer supplied an explicit URL.

## Existing Coverage and Re-Runs

Existing comments suppress duplicate posting, not analysis. The skill should always analyze the artifact in full, then post only the net-new delta over what is already covered.

Read existing maintainer/trusted-agent comments and reviews as prior coverage, but analyze fully regardless — a prior comment may be partial, catching one problem while missing another. Keep only net-new, high-confidence items not already materially covered. If a non-empty delta remains, post one comment that explicitly builds on the prior coverage (for example `Adding to @reviewer's review:`) and states only the new items, without restating covered points. If the delta is empty, post nothing public and report `Already covered` to the maintainer with the existing comment/review URL.

The skill should be idempotent across re-runs: it must treat its own earlier comments as already-covered and never stack a second comment that repeats an earlier one. RFC issues remain the one hard skip — no analysis and no post unless the maintainer overrides.

## Issue Flow

For each issue, first perform a cheap precheck: read issue metadata, labels, author, body, and existing comments. If labels, title, or body mark the issue as RFC (`rfc`, `[RFC]`, `RFC:`, or `Request for Comments`), classify it as `rfc-no-comment`, skip deep analysis, and do not post anything public unless the maintainer explicitly overrides the RFC skip for that item. Existing maintainer or trusted-agent comments are prior coverage, not an automatic skip — analyze fully and post only the net-new delta (see Existing Coverage and Re-Runs).

If the precheck does not skip the issue, gather the issue body, comments, screenshots, logs, reproduction details, linked artifacts, and relevant DeerFlow code/docs.

The public issue comment should start naturally, then move quickly into execution guidance. Prefer a short opener like `Thanks @author. <specific context sentence>.` when the issue is reporter-authored and the mention reads naturally. Omit the mention for bots, maintainer-authored tracking issues, or cases where it would add noise.

Do not include internal analysis labels or generic assessment openers such as "This is actionable", "I would treat this as", `ready-to-fix`, surface labels, or risk labels. Use the smallest stable template that fits:

```text
Thanks @author. <one specific sentence that frames the fix, investigation, or missing evidence.>

Recommended solution:
- ...

Validation:
- ...
```

Add optional sections only when they add signal:

- `Evidence:` for concrete code, logs, reproduction details, or proof.
- `Risk:` for specific architecture, security, public API, default behavior, or compatibility impact.
- `Missing info:` when the issue cannot be diagnosed without more evidence.

Put relevant files/components inside `Evidence:` or `Recommended solution:` bullets. Every posted issue comment should contain concrete modification guidance and validation guidance unless the only useful response is `Missing info:`.

Architecture and security concerns should be explained in the comment when they are relevant. They are not reasons to ask the maintainer what to do. Avoid private reasoning, credentials, internal-only context, exploit instructions, and unsupported promises.

Immediately before posting, refresh comments; fold any equivalent comment that appeared during analysis into prior coverage and post only the remaining delta.

## PR Review Flow

For each PR, first perform a cheap precheck: read PR metadata, changed file list, checks summary, existing PR reviews, existing comments, and review threads when available. Existing maintainer or trusted-agent reviews are prior coverage, not an automatic skip — review fully and post only the net-new delta.

Read `statusCheckRollup` as signal, not verdict. Failing required checks are themselves a reportable finding (a build failure is P0; failing tests or lint are P1/P2 by impact). Green checks lower risk but never excuse reading the actual changed code path: confirm suspect logic by reading the source, since tests passing does not prove the changed branch is exercised.

Before local diff review, establish the base from the base repository, not from local `main`. Prefer GitHub PR base metadata for PR target branches; for non-PR local diffs, use the base repository default branch. Fetch that branch with a command that updates the remote-tracking ref, such as `git fetch <base-remote> +refs/heads/<base-branch>:refs/remotes/<base-remote>/<base-branch>`, or use the verified `FETCH_HEAD` immediately. In fork checkouts this is usually `upstream/main`; in direct upstream checkouts this is usually `origin/main`. Use a merge-base or three-dot diff from the fetched base. If local base resolution fails, use the GitHub PR files/diff as source of truth.

Resolve the PR head explicitly. For fork PRs whose head branch is not on the base repo, fetch the PR ref with `git fetch <base-remote> pull/<n>/head:pr-<n>`; the fork's own branch ref and `gh api .../contents?ref=<fork-branch>` will 404 against the base repo. Record the head SHA reviewed, and re-check it immediately before posting — if the PR head moved during analysis, re-review the new diff or abort rather than post a review against a diff the PR no longer has.

Review only the current diff and changed files. Do not comment on unrelated pre-existing code unless the diff makes it newly risky. Do not report low-confidence guesses.

Prioritize correctness, safety, maintainability, production risk, compatibility, and missing critical tests. Architecture, security, public API, default-behavior, and compatibility problems should be reported as findings when the diff causes or exposes them.

For public PR reviews with findings, start with one short opener that fits the review context and matches the finding count. Use singular wording only for exactly one finding, for example `Thanks @author. I found one issue that should be addressed before this is ready.` Use plural wording for multiple findings, for example `Thanks @author. I found a few issues that should be addressed before this is ready.` Omit the mention for bots or when it adds noise.

Use this finding format:

```text
[P0/P1/P2] Title

- Location: file and line/range
- Problem: what can go wrong
- Evidence: why the diff causes it
- Suggested fix: concrete minimal fix
- Test: what test should cover it
```

Severity:

- `P0`: causes outage, data loss, security breach, or build failure.
- `P1`: likely production bug, serious regression, broken compatibility, or high-risk security/architecture issue.
- `P2`: correctness, maintainability, or test concern with lower risk.

### Posting Gate

Posting depends on both confidence (is the problem real?) and severity (how bad if real); they are independent axes. "No high-confidence findings" means none across P0/P1/P2, not merely "no P0".

Post publicly only items that are high-confidence and at least P2. For a public P2, additionally require that the diff itself introduces or worsens the issue — do not raise a public P2 for pre-existing behavior the diff only touches, or for a change that is a net improvement over the prior state. A high-confidence P0/P1 is always worth posting; a low-confidence P1 is not, so omit it or route it to maintainer notes as a hypothesis to verify. Sub-threshold but real observations (net-improvement nits, bounded or low-risk concerns, pre-existing issues, low-confidence hypotheses) go to the maintainer-only notes channel in the run result.

If the gate yields no public findings, do not post a public PR review/comment. Report `No high-confidence review findings.` (or `Already covered`) to the maintainer in the run result, plus any maintainer notes.

Immediately before posting, refresh reviews/comments; fold any equivalent review that appeared during analysis into prior coverage and post only the remaining delta.

## Batch Handling

When the scope has multiple artifacts, cluster before reviewing and synthesize after.

Cluster by relatedness, not by type. Group artifacts that share files, interfaces, or the same issue/feature into one cluster; same-type artifacts that touch disjoint files are independent. Review a related cluster in one shared context so cross-artifact reasoning is possible — parallel agents cannot see each other's findings, so a related cluster should never be split across parallel agents. Independent clusters may run in parallel; offloading a large or independent batch to one subagent per cluster keeps the main context clean. Consider this for big batches and prefer offering it to the maintainer over silently spawning; do not spawn for two or three related items or when the cold-start cost is not earned.

After per-artifact review, run one synthesis pass over the whole batch and report it to the maintainer as decision-support (not a public comment): overlapping files and the merge-order/conflict surface (which PRs touch the same files and will conflict pairwise), duplicate or competing solutions to the same problem, and composition risk where changes are each safe alone but interact (for example, two PRs editing the same module or table).

## Competing PR Comparison

When several PRs target the same issue, compare them instead of reviewing each in isolation. Pull the issue's acceptance criteria (the reported problem and expected behavior) as the rubric anchor, then score each PR on whether it actually resolves the issue's ask, correctness and edge/error-path coverage, test quality, blast radius and compatibility, and maintainability — using the same DeerFlow heuristics and Posting Gate as a single review.

Report a maintainer-facing comparison (the strongest PR and why, and what each is missing) in the run result. Keep the public surface constructive and per-PR: post each PR's own gate-passing findings normally, and do not publicly rank PRs against each other or tell an author their PR is worse than a competitor's. Winner selection is the maintainer's call and stays in the maintainer report.

## No-Question Policy

The skill should not ask routine clarification questions. It should use the workflow to resolve scope and produce comments.

Stop without asking only when:

- no issue/PR scope can be resolved through URLs, numbers, `gh` view/list, `gh api`, or GitHub search fallback;
- GitHub authentication, repository access, or comment posting fails;
- the requested action is outside comment-only scope;
- posting would require private credentials, private security details, or non-public context.

In these cases, return a compact failure report with attempted command path and smallest next action. Do not phrase it as a question unless the maintainer explicitly asks to be prompted.

## DeerFlow Heuristics

Treat these as high-signal areas for issue comments and PR findings:

- `backend/packages/harness/deerflow/` must not import `app.*`.
- App may depend on harness; harness must stay publishable and app-agnostic.
- Frontend thread/message behavior and Gateway/LangGraph-compatible SSE are contract surfaces.
- Sandbox permissions, bash/file-write tools, skill installation, and remote execution are security-sensitive.
- Default model/provider behavior, config migration, persistence schema, public API/SSE, and LangGraph thread/run lifecycle are compatibility-sensitive.
- Runtime docs should track user-facing or developer-facing behavior changes.
- Security-sensitive comments should provide proof and remediation, not vague assertions.

## Validation Guidance

| Surface | Suggested evidence |
| --- | --- |
| Backend API / harness / agents / MCP / runtime skills | `cd backend && make lint && make test` |
| Blocking IO or async IO risk | `cd backend && make test-blocking-io` or focused regression |
| Harness/app boundary | `cd backend && uv run pytest tests/test_harness_boundary.py` |
| Frontend UI/core | `cd frontend && pnpm format && pnpm lint && pnpm typecheck && BETTER_AUTH_SECRET=local-dev-secret pnpm build && make test` |
| Front/back thread or SSE contract | backend replay golden and full-stack replay render where feasible |
| Frontend user workflow | Playwright E2E or browser proof with screenshot/DOM assertion |
| Docker/sandbox/provisioner | focused backend tests plus Docker/provisioner smoke when feasible |
| Docs-only | targeted markdown review |

## Output

For Issue Flow, report posted, skipped, already-covered, failed, maintainer notes, and per-issue comment status. For analysis-only requests, report drafted comments instead of posted comments.

For PR Review Flow, report reviewed, skipped, clean, already-covered, failed, maintainer notes, and per-PR review status. `Clean` means no high-confidence findings and no public comment posted; `Already covered` means the net-new delta was empty over existing coverage.

For batches, prefer a compact maintainer-facing table, then follow it with a `Batch synthesis` block (overlapping files, merge-order/conflict surface, duplicate or competing solutions, composition risk) and, when issues had competing PRs, a `Competing PR comparison` block. Both are maintainer-only.

```text
| Artifact | Status | Public action | Notes |
| --- | --- | --- | --- |
| #123 | posted | comment URL | short reason |
| PR #456 | reviewed | review URL | P1: finding title |
| PR #789 | clean | none | No high-confidence review findings. |
| #321 | already covered | none | existing maintainer comment |
```

Omit empty categories, no-op fields, routine command output, and raw logs. Report meaningful changes, evidence, and options.
