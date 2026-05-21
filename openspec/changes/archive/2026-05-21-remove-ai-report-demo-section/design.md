## Context

The data-analyst skill's daily / weekly / monthly AI report path was wired (in change `wire-equipment-reports-real-data`) so InS is the real backend and a demo provider is registered as a permanent fallback. Today's runtime contract is:

- `_data_providers._PROVIDER_FACTORIES["daily"|"weekly"|"monthly"]` registers BOTH `demo` and `ins`.
- Resolution defaults to `demo` via `DEER_FLOW_DATA_PROVIDER`.
- `fetch_with_fallback` wraps every InS call: any `HttpProviderError` swaps in the demo provider and appends a "HTTP provider failed, fell back to demo: ..." string to `data_notes`.
- `query_*.build_result` carries `data_source` and `data_notes` into the JSON output, the KPI transforms append a precomputed `data_source_banner`, and `export_report.render_markdown` prepends a `> ✅` / `> ⚠️` line to the rendered markdown.
- Builtin DSL templates have a `data_source_banner` markdown section, and the three SOUL prompts include "必须保留首行横幅" instructions.

This dual path was introduced to keep the demo / dev environment usable while InS connectivity matured. The current incident is the opposite of what fallback was designed for: a report that should be flagged as broken silently looks valid because the demo provider always succeeds. The user has decided to remove the demo path entirely — production-grade reports come from InS or they explicitly fail.

The change touches three intertwined surfaces — provider registry, query/KPI scripts, and rendering (markdown + DSL + SOUL) — but does **not** touch the underlying `InsApiClient` / `_ins_provider` business logic. Endpoint routing (2k / 6k / 8k / 9k) and KPI mapping are left as-is.

Stakeholders: data-analyst skill maintainers, AI report agent authors, operators who deploy the sandbox image.

## Goals / Non-Goals

**Goals:**

- Make `Ins{Daily,Weekly,Monthly}Provider` the only registered provider for the three AI-report sources.
- Make any failure in the InS path (`HttpProviderError`, missing features-tool, KPI mapping gap, empty trend data, compare-period failure) surface as `{"error": ...}` on stdout instead of producing demo-tagged output.
- Strip the data-source banner from rendered markdown, KPI JSON, DSL templates, and SOUL prompts so the only signal in the report comes from the report content itself.
- Keep the InS happy-path output schema stable (existing consumers that read `current.kpis`, `hourly_runtime_rate`, `alarms`, etc. keep working) except for: `data_source` now constant `"ins"`; `data_notes` always `[]`; `data_source_banner` field gone.
- Delete dead code aggressively (`_demo_day` / `_demo_week` / `_demo_month`, `Demo*Provider` for daily/weekly/monthly, `_data_banner.py`, banner-related tests).

**Non-Goals:**

- Reworking the InS provider, `_ins_provider.py` aggregation logic, or any of the four endpoint paths.
- Touching unrelated demo providers (`trend`, `fault_context`, `failure_data`, `closure_items`, `inspection`) — `DEER_FLOW_DATA_PROVIDER` continues to gate those.
- Changing the diagnosis skills' demo fallback (e.g. `diagnosis_features.py:474` still emits `"demo_fallback"` for historical cases — that path is owned by a different capability and is out of scope per [[export_report_diagnosis_fourth_type]]).
- Adding a feature-flag to re-enable demo. The removal is intentionally one-way; the user wants the safety net gone.
- Migrating any persisted historical reports — only the runtime path is changing.

## Decisions

### D1. Drop `Demo*Provider` registration for daily/weekly/monthly instead of just defaulting to InS

The minimum-edit alternative would be to change the default mode from `demo` to `ins` and keep both providers registered. **Rejected** because:

- It leaves `Demo{Daily,Weekly,Monthly}Provider` and the `_demo_*` helpers as live code paths reachable via `DEER_FLOW_DATA_PROVIDER=demo`, which an operator could re-enable accidentally — defeating the stated goal of "removing the safety net."
- It keeps the dead-code branch in `fetch_with_fallback` (the `except HttpProviderError → demo` arm), which the user has been explicit about wanting to eliminate.
- It does not remove the banner copy, which is the visible artifact the user identified.

