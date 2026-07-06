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

## Chart generation (planned)

The current pipeline (`render_markdown.py` + `render_docx.py`) emits HTML
tables and Chinese narrative only — no charts. This section describes the
planned integration of `skills/public/matplotlib/` so each report gets a
static PNG companion to its table.

### Why matplotlib

| Candidate | Output | Fit for embedded reports |
|---|---|---|
| matplotlib | PNG/SVG (static) | Matches markdown `<img>` + python-docx `add_picture` directly |
| pyecharts-viz | HTML by default; PNG only via `snapshot_selenium` + browser | Skill is "examples generator" with no data ingest API |
| echart-skill | Single-file HTML (interactive ECharts) | Designed for live dashboards; no PNG export path; would duplicate chatbi-report's data layer |

matplotlib ships `fonts/wqy-microhei.ttc` for Chinese, needs no server,
no browser, no DuckDB — minimum surface area for chatbi-report's
deterministic render layer.

### Pipeline change: new Step 4.5 `chart-gen`

Insert between `Step 4 assemble-wide` and `Step 6 extract-ir` in
`SKILL.md` and `references/pipeline.md`:

```bash
python /mnt/skills/public/chatbi-report/scripts/chart_gen.py \
  --wide  /mnt/user-data/outputs/<stem>.wide.json \
  --out   /mnt/user-data/outputs/<stem>.charts/
```

Behavior: walk each `Report` in wide.json and infer a chart type from the
`Th` schema:

- 时间列（如 2023/2024/2025，多级表头含 `period`）→ 折线图（趋势）
- 类别列 + 数值列 → 柱状图（横向对比）
- 占比列（`data-unit="%"`）→ 饼图

Output:

```text
/mnt/user-data/outputs/<stem>.charts/<report_idx>.<chart_type>.png
```

`chart_gen.py` is deterministic; no LLM involved. It must read `data_unit`
from `<th data-unit=...>` for axis labels and reuse the Decimal values
already produced by `assemble-wide` (do not re-round).

### Renderer edits

`scripts/render_markdown.py` — before each report's `<table>`, prepend a
markdown image link:

```markdown
![<report.title>](<stem>.charts/<report_idx>.bar.png)
```

`scripts/render_docx.py` — at the same insertion point, embed natively
via `docx.shared.Inches(<width>)` + `doc.add_picture(<png path>)` so the
generated DOCX has no external file dependency at read time.

### Out of scope

- Interactive charts in markdown (chatbi-report targets static docx output)
- 3D charts (matplotlib covers them; defer until a real report needs one)
- LLM-driven chart-type selection (Step 4.5 uses header schema only)

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Step 3 query fails or all cells show ⚠️QUERY_FAILED | SQLBot unreachable or returned no matching data | Check `SQLBOT_BASE_URL`; `curl ${SQLBOT_BASE_URL}/api/v1/indicator/query-report-info` |
| All idx marked ⚠️QUERY_FAILED | `data_dt` mismatch between MD tbody and SQLBot response | Verify `> 时期:` block matches what SQLBot returns |
| Compute column skipped | AST/signature/smoke failure | Read step 8a stderr; column is marked `⚠️COMPUTE_FAILED` in outputs |
| DOCX shows English | `data-idx` attribute missing on real-indicator `<th>` | Re-run `md_lint.py` for the exact fix |
| Sandbox can't import pandas | Container missing deps | Restart with `make dev` (the gateway image ships pandas) |
