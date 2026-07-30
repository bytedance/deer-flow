# Eval Design For Skills

Use evals to prove routing and behavior claims. Static review can recommend evals, but it must not claim runtime verification without retained runs.

## Trigger Evals

A trigger eval set should include:

- positive cases that should invoke the skill;
- negative cases that should route elsewhere;
- sibling collision cases when another skill has a similar boundary;
- short rationales for each case.

The existing trigger-eval list shape is supported:

```json
[
  {
    "query": "Review this skill for publication readiness",
    "should_trigger": true,
    "rationale": "Explicit skill review request"
  }
]
```

## Behavior Evals

Behavior evals should retain:

- reviewed package digest;
- model and runtime identity;
- prompt and expected behavior;
- tool trace;
- output artifact;
- assertion or grading result.

## Baseline Comparisons

To claim improvement, retain both the baseline and candidate package digests. The report can only use `regression_verified` when comparison artifacts and grading evidence are present.
