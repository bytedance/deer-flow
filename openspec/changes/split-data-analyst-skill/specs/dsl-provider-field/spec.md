# DSL Provider Field

## MODIFIED Requirements

### Requirement: DataStep schema accepts optional provider field

The `DataStep` model in `report_templates/schema.py` SHALL accept an optional `provider` field of type `str | None` with default `None`. Valid values are `"platform"`, `"ins"`, `"demo"`, and `"http"`. The `provider` field SHALL be an explicit whitelisted field alongside existing `id`, `kind`, `name`, `args`, `outputs` fields.

#### Scenario: DataStep parses provider field

- **WHEN** a DSL YAML `data_steps` entry includes `provider: "platform"`
- **THEN** the parsed `DataStep` model has `provider == "platform"` and validation passes

#### Scenario: DataStep without provider defaults to None

- **WHEN** a DSL YAML `data_steps` entry omits `provider`
- **THEN** the parsed `DataStep` model has `provider is None` and validation passes

#### Scenario: Invalid provider value rejected

- **WHEN** a DSL YAML `data_steps` entry sets `provider: "invalid_value"`
- **THEN** the validator rejects the template with a clear error message listing valid values

### Requirement: data_runner injects env vars based on provider

The `run_script()` function in `report_templates/runtime/data_runner.py` SHALL accept an optional `provider` parameter (`str | None`, default `None`). When `provider` is not `None`, the function SHALL inject environment variables into the subprocess:

- `provider == "platform"` → `USE_PLATFORM=true`
- `provider == "ins"` → `USE_PROVIDER=ins`
- `provider == "demo"` → `USE_PROVIDER=demo`
- `provider == "http"` → `USE_PROVIDER=http`

#### Scenario: provider=platform injects USE_PLATFORM=true

- **WHEN** `run_script(provider="platform", ...)` is called and the script executes via subprocess
- **THEN** the subprocess environment contains `USE_PLATFORM=true`

#### Scenario: provider=None injects no env

- **WHEN** `run_script(provider=None, ...)` is called (or `provider` is omitted)
- **THEN** the subprocess environment does NOT contain `USE_PLATFORM` or `USE_PROVIDER`

#### Scenario: provider=ins injects USE_PROVIDER=ins

- **WHEN** `run_script(provider="ins", ...)` is called
- **THEN** the subprocess environment contains `USE_PROVIDER=ins`

### Requirement: run_data_steps_and_transforms passes provider from DSL step

The `run_data_steps_and_transforms()` function SHALL extract `provider` from each `data_steps[]` entry dict and pass it to `run_script()`. Steps that omit `provider` in the DSL SHALL call `run_script()` with `provider=None`.

#### Scenario: Provider extracted from DSL step and passed through

- **WHEN** `run_data_steps_and_transforms()` processes a step with `"provider": "platform"`
- **THEN** it calls `run_script(..., provider="platform")` for that step

#### Scenario: Missing provider in DSL step passes None

- **WHEN** `run_data_steps_and_transforms()` processes a step without a `provider` key
- **THEN** it calls `run_script()` without a `provider` argument (or `provider=None`)

## ADDED Requirements

### Requirement: DSL template name field uses per-report-type skill namespace

The `name:` field in DSL template `data_steps` entries SHALL use the new per-report-type skill namespaces instead of the monolithic `data-analyst/` namespace. Specifically:

- `daily-equipment/default.yaml` SHALL use `daily-report/list_equipment`, `daily-report/query_daily`, `daily-report/daily_kpi`
- `weekly-equipment/default.yaml` SHALL use `weekly-report/list_equipment`, `weekly-report/query_weekly`, `weekly-report/weekly_kpi`
- `monthly-equipment/default.yaml` SHALL use `monthly-report/list_equipment`, `monthly-report/query_monthly`, `monthly-report/monthly_kpi`

Export steps SHALL similarly reference `daily-report/export_report`, `weekly-report/export_report`, and `monthly-report/export_report` respectively.

#### Scenario: Daily DSL template references daily-report skill

- **WHEN** `agents/builtin/report-templates/daily-equipment/default.yaml` is parsed
- **THEN** all `name:` fields in `data_steps` use the `daily-report/` prefix
- **AND** no `name:` field uses the `data-analyst/` prefix

#### Scenario: Weekly DSL template references weekly-report skill

- **WHEN** `agents/builtin/report-templates/weekly-equipment/default.yaml` is parsed
- **THEN** all `name:` fields in `data_steps` use the `weekly-report/` prefix
- **AND** no `name:` field uses the `data-analyst/` prefix

#### Scenario: Monthly DSL template references monthly-report skill

- **WHEN** `agents/builtin/report-templates/monthly-equipment/default.yaml` is parsed
- **THEN** all `name:` fields in `data_steps` use the `monthly-report/` prefix
- **AND** no `name:` field uses the `data-analyst/` prefix

### Requirement: Agent SOUL.md script paths use per-report-type skill directories

The three Agent SOUL.md files SHALL reference scripts at their new skill directories:

- `ai-report--daily/SOUL.md` SHALL use `/mnt/skills/custom/daily-report/scripts/` paths
- `ai-report--weekly/SOUL.md` SHALL use `/mnt/skills/custom/weekly-report/scripts/` paths
- `ai-report--monthly/SOUL.md` SHALL use `/mnt/skills/custom/monthly-report/scripts/` paths

#### Scenario: Daily SOUL.md references daily-report paths

- **WHEN** `agents/builtin/ai-report--daily/SOUL.md` is loaded
- **THEN** all `/mnt/skills/custom/` paths reference `daily-report/scripts/`
- **AND** no path references `data-analyst/scripts/`

#### Scenario: Weekly SOUL.md references weekly-report paths

- **WHEN** `agents/builtin/ai-report--weekly/SOUL.md` is loaded
- **THEN** all `/mnt/skills/custom/` paths reference `weekly-report/scripts/`
- **AND** no path references `data-analyst/scripts/`

#### Scenario: Monthly SOUL.md references monthly-report paths

- **WHEN** `agents/builtin/ai-report--monthly/SOUL.md` is loaded
- **THEN** all `/mnt/skills/custom/` paths reference `monthly-report/scripts/`
- **AND** no path references `data-analyst/scripts/`
