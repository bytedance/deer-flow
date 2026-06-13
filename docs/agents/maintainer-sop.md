# DeerFlow Maintainer Orchestrator SOP

This SOP defines how DeerFlow maintainers should use the repository-local `deerflow-maintainer-orchestrator` skill for comment-only GitHub issue handling and PR review.

The goal is practical automation: the maintainer provides an issue or PR scope, and the agent resolves the artifacts with GitHub tools, analyzes DeerFlow context, and posts or drafts useful comments. The skill should not turn routine judgment into maintainer questions or offload technical analysis back to the maintainer.

The local skill lives at `.agent/skills/deerflow-maintainer-orchestrator/SKILL.md`.

## Scope

- **Issue Flow** analyzes GitHub issues and posts or drafts issue comments.
- **PR Review Flow** reviews GitHub pull request diffs and posts or drafts PR review comments.
- The skill is a comment-plane workflow. It does not implement code changes, manage branches, close artifacts, publish releases, or perform non-comment maintainer actions.

## Comment Authorization

When the maintainer asks to process, handle, comment on, or review a bounded set of issues or PRs, the skill may post one public issue comment per selected non-skipped issue and one PR review comment per selected PR with high-confidence findings.

If a PR has no high-confidence findings, the skill should not post a public review/comment. It should report that clean result to the maintainer only.

When the maintainer explicitly asks for analysis only, the skill should return comment-ready drafts without posting.

The maintainer's normal interaction should be: provide scope; receive posted comment URLs, PR review URLs, clean results, skipped items, failures, or drafts.

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
11. If no artifact scope can be resolved through URLs, numbers, `gh`, API, or search fallback, return a compact failure report instead of asking a question.

Maintainer reports and comments can use concise repo-local references such as `#123` and `PR #123`. Include full GitHub URLs only for posted comment/review links returned by GitHub or when the maintainer supplied an explicit URL.

## Issue Flow

For each issue, first perform a cheap precheck: read issue metadata, labels, author, body, and existing comments. If labels, title, or body mark the issue as RFC (`rfc`, `[RFC]`, `RFC:`, or `Request for Comments`), classify it as `rfc-no-comment`, skip deep analysis, and do not post anything public unless the maintainer explicitly overrides the RFC skip for that item. If a maintainer or trusted agent already posted an equivalent diagnosis, modification suggestion, information request, or blocking decision, skip deep analysis and do not post anything public for that issue.

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

Immediately before posting, refresh comments and skip if an equivalent maintainer or trusted-agent comment appeared during analysis.

## PR Review Flow

For each PR, first perform a cheap duplicate-review precheck: read PR metadata, changed file list, checks summary, existing PR reviews, existing comments, and review threads when available. If a maintainer or trusted agent already posted equivalent findings or a blocking decision, skip deep review and do not post another review comment.

Before local diff review, establish the base from the base repository, not from local `main`. Prefer GitHub PR base metadata for PR target branches; for non-PR local diffs, use the base repository default branch. Fetch that branch with a command that updates the remote-tracking ref, such as `git fetch <base-remote> +refs/heads/<base-branch>:refs/remotes/<base-remote>/<base-branch>`, or use the verified `FETCH_HEAD` immediately. In fork checkouts this is usually `upstream/main`; in direct upstream checkouts this is usually `origin/main`. Use a merge-base or three-dot diff from the fetched base. If local base resolution fails, use the GitHub PR files/diff as source of truth.

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

If there are no high-confidence findings, do not post a public PR review/comment. Report `No high-confidence review findings.` to the maintainer in the run result.

Immediately before posting, refresh reviews/comments and skip if an equivalent maintainer or trusted-agent review appeared during analysis.

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

For Issue Flow, report posted, skipped, failed, and per-issue comment status. For analysis-only requests, report drafted comments instead of posted comments.

For PR Review Flow, report reviewed, skipped, clean, failed, and per-PR review status. `Clean` means no high-confidence findings and no public comment posted.

For batches, prefer a compact maintainer-facing table:

```text
| Artifact | Status | Public action | Notes |
| --- | --- | --- | --- |
| #123 | posted | comment URL | short reason |
| PR #456 | reviewed | review URL | P1: finding title |
| PR #789 | clean | none | No high-confidence review findings. |
| #321 | skipped | none | existing maintainer comment |
```

Omit empty categories, no-op fields, routine command output, and raw logs. Report meaningful changes, evidence, and options.
