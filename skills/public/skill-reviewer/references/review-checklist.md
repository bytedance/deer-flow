# Skill Review Checklist

Use this checklist to keep reviews concrete and repeatable.

## Deterministic Facts

- Root `SKILL.md` exists, is UTF-8 text, and has valid YAML frontmatter.
- `name` and `description` are non-empty and valid for the selected profile.
- `allowed-tools`, `required-secrets`, and `secrets-autonomous` are structurally valid.
- Package digest is present.
- `SkillScan` findings are visible and severity is preserved.
- Reader errors, truncation, and analyzer errors are reported as limitations.

## Trigger Boundary

- Description says what the skill does.
- Description says when to invoke it.
- Description does not claim broad ownership over adjacent tasks.
- Sibling collision cases are named when relevant.
- Suggested replacement text is concise enough for catalog display.

## Instructions

- Inputs are named.
- Ordered actions are explicit.
- Branches and fallback behavior are clear.
- Stop conditions are clear.
- The skill tells the agent what not to do when that matters.

## Resources And Scripts

- Required references are reachable from `SKILL.md`.
- Unreferenced files are either intentional or removed.
- Scripts have documented inputs and outputs.
- Scripts are not required unless the instructions say when to run them.
- Templates and assets have read-when guidance.

## Safety

- Side effects are named.
- Destructive or externally visible actions require confirmation.
- Secrets are declared rather than hardcoded.
- Network access is justified.
- Retry and idempotency behavior is bounded where relevant.

## Evidence

- Trigger evals include positive and negative cases when routing is fuzzy.
- Behavior evals tie outputs to the reviewed digest.
- Baselines are frozen before claiming improvement.
- Runtime, model, prompts, outputs, and graders are retained for verified claims.
