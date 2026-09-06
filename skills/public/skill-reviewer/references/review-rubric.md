# Skill Review Rubric

Use this rubric after `review_skill_package` returns deterministic facts. Deterministic blockers and errors always take precedence over semantic judgment.

## Dimensions

### 1. Trigger Boundary

Status:

- `pass`: The description states what the skill does, when to invoke it, and realistic neighboring intents it should not own.
- `concern`: The description is useful but broad, narrow, ambiguous, or likely to collide with sibling skills.
- `blocker`: The description is so broad or misleading that normal routing would frequently select the wrong skill.
- `not_assessed`: The description was unavailable or trigger review was out of scope.

Look for:

- clear user intent triggers;
- sibling collision risk;
- negative examples only when they clarify a real boundary;
- concise wording suitable for catalog display.

### 2. Instruction Executability

Status:

- `pass`: The model can identify inputs, ordered actions, forks, stop conditions, failure handling, and completion criteria.
- `concern`: Some decisions require hidden interpretation or missing inputs.
- `blocker`: The workflow cannot be executed reliably from the written instructions.
- `not_assessed`: Instruction body was unavailable or out of scope.

### 3. Resource Design

Status:

- `pass`: References, templates, assets, scripts, and evals are reachable, necessary, and loaded progressively.
- `concern`: Some resources are unreferenced, stale, duplicated, or loaded too eagerly.
- `blocker`: Required resources are missing or instructions depend on inaccessible artifacts.
- `not_assessed`: Resources were unavailable or out of scope.

Script necessity belongs in this dimension. Do not double-count scripts as a separate score.

### 4. Safety And Operational Constraints

Status:

- `pass`: Side effects, secrets, network use, destructive actions, user confirmation, retries, and idempotency are bounded.
- `concern`: Safety guidance exists but is incomplete or too implicit.
- `blocker`: The skill asks for unsafe actions, mishandles secrets, or lacks required confirmation for high-risk operations.
- `not_assessed`: Safety was out of scope.

If deterministic safety findings include a blocker, readiness is `blocked` regardless of this semantic status.

### 5. Output Contract

Status:

- `pass`: The expected output is useful, stable, and verifiable without over-constraining normal prose.
- `concern`: Output format or completion criteria are vague.
- `blocker`: The user cannot tell when the workflow is complete or whether the result is valid.
- `not_assessed`: Output was out of scope.

### 6. Maintainability

Status:

- `pass`: Responsibilities are separated and cross-file contracts are consistent.
- `concern`: The package is understandable but contains duplication, stale claims, or unclear ownership.
- `blocker`: The package structure makes safe maintenance unrealistic.
- `not_assessed`: Maintainability was out of scope.

### 7. Evidence Quality

Status:

- `pass`: Evals, baselines, retained outputs, and grading support the claims made.
- `concern`: Evidence exists but is partial, stale, or not tied to the reviewed digest.
- `blocker`: The skill makes high-risk or measurable claims with no credible supporting evidence.
- `not_assessed`: Evidence review was out of scope.

Missing evals are normally a recommendation, not a blocker. They become a major issue when the skill performs destructive or externally visible actions, handles secrets, has sibling-routing collision risk, claims measurable improvement, produces high-stakes output, or has known regressions.

## Issue Severity

- `blocker`: Must be fixed before publication or use within the assessed scope.
- `major`: Should be fixed before publication; readiness is at most `revise`.
- `minor`: Useful improvement that does not materially block the assessed scope.

## Confidence

- `high`: Direct evidence from facts or quoted package content.
- `medium`: Strong inference from package structure or missing contracts.
- `low`: Plausible concern that needs author confirmation.
