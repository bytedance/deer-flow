# Issue triage for maintainers

`scripts/score_issues.py` suggests an issue's priority and next action for a
maintainer to review. Priority measures the reported impact; implementation
difficulty and design readiness determine routing independently. The script
does not use later merge outcomes as evidence.

## Run

Set `TRIAGE_LLM_API_KEY` or `OPENAI_API_KEY` in your environment, then run from the
repository root:

```bash
python scripts/score_issues.py --repo bytedance/deer-flow --limit 20 \
  --output-json results.json --output-md report.md
python scripts/score_issues.py --input-json issues.json --output-md report.md
```

Prefer the environment variables over `--api-key`, since command-line arguments
may be visible in process listings.

The default is one Responses API call per issue using `gpt-6.1-terra` with
`medium` reasoning and a strict eight-field schema. The full title and body are
sent; author, labels and formatting signals are not added to the model input.
The output token limit is 6,500, including reasoning; actual usage is retained
under `usage` in the JSON report. Transient network failures and HTTP
429/500/502/503/504 responses can be retried up to three attempts. Invalid model
answers are flagged without an extra repair call.

`--model`, `--base-url` and `--reasoning-effort high` override the defaults.
`TRIAGE_LLM_MODEL`, `TRIAGE_LLM_BASE_URL` and `OPENAI_BASE_URL` are also supported.
For compatible services exposing Chat Completions, use
`--api-format chat-completions`; that service must support the requested strict
JSON schema. Reasoning effort is sent for recognized GPT-5/GPT-6/o-series model
names. No silent fallback to another model or scoring policy is performed.

`--offline` previews the report without assessing priorities. Every preview
entry is marked for manual review and receives no suggested labels. A missing
key requires this explicit option. The legacy `--mode` option is accepted with
a deprecation notice; all issue types now use the same policy.

## Read the report

The model returns `trigger_quote`, `impact_quote`, `kind`, `area`,
`extension_hook`, `priority`, `route` and `reason_zh`. Each quote field holds up
to two exact source spans, each at most 160 characters. JSON preserves those
quotes unchanged; Markdown escapes markup and displays line breaks.

Priorities are `P0` through `P3`, `Needs-Info` (impact cannot be assessed), and
`Not-Applicable` (a finding confined to an unmerged PR). Numeric priorities sort
first, followed by the two nonnumeric states; issue number breaks ties. There
is no additive score or implementation-ease bonus.

Routes are `fix`, `investigate`, `assign`, `design`, `needs_info`, `extension`,
`governance`, `discussion` and `pr_review`. Governance and general questions
have their own routes. An extension recommendation requires a recognized hook:
`MCP`, `Skill`, `SandboxProvider`, `model_provider` or `packaged_extension`.

The script checks the schema, exact quote provenance, extension hook/action
consistency, and unmerged-PR and unknown-request routing. Failures remain in the
report with **需人工复核**, `scoring.needs_review: true`, and specific
`scoring.validation_errors`. Returned facts remain under `llm`, including
invalid quotes, so a maintainer can inspect what went wrong. Failed or
incomplete API responses are also visible as unassessed entries.
An unexpected per-issue exception also retains that issue and all completed
results in both reports. The CLI lists affected issue numbers on stderr and
exits with status 1 after writing the reports; it never labels those entries.

Passing these checks establishes source provenance and structural consistency.
It does not establish that the priority is correct or that a named extension
hook can implement the whole request. Maintainers make the final decision.

## Labels

Reports are read-only by default. Preview eligible label operations with:

```bash
python scripts/score_issues.py --input-json issues.json \
  --repo bytedance/deer-flow --dry-run
```

`--apply-labels` explicitly enables writes through `gh`. Only labels declared
in `.github/labels.yml` are eligible. Entries requiring manual review, offline
previews, `Needs-Info`, and `Not-Applicable` receive no labels. Existing live
priority labels are preserved. JSON input requires `--repo`, and every issue's
URL and number must match the target before any labels are written.

Compared with the earlier weighted scorer, JSON reports no longer contain
`stage0`, `total_score`, `breakdown`, `fast_track_ready`, `scene_zh` or `scope_zh`.
Consumers should use `scoring.priority`, `scoring.route`, `scoring.needs_review`
and the source quotes. Input labels are retained as `existing_labels`.
