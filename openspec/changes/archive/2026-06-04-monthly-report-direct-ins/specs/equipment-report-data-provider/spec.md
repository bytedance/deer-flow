## MODIFIED Requirements

### Requirement: Provider registration for daily / weekly / monthly equipment reports

The data-analyst skill SHALL register `daily`, `weekly`, and `monthly` as named provider sources in `_data_providers._PROVIDER_FACTORIES`. Each source SHALL support both a `platform` mode (integrations CLI bridge) and an `ins` mode (direct InS API calls within the sandbox process). The `DEER_FLOW_DATA_PROVIDER` environment variable SHALL control which mode is selected when no explicit mode is passed: when set to `"ins"`, the direct `ins` mode is used; when unset or set to any other value, `"platform"` mode is used as the default. The legacy `demo` mode entries for these three sources MUST NOT be registered, and `Demo{Daily,Weekly,Monthly}Provider` classes (and their backing `_demo_*` helpers in the query scripts) MUST NOT exist.

#### Scenario: Platform mode is the default

- **WHEN** `get_provider("monthly")` (or `"daily"` / `"weekly"`) is called with `DEER_FLOW_DATA_PROVIDER` unset
- **THEN** the registry returns the `Platform{Monthly,Daily,Weekly}Provider` instance

#### Scenario: Ins mode selected via env var

- **WHEN** `DEER_FLOW_DATA_PROVIDER=ins` is set and `get_provider("monthly")` runs
- **THEN** the registry returns the `DirectInsMonthlyProvider` instance

#### Scenario: Explicit mode overrides env var

- **WHEN** `DEER_FLOW_DATA_PROVIDER=ins` is set but `get_provider("monthly", mode="platform")` is called
- **THEN** the registry returns the `PlatformMonthlyProvider` instance — explicit mode takes precedence over the env var

#### Scenario: Legacy demo mode raises

- **WHEN** code calls `get_provider("monthly", mode="demo")` (or daily / weekly)
- **THEN** `get_provider` raises `KeyError` indicating no provider is registered for mode `demo`

#### Scenario: Both modes are registered

- **WHEN** `list_registered()` is called
- **THEN** `list_registered()["monthly"]` contains `["ins", "platform"]` (both modes available)
