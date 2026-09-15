# DeerFlow Maintainer Orchestrator — design notes

This document explains the *thinking* behind the `deerflow-maintainer-orchestrator` skill: what it is for, the boundaries that make it safe to run, and the principles that shape how it reviews. It is written for DeerFlow maintainers who run the skill, and for anyone in the community who wants to understand — or adapt — the pattern of delegating issue and PR triage to an agent.

It is **not** a rule reference. The exact resolution commands, comment templates, severity definitions, and validation matrix live in the skill itself, which is the canonical executable contract:

> `.agent/skills/deerflow-maintainer-orchestrator/SKILL.md`

When the two disagree, the skill wins and this document should be updated to match.

## What problem it solves

Triage is repetitive and easy to defer. A maintainer has to open each issue or PR, reconstruct context, judge severity, and write a comment that actually helps the author move forward. The skill turns a *bounded scope* — some issue or PR numbers, a count, or a time window — into evidence-backed comments through a fixed workflow, without turning routine judgment back into questions for the maintainer and without handing the analysis back for them to finish.

The goal is leverage, not autonomy. The maintainer still owns every decision that matters; the skill does the legwork and makes a concrete, defensible recommendation inside each comment.

## The safety model: comment-only

The most important property of this skill is the surface it is *not* allowed to touch. It operates entirely on the **comment plane**: resolve scope, read evidence, post or draft issue comments and PR review comments. It does not write code, manage branches, close or label artifacts, or cut releases.

This is a deliberate trust boundary. A comment is the lowest-risk, most reversible action an agent can take on a repository — a wrong comment costs a correction, while a wrong merge, force-push, or release costs far more. Keeping the agent on the comment plane is what makes it safe to run over a batch of real PRs without pre-auditing every step for irreversible damage.

## When it posts: a deliberately high bar

Public review noise erodes trust faster than the occasional missed nit, so posting is conservative and gated on two **independent** axes:

- **Confidence** — is the problem real?
- **Severity** — P0/P1/P2: how bad if it is real?

A finding reaches the **public** surface only when it is high-confidence *and* at least P2. "No high-confidence findings" means none across P0/P1/P2 — not merely "no P0." A public P2 carries one extra guard: the diff under review must itself introduce or worsen the issue, so the skill does not lecture an author about pre-existing behavior their change merely touches, or about a change that is already a net improvement.

Everything real but below that bar — net-improvement nits, bounded risks, low-confidence hypotheses, pre-existing issues — goes to a **maintainer-only notes channel** in the run result, never to a public comment. The maintainer still sees the signal; the author's thread stays clean.

## How it treats existing coverage

Existing comments suppress duplicate *posting*, not *analysis*. The skill always analyzes the artifact in full, because a prior review may have caught one problem and missed another. It then posts only the net-new delta, explicitly building on what is already there, and stays silent when there is nothing to add. Re-running is safe by design: the skill treats its own earlier comments as covered and never stacks a second comment that repeats the first.

## Principles that shape the review

A handful of ideas do most of the work:

- **Evidence over a green check.** CI status is a signal, not a verdict. A green rollup never excuses reading the changed code path, and a failing required check is itself a finding. Tests passing does not prove the changed branch is exercised.
- **Review the right diff.** A finding is only as trustworthy as the diff it is computed against. The skill compares against a freshly fetched base rather than a stale local branch, resolves fork PR heads explicitly, records the reviewed head SHA, and re-checks it before posting — because a review against a diff the PR no longer has is worse than no review.
- **Reason about batches, not just artifacts.** Related PRs are clustered and reviewed in one context, then a synthesis pass reports cross-PR interactions: overlapping files, merge-order and conflict surface, and composition risk where each change is safe alone but unsafe together. Reviewing related PRs in isolation is how you patch one and break another.
- **Compare competing PRs fairly.** When several PRs target the same issue, they are scored against the *issue's acceptance criteria* as the rubric. The ranking is for the maintainer; the public surface stays per-PR and constructive, and never tells one author their PR is worse than a competitor's.

## What it deliberately does not do

Scope discipline is part of the design, not an omission:

- It stays on the comment plane (above) — no code, branch, or release actions.
- It keeps its review heuristics focused and delegates detection that other tools already own. Blocking-IO on the event loop, for example, is covered by the CI blocking-IO gate and a dedicated `blocking-io-guard` skill, so it is intentionally left out of this skill's heuristics rather than duplicated. Separation of concerns keeps each tool sharp.
- It keeps private reasoning, credentials, and security-exploit detail out of public comments; sensitive issues are described by impact and remediation only.

## How a maintainer runs it

Give it a scope: issue or PR numbers, a URL, a count, or a time window. It resolves the artifacts with GitHub tooling and returns posted comment and review URLs, clean results, already-covered notes, maintainer-only notes, a batch synthesis, or — when you ask for analysis only — drafts to review before anything is posted. It does not ask routine clarifying questions; it stops and reports only when scope genuinely cannot be resolved, access fails, the request leaves comment-only scope, or posting would require non-public context.

Output language follows the artifact: Chinese issues and PRs get Chinese comments, English gets English.

## Adapting this pattern

If you are building something similar for your own project, three choices carry most of the value and transfer cleanly:

1. **Keep the agent on a reversible surface** (comments) until you trust it; reversibility is what lets you run it unattended.
2. **Gate public output on confidence and severity together**, with a private channel for everything below the bar — a reviewer that posts everything it notices is quickly muted.
3. **Make the agent prove it reviewed the current diff** before it speaks.

The rest — surfaces, severity labels, validation commands, output formats — is project-specific and belongs in the skill, not in a document like this one.
