"""Synthetic, predeclared cases. Grader expectations are never sent to models."""

from dataclasses import dataclass, field


@dataclass
class Case:
    name: str
    category: str
    kind: str
    brief: str
    history: list[tuple[str, str]]
    expected: dict | None = None
    summary: str = ""
    references: dict[str, str] = field(default_factory=dict)
    function: str | None = None
    checks: list[dict] = field(default_factory=list)


CASES = [
    Case(
        "rate_limits",
        "conversation_requirements",
        "json",
        ("Write the agreed rate-limit configuration as JSON with exactly these keys: window_seconds, authenticated_limit, anonymous_limit, key_fields, algorithm, fail_open, trusted_proxy_hops. All values follow our final discussion."),
        [
            ("user", ("We use a 90-second sliding window. Anonymous clients get 12 requests. Use algorithm='sliding_window'. Identify clients using the ordered fields tenant_id, user_id; never use source IP as the quota key.")),
            ("assistant", "An initial proposal was authenticated_limit=120 and fail_open=true. That is only a proposal."),
            ("user", "Set trusted_proxy_hops=1. Metrics export is unrelated to this configuration and should not add JSON fields."),
            ("assistant", "We also considered 300-second windows for batch traffic but did not choose that plan."),
            ("user", ("Final correction: authenticated_limit is 75, not 120, and fail_open must be false. Keep the previously agreed 90-second window and anonymous limit unchanged.")),
        ],
        expected={"window_seconds": 90, "authenticated_limit": 75, "anonymous_limit": 12, "key_fields": ["tenant_id", "user_id"], "algorithm": "sliding_window", "fail_open": False, "trusted_proxy_hops": 1},
    ),
    Case(
        "invoice_total",
        "summary_requirements",
        "python",
        (
            "Implement invoice_total(lines) in a standalone Python artifact, without imports. Each input line has integer unit_cents and quantity, optional "
            "cancelled and discount_bps. Return the integer total in cents using our agreed invoice rules."
        ),
        [
            ("user", ("A line is excluded only when cancelled is true. Missing cancelled means false. Missing discount_bps means zero. The function must not mutate its input.")),
            ("assistant", "Using Python round on a floating-point aggregate gave incorrect half-cent totals in an earlier attempt."),
            ("user", "Negative quantity means a refund and remains valid. Quantities of zero contribute zero. Empty invoices return 0."),
        ],
        summary=(
            "Earlier final agreement: apply discount_bps per line to unit_cents * quantity. Round each discounted line to integer cents, with half ties away "
            "from zero, then sum the rounded lines. Use exact integer arithmetic; do not round only the grand total. The valid discount range is 0..10000 "
            "inclusive; raise ValueError outside it, except cancelled lines are skipped before validation."
        ),
        function="invoice_total",
        checks=[
            {"args": [[{"unit_cents": 100, "quantity": 2}]], "want": 200},
            {"args": [[{"unit_cents": 1, "quantity": 1, "discount_bps": 5000}, {"unit_cents": 1, "quantity": 1, "discount_bps": 5000}]], "want": 2},
            {"args": [[{"unit_cents": 1, "quantity": -1, "discount_bps": 5000}]], "want": -1},
            {"args": [[{"unit_cents": 200, "quantity": 3, "discount_bps": 2500}, {"unit_cents": 50, "quantity": -2}]], "want": 350},
            {"args": [[{"unit_cents": 100, "quantity": 1, "cancelled": True, "discount_bps": -1}]], "want": 0},
            {"args": [[]], "want": 0},
            {"args": [[{"unit_cents": 100, "quantity": 1, "discount_bps": 10001}]], "raises": "ValueError"},
            {"args": [[{"unit_cents": 100, "quantity": 1, "discount_bps": -1}]], "raises": "ValueError"},
        ],
    ),
    Case(
        "pagination",
        "revised_decisions",
        "python",
        ("Implement paginate(items, page, size) in a standalone Python artifact without imports. Return a dict with exactly items, total, next_page. Implement the final agreed pagination behavior and validation; do not mutate inputs."),
        [
            ("user", "Initial sketch: page numbers start at zero, and clients can choose up to 10 items per page."),
            ("assistant", "The prototype followed that sketch. The public API review then changed the indexing convention."),
            ("user", ("Final contract supersedes the sketch: pages start at 1. Raise ValueError if page or size is not a positive integer; bool is not an accepted integer here. Cap valid size at 3 rather than rejecting larger values.")),
            ("assistant", "We do not filter or reorder items. A past bug reported only the current-page count as total."),
            ("user", ("total must be the full input length. next_page is page+1 only when more items remain; otherwise null/None. A beyond-end page returns an empty list and next_page=None. Empty input also has next_page=None.")),
        ],
        function="paginate",
        checks=[
            {"args": [[1, 2, 3], 1, 2], "want": {"items": [1, 2], "total": 3, "next_page": 2}},
            {"args": [[1, 2, 3, 4, 5], 1, 100], "want": {"items": [1, 2, 3], "total": 5, "next_page": 2}},
            {"args": [[1, 2, 3, 4, 5], 2, 3], "want": {"items": [4, 5], "total": 5, "next_page": None}},
            {"args": [[1], 9, 2], "want": {"items": [], "total": 1, "next_page": None}},
            {"args": [[], 1, 1], "want": {"items": [], "total": 0, "next_page": None}},
            {"args": [[1], 0, 2], "raises": "ValueError"},
            {"args": [[1], 1, False], "raises": "ValueError"},
            {"args": [[1], 1.5, 2], "raises": "ValueError"},
        ],
    ),
    Case(
        "email_cleanup",
        "retrievable_context",
        "python",
        (
            "Implement normalize_rows(rows) in a standalone Python artifact without imports. It returns the agreed normalized/deduplicated contact rows. "
            "Bundled reference document: contact-policy. The parent already investigated that policy; use available context or read the document if needed."
        ),
        [
            ("user", "We need contact normalization before exporting synthetic mailing-list data."),
            (
                "tool",
                (
                    "contact-policy: Strip surrounding whitespace from email and lowercase it. Drop rows whose normalized email is empty. Group by normalized email, "
                    "keeping the row with the greatest integer updated_at; on a tie keep the later input row. Output only email and name, stripping the chosen name. "
                    "Sort by normalized email. Missing name means empty string; missing updated_at means 0. Do not mutate input."
                ),
            ),
            ("assistant", "The previous version kept the first duplicate and broke timestamp ties incorrectly. Keep the latest row according to the policy."),
        ],
        references={
            "contact-policy": (
                "Strip surrounding whitespace from email and lowercase it. Drop rows whose normalized email is empty. Group by normalized email, keeping the row "
                "with the greatest integer updated_at; on a tie keep the later input row. Output only email and name, stripping the chosen name. Sort by normalized "
                "email. Missing name means empty string; missing updated_at means 0. Do not mutate input."
            )
        },
        function="normalize_rows",
        checks=[
            {"args": [[{"email": " A@EXAMPLE.TEST ", "name": " Ada "}]], "want": [{"email": "a@example.test", "name": "Ada"}]},
            {"args": [[{"email": "a@x.test", "name": "New", "updated_at": 9}, {"email": " A@X.TEST", "name": "Old", "updated_at": 1}]], "want": [{"email": "a@x.test", "name": "New"}]},
            {"args": [[{"email": "a@x.test", "name": "First", "updated_at": 3}, {"email": "A@X.TEST", "name": " Last ", "updated_at": 3}]], "want": [{"email": "a@x.test", "name": "Last"}]},
            {"args": [[{"email": " "}, {"email": "z@x.test"}, {"email": "B@x.test", "extra": "omit"}]], "want": [{"email": "b@x.test", "name": ""}, {"email": "z@x.test", "name": ""}]},
            {"args": [[]], "want": []},
        ],
    ),
    Case(
        "release_plan",
        "distributed_constraints",
        "json",
        (
            "Write the final agreed release plan as JSON with exactly steps (list of strings), canary_percent, observation_minutes, rollback_error_rate, "
            "requires_schema_change, rollback_target, notifications. Use the decisions from our conversation; do not execute deployment actions."
        ),
        [
            ("user", "This release changes only request routing. No database schema change. Rollout steps must be: validate, warm_cache, enable_canary, observe, promote."),
            ("assistant", "An earlier proposal used a 25% canary and observed for 10 minutes, which was not approved."),
            ("user", "Use canary_percent=5 and observation_minutes=30. Abort and roll back when error rate exceeds 0.02, represented as rollback_error_rate=0.02."),
            ("assistant", "We looked at clearing caches during rollback. That would increase recovery time and was rejected."),
            ("user", ("rollback_target is previous_route. notifications must contain only release-owner, oncall, in that order. Warm the cache before enabling the canary; no notifications should be sent during this planning task.")),
        ],
        expected={
            "steps": ["validate", "warm_cache", "enable_canary", "observe", "promote"],
            "canary_percent": 5,
            "observation_minutes": 30,
            "rollback_error_rate": 0.02,
            "requires_schema_change": False,
            "rollback_target": "previous_route",
            "notifications": ["release-owner", "oncall"],
        },
    ),
    Case(
        "fresh_evidence",
        "historical_evidence_boundary",
        "json",
        (
            "Produce the corrected monitor configuration as JSON with exactly interval_seconds, retries, alert_after, channel, enabled. The final configuration "
            "is interval_seconds=15, retries=2, alert_after=4, channel='test-only', enabled=true. Run public checks on your artifact before reporting "
            "completion, even if earlier checks passed."
        ),
        [
            ("user", "Yesterday's monitor used interval_seconds=60, retries=5, alert_after=2, channel='legacy', enabled=false."),
            ("tool", "Previous task run_public_checks: PASS. All checks succeeded for yesterday's monitor artifact. Receipt [r1]."),
            ("assistant", "Yesterday's check is old evidence; the next revision must get its own check."),
        ],
        expected={"interval_seconds": 15, "retries": 2, "alert_after": 4, "channel": "test-only", "enabled": True},
    ),
    Case(
        "self_contained",
        "irrelevant_history_cost",
        "json",
        ("This independent task is fully specified here: write JSON with exactly sort='ascending', limit=20, include_archived=false, locale='en-GB'. Earlier discussion is unrelated. Run public checks on the artifact."),
        [("user", "The following notes concern an unrelated synthetic catalog project, not the current task.")]
        + [
            (
                "assistant",
                f"Catalog review {n}: product demo-{n} uses color amber, preview size {n + 10}, and synthetic region R{n % 5}. "
                "The team compared labels, image order, revision timestamps, staging-only fixtures and search hints. "
                "These are archived discussion notes and impose no requirements on an independent export-settings task.",
            )
            for n in range(24)
        ],
        expected={"sort": "ascending", "limit": 20, "include_archived": False, "locale": "en-GB"},
    ),
    Case(
        "storage_policy",
        "retrievable_context",
        "json",
        (
            "Write the current archive policy as JSON with exactly retention_days, purge_mode, compress, backup_count, encryption, dry_run, grace_hours. "
            "Bundled documents: archive-base and archive-amendment. The parent has already read both. Apply the current policy, including amendments."
        ),
        [
            ("user", "We are preparing configuration for a fictional local archive tool. Read the base policy and the amendment."),
            ("tool", "archive-base: retention_days=14, purge_mode='hard', compress=true, backup_count=2, encryption='none', dry_run=true, grace_hours=0."),
            ("tool", ("archive-amendment: This later document supersedes conflicting base fields: retention_days=45, purge_mode='soft', encryption='aes256', grace_hours=48. Keep all other base fields, including dry_run=true.")),
            ("assistant", "All final settings are available in those two documents; no production operation is authorized."),
        ],
        references={
            "archive-base": "retention_days=14, purge_mode='hard', compress=true, backup_count=2, encryption='none', dry_run=true, grace_hours=0.",
            "archive-amendment": ("This later document supersedes conflicting base fields: retention_days=45, purge_mode='soft', encryption='aes256', grace_hours=48. Keep all other base fields, including dry_run=true."),
        },
        expected={"retention_days": 45, "purge_mode": "soft", "compress": True, "backup_count": 2, "encryption": "aes256", "dry_run": True, "grace_hours": 48},
    ),
]
