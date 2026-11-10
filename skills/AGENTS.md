# Skills

Skill quality review note:
- `skills/public/skill-reviewer/` is the built-in read-only reviewer (harness tool
  `review_skill_package`, contracts in `contracts/skill_review/`). Model-visible review
  data is tag-neutralized; raw payloads stay in tool artifacts. See
  [backend/AGENTS.md](../backend/AGENTS.md) for the ownership boundaries.
- CI waivers live in `.github/skill-review-waivers.v1.json`, enforced by
  `scripts/review_changed_public_skills.py`. Only the manifest from the trusted base
  revision can suppress a run, and blocker findings can never be waived.

## Skill tests

Skill-creator tests must preserve YAML values/body, restore bytecode settings,
and check invalid metadata through offline CLI subprocesses.
Public skill script regressions live in `tests/skills/` and run in Skill Review CI
independently of package review. Exercise dependency fallbacks with the optional
import unavailable and mock HTTP transport to keep tests offline.
Video, podcast, and chart-visualization CLI failures exit non-zero;
diagnostics on stderr, success URLs on stdout; test offline.

## Conventions

- **Skill text encoding** — use explicit UTF-8 for textual skill resources.
  Read `SKILL.md` with `encoding="utf-8-sig"` to strip a leading BOM; write with
  `encoding="utf-8"`. Never rely on the platform locale.
