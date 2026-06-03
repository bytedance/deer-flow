## 1. Restore `_ins_provider.py` sync wrappers

- [x] 1.1 Restore `fetch_monthly_payload` implementation — replace `NotImplementedError` with `_run_async(_async_fetch_payload(period_kind="range", period_args={"start": month_start, "end": month_end}, ...))`
- [x] 1.2 Restore `fetch_daily_series_payload` sync wrapper — remove `NotImplementedError`, restore original `_run_async(...)` call (surgical: `fetch_daily_payload`/`fetch_weekly_payload` skipped — not needed by monthly report)

## 2. Add `InsMonthlyProvider`

- [x] 2.1 Create `InsMonthlyProvider` class in `_data_provider_impls.py` that calls `_ins_provider.fetch_daily_series_payload` for the full month date range
- [x] 2.2 Register `InsMonthlyProvider` as `monthly` source's `ins` mode via `register_provider("monthly", "ins", InsMonthlyProvider)`
- [x] 2.3 Add `INS_SUCCESS` as `data_source` tag in the returned `ProviderResult`

## 3. Modify `_resolve_mode` in `_data_providers.py`

- [x] 3.1 Pin `_INS_SOURCES = {"daily", "weekly", "monthly"}` to always resolve to `"ins"` — these ignore `DEER_FLOW_DATA_PROVIDER`
- [x] 3.2 Ensure `_PROVIDER_FACTORIES["monthly"]` has `"ins"` key after provider registration

## 4. Write tests

- [x] 4.1 Add tests for `InsMonthlyProvider.fetch()` with mocked `fetch_daily_series_payload` — verify correct daily entries structure and data_source tag
- [x] 4.2 Add tests for `_resolve_mode` — verify monthly/daily/weekly pinned to "ins"
- [x] 4.3 Add tests for `get_provider("monthly")` returning `InsMonthlyProvider`
- [x] 4.4 Add regression test: `fetch_monthly_payload` no longer raises `NotImplementedError`

## 5. Verify & clean up

- [x] 5.1 Run existing monthly report test suite — 19/20 pass (1 pre-existing encoding issue in `test_weekly_entries_still_parse`)
- [x] 5.2 `InsMonthlyProvider` uses direct InS path without spawning subprocesses
- [x] 5.3 Default behavior uses direct InS path (`_INS_SOURCES` hardcoded to "ins")
