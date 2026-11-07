# Skill self-evolution example — evidence-gated revisions

An opt-in Python plugin that demonstrates the roadmap deliverable from
[#7884](https://github.com/bytedance/deer-flow/issues/7884) ("Skills,
extensions, and reproducible agents"): a **proposed change**, the **regression
case it fixes**, the **old and new results**, and a **rollback to a known-good
version** — driven entirely through the host `SkillMutationService` contract
merged in [#5645](https://github.com/bytedance/deer-flow/pull/5645).

It uses extension API 0.2.11 with no host code changes. The host owns storage,
security scanning, revision identity and authorization; this package owns only
one policy: **a revision commits only when a recorded regression case
demonstrates it fixes something**.

## Why evidence-gated

With `skill_evolution.enabled`, the agent can already rewrite its own skills
through `skill_manage`. What is missing is a visible answer to "was that change
an improvement?". This example attaches one to every commit:

```
propose ──> stage()          freeze baseline + candidate bundles (host-side)
evaluate ─> recorded cases    run static checks against BOTH bundles
apply ────> check() + commit(assessment_ref)   host security gate, then commit
                                                  with the verdict attached
rollback ─> revert()          append-only return to the known-good revision
```

The `AssessmentRef` carried into `commit` binds the evidence to the exact
proposal (`candidate_hash` + `base_revision`); the host rejects a mismatched
assessment with `INVALID_ASSESSMENT`. Afterwards every committed `Operation`
answers: what changed, which recorded cases justified it, and how to undo it.

## Recorded regression cases

Cases are JSON files in `deerflow_extension_skill_evolution/cases/` (override
with `config.cases_dir`). One case per file:

```json
{
  "id": "converter-arg",
  "description": "SKILL.md must instruct the converter with --format json",
  "checks": [
    { "kind": "text_contains", "path": "SKILL.md", "needle": "--format json" },
    { "kind": "text_not_contains", "path": "SKILL.md", "needle": "--fmt " }
  ]
}
````

Check kinds: `file_exists`, `text_contains`, `text_not_contains`,
`referenced_files_exist` (bare `scripts/…` / `assets/…` tokens in a text file
must exist in the package), and `scripts_parse` (every `scripts/*.py` must pass
`ast.parse`).

**The evaluator never executes package content.** The candidate is an
agent-proposed revision that has not passed the host security `check` yet, so
the only safe operations are structural (presence, text, parse-only). A
malformed case file raises and stops the evaluation rather than silently
narrowing it.

### Verdicts

| Verdict | Meaning | Service behavior |
| --- | --- | --- |
| `justified` | every case passes on the candidate and at least one fails on the baseline | eligible for `apply` |
| `unjustified` | every case passes on both sides — nothing recorded was broken | proposal discarded, `apply` refuses |
| `failed` | some case still fails on the candidate (or none recorded) | proposal discarded, `apply` refuses |

## Install and configure

From the DeerFlow checkout root:

```sh
make extension-install SOURCE=examples/deerflow-extension-skill-evolution
```

The mutation capability requires an explicit operator grant in `config.yaml`
(restart required). Prerequisites are the same as any `skill_mutations`
consumer: durable database backend, `run_events.backend: db`, and a single
POSIX host with local disk:

```yaml
plugins:
  - name: skill-evolution
    package: deerflow-extension-skill-evolution
    use: deerflow_extension_skill_evolution:install
    enabled: true
    host_access:
      evidence:
        owners: ["your-user-id"]
      skill_mutations:
        owners: ["your-user-id"]          # subset of evidence.owners
        operations: [stage, check, commit, revert]
        trigger_agents: [lead_agent]
        target_skills: [example-skill]    # canonical names this plugin may revise
        topology: single_host_local
    config:
      cases_dir: null                     # optional: default bundled cases
```

Without the grant the service fails to start with a `NOT_GRANTED` diagnostic;
nothing else in the deployment changes.

## HTTP surface

All routes are under `/api/extension-skill-evolution`:

| Route | Purpose |
| --- | --- |
| `GET /health` | readiness, evaluator identity, recorded case count |
| `POST /proposals` | resolve the sealed run evidence, stage a candidate, evaluate, return the verdict + report |
| `GET /proposals` · `GET /proposals/{id}` | list / inspect proposals and their reports |
| `POST /proposals/{id}/apply` | host `check`, then commit with the `AssessmentRef` attached |
| `POST /operations/{id}/revert` | roll back a committed revision |

`POST /proposals` takes `{skill_name, candidate_content, thread_id, run_id}`.
The run must be completed and sealed — it is the evidence anchor the host
requires for staging (`source_refs`), so every proposal records *which run
motivated the change*.

## Offline walkthrough (tests)

The package ships the demonstration as tests; no Gateway, model, or network:

```sh
cd examples/deerflow-extension-skill-evolution
uv run --no-project --python 3.12 --with pytest --with pytest-asyncio \
    --with ../../backend/packages/extension-api \
    --with-editable . python -m pytest tests/ -q
```

`tests/test_lifecycle.py` drives the full loop against a fake host that
implements only the public contract: propose a fix for a broken converter
argument → verdict `justified` → apply → the committed operation carries the
report id → revert → the skill is byte-identical to the known-good baseline.
It also pins the refusal paths: `unjustified` and `failed` proposals are
discarded and cannot commit, a denied host `check` blocks the commit, and
double-commit is rejected.

## Scope and boundaries

- **This is an example, not a production engine.** The evaluator is a
  deterministic static checker; it has no live-model runs, metrics, or signal
  collection.
- [#6954](https://github.com/bytedance/deer-flow/discussions/6954) proposes a
  distributable evolution plugin package with its own snapshot/versioning
  design; this example stops at the merged #5645 contract and should be
  revisited against that RFC if it lands.
- [#7066](https://github.com/bytedance/deer-flow/issues/7066) (eval-gated
  evolution) owns the broader signal → attribution → candidate → verification
  loop; the minimal evaluator here is deliberately smaller than that scope.
- The `skill_manage` direct-write path is unchanged. This plugin is additive
  and opt-in.

## A concrete evidence standard (input for the roadmap discussion)

The roadmap asks what evidence should be required before enabling automatic
publication. Rather than propose a standard in the abstract, this example makes
one concrete and reviewable:

1. **Every proposal names its motivating run.** Staging requires sealed
   completed-run evidence (`source_refs`); the host rejects stale or unsealed
   anchors.
2. **Evidence is recorded, not narrated.** A case is a versioned JSON file with
   deterministic checks; the verdict is computed from the frozen baseline and
   candidate bundles, not from the proposal text.
3. **The verdict travels with the commit.** `AssessmentRef` pins
   `evaluator`, `evaluator_version`, and a content-addressed `report_id`
   (SHA-256 over the canonical report JSON) to the exact `candidate_hash` and
   `base_revision`.
4. **Fail-closed by default.** `unjustified` and `failed` proposals are
   discarded before they can commit; a host `check` denial blocks the commit;
   an assessment mismatch is rejected by the host itself.
5. **Rollback is as auditable as the change.** `revert` appends a new
   operation referencing the one it undoes.

Automatic publication would additionally need: case authorship provenance (who
recorded the case, and was it derived from the same run that motivated the
change), a minimum case count, and a policy for `unjustified` proposals that
keep recurring. Those are deliberately out of scope here.