Chosen path: physically delete the registration calls, delete the classes, delete the `_demo_*` helpers in `query_daily/weekly/monthly.py`, and bypass `fetch_with_fallback` entirely for these three sources.

### D2. Call `get_provider(source).fetch(...)` directly instead of `fetch_with_fallback`

`fetch_with_fallback` is the helper that catches `HttpProviderError` and substitutes demo. With demo removed there's nothing to fall back to, so its purpose disappears for daily/weekly/monthly. We have two options:

- **Option A** — Keep `fetch_with_fallback` but make it raise when no `demo` mode is registered.
- **Option B** — Stop calling `fetch_with_fallback` from `query_daily/weekly/monthly.fetch_*_with_provenance` entirely; call `get_provider(source).fetch(**args)` directly and let `HttpProviderError` propagate.

Chosen: **Option B**. It is one less indirection, makes the error path explicit at the call site, and keeps `fetch_with_fallback` available for the other five sources (`trend` / `fault_context` / etc.) that still benefit from it. Option A would have left a misleading helper name in place and added a branch ("registry has no demo → re-raise") that would only ever execute for these three sources.

### D3. Make `data_source` a required key (not defaulted) downstream

Today `daily_kpi.py:377` does `payload.get("data_source", "demo_fallback")`. We will remove the default and require the field — a `KeyError` is preferable to a silent demo tag if some future regression strips the field. This converts a class of silent failures into loud failures, which is the whole point of this change.

Alternative considered: keep the default but change it to `"ins"`. **Rejected** — defaulting still hides regressions; a missing field is a bug, not a "probably ins" situation.

### D4. Delete `_data_banner.py` outright rather than reducing it to a constant

The banner exists to communicate provenance. With only one provenance possible, the banner has no informational content; reading "> ✅ 数据来源：InS 实时接入" on every report is noise. Even an empty `format_banner` that returned `""` would leave a vestigial blank line and require every caller to coalesce the empty string. The cleanest cut is to delete the file and remove all call sites, including:

- `daily_kpi.py` lines that set `result["data_source_banner"]`
- `weekly_kpi.py` / `monthly_kpi.py` equivalents
- `export_report.py` markdown rendering that prepends the banner
- builtin DSL template sections named `data_source_banner`
- SOUL prompt clauses about "保留首行横幅"

Risk: callers of `format_banner` outside the AI report path could break. We will grep for `_data_banner` / `format_banner` / `data_source_banner` across the repo before deletion and confirm no other capability depends on them.

### D5. Keep the InS provider's existing `HttpProviderError` taxonomy

`Ins{Daily,Weekly,Monthly}Provider` already raises `HttpProviderError` for: features-tool missing, device not found, empty trend rows, KPI mapping gap, compare-period failure. We will not introduce a new exception type. The error message strings the InS provider already produces are descriptive enough to land in `{"error": "HttpProviderError: <message>"}` and be diagnosed.

Trade-off: `HttpProviderError` is named after the obsolete `HttpProvider`. We considered renaming it but **decided against** — that's a separate concern, and renaming would force every other capability's tests to update. We accept the slightly inaccurate name as the cost of staying focused.

### D6. Tests: rewrite the daily/weekly/monthly InS tests, delete the demo & banner tests

Concretely:

- `test_ai_report_daily_ins_provider.py` and the weekly/monthly equivalents currently include both "demo fallback when env unset" and "InS success" cases. We will delete the demo cases and add new cases asserting that `HttpProviderError` propagates as `{"error": ...}`.
- `test_ai_report_daily_query.py` (and weekly/monthly equivalents) currently smoke-test the demo output shape. We will rewrite their fixtures to mock `Ins{Daily,Weekly,Monthly}Provider.fetch` so the same downstream-shape assertions hold, but against InS-tagged payloads.
- `test_ai_report_daily_export.py::test_*_banner` (and weekly/monthly) will be deleted — there is no banner to test.
- `test_builtin_report_templates.py` already validates the DSL templates; the new assertion is that no template section references `data_source_banner`.

## Risks / Trade-offs

