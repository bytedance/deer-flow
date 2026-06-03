# Agent SOUL Simplification

## ADDED Requirements

### Requirement: AI report SOUL.md only has DSL path

The Agent SOUL.md files for `ai-report--daily`, `ai-report--weekly`, and `ai-report--monthly` SHALL contain only the DSL template platform path. All fallback/downgrade logic SHALL be removed, including:

- The `启动决策` section that checks `report_template_get` return value and branches to fallback
- The `Fallback 路径触发场景` section
- The `DSL 优先 + Fallback 双轨` section header and its `> **重要**` preamble
- All hardcoded fallback form JSON blocks (Round 1 scope form, Round 1.5 device-selector-multi, Round 2 KPI form, Round 2 callback generate logic with `query_daily.py` shell command)
- Instructions to call `report_template_record_fallback`
- Instructions to display "正在使用兼容模式生成报告"

#### Scenario: Daily report SOUL has no fallback form blocks

- **WHEN** `ai-report--daily/SOUL.md` is loaded
- **THEN** it does NOT contain `"callback_id": "daily-report-scope"` or `"callback_id": "daily-report-equipment"` or `"callback_id": "daily-report-confirm"`

#### Scenario: Daily report SOUL has no fallback decision logic

- **WHEN** `ai-report--daily/SOUL.md` is loaded
- **THEN** it does NOT contain `report_template_record_fallback`, `正在使用兼容模式`, `Fallback 路径`, or `--scope-filter`

#### Scenario: Weekly report SOUL has no fallback path

- **WHEN** `ai-report--weekly/SOUL.md` is loaded
- **THEN** it contains no fallback form blocks or decision branches referencing `report_template_get` → fallback

#### Scenario: Monthly report SOUL has no fallback path

- **WHEN** `ai-report--monthly/SOUL.md` is loaded
- **THEN** it contains no fallback form blocks or decision branches referencing `report_template_get` → fallback

### Requirement: DSL failures surface as errors, not fallbacks

When the DSL template platform path fails (e.g., `report_template_get` returns no result, `report_template_prepare_run` fails, or `report_template_export` fails), the Agent SHALL report the error to the user via `markdown` component rather than silently falling back to hardcoded forms.

#### Scenario: Template not found surfaces error

- **WHEN** `report_template_get(template_id="daily-equipment")` returns no result
- **THEN** the Agent renders a `markdown` component with an error message like "日报模板未安装，请联系管理员" and stops

#### Scenario: Data step failure surfaces error

- **WHEN** `report_template_run_data_steps` fails with `RUN_NOT_FOUND` or `INTERNAL` error
- **THEN** the Agent renders the error via `markdown` and does NOT attempt to generate a report through any other path
