"""Secondary adapters for the schedule bounded context.

Grouped by context rather than by technology, mirroring `domain/schedule/`:
everything the outer ring provides to this one context lives here, whether it
talks to SQL (`task_sql`, `run_sql`), converts a wire/storage shape
(`spec_mapping`), or wraps a runtime.

`app/infra/persistence/feedback.py` still follows the older technology-first
layout because it belongs to a separate migration; the two will converge.
"""