- **[Risk] An operator runs the change in local sandbox mode and every report fails** → Mitigation: the InS provider's `HttpProviderError("features-tool not available: <reason>")` is unmistakable, and the documentation update in `backend/docs/HTTP_CONNECTORS.md` will explicitly state that the docker sandbox image is required. Operators who depend on the previous "silent demo fallback" behavior will see immediate failures and must switch to the supported sandbox image or accept the breakage.
- **[Risk] Unmapped KPI keys (e.g. `output`, `energy_consumption`) now fail the whole report instead of falling back** → Mitigation: this is the explicit goal of the change. We will document the supported KPI set in `backend/docs/HTTP_CONNECTORS.md` and update the AI report templates / SOUL prompts to list only mapped KPIs so the LLM does not request unmapped keys. Adding new KPIs is a separate future change.
- **[Risk] Diagnosis capabilities also use `_data_banner` (cross-capability coupling)** → Mitigation: grep `_data_banner` / `format_banner` before deletion. If diagnosis depends on it, we keep the helper file but remove only the AI report call sites. [[export_report_diagnosis_fourth_type]] indicates the diagnosis report is a parallel path; we will not couple to it.
- **[Risk] Downstream consumers (frontend, archived runs) expect `data_source_banner` in KPI output JSON** → Mitigation: search the frontend / archived-runs schema for `data_source_banner`; if used, treat the field as optional in those consumers before this change lands.
- **[Trade-off] Loud failures during demos** — Previously a demo / dev environment could always show a polished report. After this change, demos without InS access show an error. We accept this; the user has explicitly judged "honesty over polish" for production-grade AI reports.

## Migration Plan

1. **Pre-deletion grep pass** — confirm no caller outside the AI report path depends on `_data_banner`, `Demo{Daily,Weekly,Monthly}Provider`, `_demo_day`/`_demo_week`/`_demo_month`, or the `data_source_banner` field.
2. **Registry / providers** — delete `register_provider("daily", "demo", ...)`, `register_provider("weekly", "demo", ...)`, `register_provider("monthly", "demo", ...)`, delete the three `Demo*Provider` classes from `_data_provider_impls.py`, delete the `_demo_*` helpers from `query_daily.py` / `query_weekly.py` / `query_monthly.py`.
3. **Query scripts** — in `fetch_day_with_provenance`, `fetch_week_with_provenance`, `fetch_month_with_provenance` call `get_provider(...).fetch(...)` directly; remove the `_with_provenance` `compare_src != "demo_fallback"` "downgrade everything to demo" branches; remove the `fetch_with_fallback` import where unused.
4. **KPI transforms** — remove `data_source_banner` field from `daily_kpi.py:380`, weekly/monthly equivalents; remove default in `payload.get("data_source", "demo_fallback")` → `payload["data_source"]`.
5. **Rendering** — delete the banner-prepending logic in `export_report.render_markdown`; delete `_data_banner.py` if no remaining call sites.
6. **DSL templates** — remove the `data_source_banner` markdown sections from `agents/builtin/report-templates/{daily,weekly,monthly}-equipment/default.yaml`.
7. **SOUL prompts** — remove the "保留首行横幅" / "demo" / "fallback" instructions from `agents/builtin/ai-report--{daily,weekly,monthly}/SOUL.md`.
8. **Docs** — update `backend/docs/HTTP_CONNECTORS.md` and `backend/CLAUDE.md` to: drop the `DEER_FLOW_DATA_PROVIDER` switch for AI reports; state that InS connectivity is mandatory; list the supported KPI keys.
9. **Tests** — delete demo / banner assertions, rewrite InS provider tests to assert error propagation, run `pytest backend/tests/test_ai_report_*` and `test_builtin_report_templates.py`.
10. **Validate** — `openspec validate remove-ai-report-demo-section --strict`.

**Rollback**: this is a one-way change — there is no rollback flag. If a regression appears, the fix is forward (e.g. extend KPI mapping, fix InS auth) rather than restoring the demo path. The user is making that call explicitly.

## Open Questions

- Does any non-AI-report consumer (frontend, archived run viewer, MCP report tool) read `data_source_banner` from KPI JSON? — Answered by the pre-deletion grep in step 1; if yes, those consumers stop receiving the field and we update them accordingly.
- Should the `error` field shape change from `{"error": "<ExceptionType>: <message>"}` to a structured error (e.g. `{"error": {"type": ..., "message": ..., "hint": ...}}`)? — Out of scope here; the change keeps the existing error shape for consistency with other query scripts.
