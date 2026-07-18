# Report Rendering

The canonical machine contract is `review-report.v1`. Markdown is a localized view of that report, not a second source of truth.

## Full Review Sections

1. Executive Summary
2. Readiness
3. Assurance
4. Scope and Completeness
5. Findings
6. Dimension Review
7. Trigger Analysis
8. Resource and Script Review
9. Evidence
10. Suggested Rewrites
11. Recommended Actions

Focused reviews may omit unrelated analytical sections, but must keep scope, readiness, assurance, evidence, and recommended actions.

## Machine Enums

Do not translate enum values in structured output:

- `blocked`
- `revise`
- `publish_candidate`
- `static_only`
- `trigger_checked`
- `behavior_verified`
- `regression_verified`
- `pass`
- `concern`
- `blocker`
- `not_assessed`

Localized labels may appear next to enums:

- `blocked`: Not ready / 不可发布
- `revise`: Needs revision / 需修订
- `publish_candidate`: Publish candidate / 可作为发布候选
- `static_only`: Static review only / 仅静态审查

## Finding Format

Each issue should include:

- severity: `blocker`, `major`, or `minor`;
- confidence: `high`, `medium`, or `low`;
- location: path and line when available;
- observed evidence;
- user impact;
- remediation;
- suggested replacement when there is a small paste-ready fix.

Avoid large quotes. Never quote suspected secrets.
