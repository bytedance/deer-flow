# DeerFlow Skill Static Rules

These Semgrep rules are the deterministic security layer for skill install and
update paths. Keep rules narrow and high-confidence. Every blocking rule must
include:

- a stable `id`
- `metadata.deerflow_severity`
- `metadata.remediation`
- a unit or integration test

Scanner runtime failures block skill install and update paths because this
static layer is a security gate. Non-critical findings are surfaced as warnings
and continue to the LLM scanner.
