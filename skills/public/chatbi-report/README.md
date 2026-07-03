# chatbi-report skill

Generate structured JSON, backfilled Markdown, and DOCX from a Markdown
report sample whose `<th>` cells carry a `data-idx` attribute pointing
to a SQLBot indicator plus a Chinese display name.

## Quickstart (operator)

1. Current default is mock SQLBot data. No `SQLBOT_BASE_URL` is required for the bundled demo fixture:
   ```text
   skills/public/chatbi-report/example/mock_sqlbot/profit_yoy.json
   ```
2. Bring up the gateway (no extra setup — the skill is auto-discovered):
   ```bash
   make dev
   ```
3. Upload your MD sample in the chat UI and say "生成报表" (or trigger
   the skill any other way listed in `SKILL.md`).

## Layout

```
skills/public/chatbi-report/
├── SKILL.md              # skill entry point (loaded by SkillActivationMiddleware)
├── README.md             # this file
├── .env.example          # SQLBOT_BASE_URL (no API key per 2026-06-23 spec)
├── scripts/
│   ├── retry.py
│   ├── sqlbot_client.py
│   ├── md_lint.py
│   ├── parse_md.py
│   ├── compute.py            # IR + codegen + validators
│   ├── unit_conversion.py    # Decimal math
│   ├── render_markdown.py
│   ├── render_docx.py
│   ├── report_style.json
│   └── assemble_status.py
└── prompts/
    └── compute_codegen.md    # LLM system prompt + few-shot
```

## SQLBot query mode

The skill is temporarily configured to use mock SQLBot data in `SKILL.md` Step 3:

```bash
python /mnt/skills/public/chatbi-report/scripts/sqlbot_client.py query \
  --parsed /mnt/user-data/outputs/<stem>.parsed.json \
  --mock \
  --out /mnt/user-data/outputs/<stem>.query.json
```

`--mock` uses the bundled fixture:

```text
/mnt/skills/public/chatbi-report/example/mock_sqlbot/profit_yoy.json
```

Use a different fixture with `--mock-fixture`:

```bash
python /mnt/skills/public/chatbi-report/scripts/sqlbot_client.py query \
  --parsed /mnt/user-data/outputs/<stem>.parsed.json \
  --mock-fixture /mnt/user-data/uploads/custom_sqlbot_fixture.json \
  --out /mnt/user-data/outputs/<stem>.query.json
```

To switch to the real SQLBot REST API:

1. Remove `--mock` from Step 3 in `SKILL.md`.
2. Set `SQLBOT_BASE_URL` in the runtime environment, for example:
   ```bash
   SQLBOT_BASE_URL=http://your-sqlbot:9070
   ```
3. Keep the same `query` command shape:
   ```bash
   python /mnt/skills/public/chatbi-report/scripts/sqlbot_client.py query \
     --parsed /mnt/user-data/outputs/<stem>.parsed.json \
     --out /mnt/user-data/outputs/<stem>.query.json
   ```

Real mode posts to:

```text
${SQLBOT_BASE_URL}/api/v1/indicator/query-report-info
```

No API key or Authorization header is used by the current client.

## Tests

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python -m pytest skills/public/chatbi-report/scripts/tests/ -v
python -m pytest backend/tests/chatbi_report/ -v   # integration scenarios
```

## MD contract (recap)

`<th>` cells have one of three shapes:

| Shape | Meaning | Renders as |
|---|---|---|
| `<th data-idx="BAS_0263" data-unit="个">贷款收单商户数</th>` | Real indicator (chatbi main path) | Chinese name in header, no SQLBot lookup |
| `<th data-unit="%">{{收单商户同比}}</th>` | Computed column | LLM-generated pandas code |
| `<th data-unit="个">{{BAS_0263}}</th>` | Old-style placeholder (chatbi legacy) | Falls back to SQLBot idx_name lookup |

The third form is accepted with a lint WARN — see `scripts/md_lint.py`
for the full rule list.

## Chart generation

Charts are declared explicitly with `> 图表:` blocks in the template; no
schema-based inference. See `SKILL.md` and Step **8c.5 chart-gen** in
`references/pipeline.md`.

Supported chart types: `line`, `bar`, `pie`, `bar_line` (dual axis with
left bars + right lines). Series modes: `行社` (one series per org row),
`指标` (one series per metric, aggregated when multiple orgs), or omitted
for a single aggregated series.

Example:

```md
> 图表:
>   标题: 利润总额趋势
>   类型: line
>   x轴: 时期
>   y轴: 利润总额
>   系列: 行社
>   单位: 万元
>   输出: profit-trend
```

`chart_gen.py` runs after `apply-computed` (Step 8c.5) so computed columns
can be charted. It writes PNG files to `<stem>.charts/` plus a `<stem>.charts.json`
manifest; renderers consume only the manifest via `--charts-manifest`.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Step 3 query fails or all cells show ⚠️QUERY_FAILED | SQLBot unreachable or returned no matching data | Check `SQLBOT_BASE_URL`; `curl ${SQLBOT_BASE_URL}/api/v1/indicator/query-report-info` |
| All idx marked ⚠️QUERY_FAILED | `data_dt` mismatch between MD tbody and SQLBot response | Verify `> 时期:` block matches what SQLBot returns |
| Compute column skipped | AST/signature/smoke failure | Read step 8a stderr; column is marked `⚠️COMPUTE_FAILED` in outputs |
| DOCX shows English | `data-idx` attribute missing on real-indicator `<th>` | Re-run `md_lint.py` for the exact fix |
| Sandbox can't import pandas | Container missing deps | Restart with `make dev` (the gateway image ships pandas) |
