# chatbi-report skill

Generate structured JSON, backfilled Markdown, and DOCX from a Markdown
report sample whose `<th>` cells carry a `data-idx` attribute pointing
to a SQLBot indicator plus a Chinese display name.

## Quickstart (operator)

1. Ensure `.env` has `SQLBOT_BASE_URL` set (no API key required):
   ```bash
   cp skills/public/chatbi-report/.env.example .env
   echo "SQLBOT_BASE_URL=http://your-sqlbot:9070" >> .env
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

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| F17 error at step 5 | SQLBot unreachable | Check `SQLBOT_BASE_URL`; `curl ${SQLBOT_BASE_URL}/api/v1/indicator/query-report-info` |
| All idx marked ⚠️QUERY_FAILED | `data_dt` mismatch between MD tbody and SQLBot response | Verify `> 时期:` block matches what SQLBot returns |
| Compute column skipped | AST/signature/smoke failure | Read `report.query.log`; column is marked `compute_*_failed` in JSON |
| DOCX shows English | `data-idx` attribute missing on real-indicator `<th>` | Re-run `md_lint.py` for the exact fix |
| Sandbox can't import pandas | Container missing deps | Restart with `make dev` (the gateway image ships pandas) |
