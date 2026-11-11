# Skills (`skills/`)

`public/` holds committed skills and `custom/` holds local, gitignored skills.
Tests for public skill scripts are in `tests/skills/` at the repository root and
run in Skill Review CI, independent of package review.

- **`public/skill-reviewer/` is the built-in read-only reviewer.** Its contracts
  are in `contracts/skill_review/`. Review data that the model sees is
  tag-neutralized, and raw payloads stay in tool artifacts.
- **CI waivers are in `.github/skill-review-waivers.v1.json`.** Only the
  manifest from the trusted base revision can suppress a run, and a blocker
  finding cannot be waived.
- **Read `SKILL.md` as `utf-8-sig` and write text resources as `utf-8`.** The
  platform locale is not reliable, and a leading BOM would become part of the
  content.
- **Skill script tests run offline.** Test a dependency fallback with the
  optional import unavailable, and mock the HTTP transport.
- **A skill CLI exits non-zero on failure**, with diagnostics on stderr and
  result URLs on stdout.
