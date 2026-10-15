# Effect Verification

Readiness and assurance are separate.

## Assurance Levels

- `static_only`: The package was inspected statically. No runtime evidence was retained.
- `trigger_checked`: Positive and negative routing cases were executed against a stated model/runtime and retained.
- `behavior_verified`: Behavior assertions passed for the reviewed package digest.
- `regression_verified`: A frozen baseline and reviewed package were compared with retained outputs and grading evidence.

## Evidence That Raises Assurance

To move beyond `static_only`, evidence must include:

- subject digest;
- model ID;
- runtime or DeerFlow version;
- prompt inputs;
- tool trace;
- outputs;
- assertions or grading result;
- timestamp.

If any of those are missing, stale, contradictory, or attached to a different digest, name the limitation and keep the lower assurance level.

## Risk-Based Evidence

Missing evals become material when a skill:

- performs destructive or externally visible actions;
- handles secrets or sensitive data;
- has known sibling-routing collision risk;
- claims measurable improvement over a baseline;
- produces high-stakes output;
- has a history of regressions.
