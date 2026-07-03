# chatbi-report Template and Troubleshooting Reference

Read this when validating templates, explaining user fixes, switching SQLBot modes, or diagnosing failures.

## Markdown template contract

`<th>` cells have one of three shapes:

| Shape | Meaning | Renders as |
|---|---|---|
| `<th data-idx="BAS_0263" data-unit="个">贷款收单商户数</th>` | Real indicator | Chinese name in header, value from SQLBot |
| `<th data-unit="%">{{收单商户同比}}</th>` | Computed column | value from generated compute code |
| `<th data-unit="个">{{BAS_0263}}</th>` | Old-style placeholder | legacy fallback, lint warning |

Required context blocks:

```markdown
> 机构:
>   branch_num=27020199; branch_short_name=王益联社
> 时期: time_info=["2025", "2024"]
```

Optional computed columns:

```markdown
> 计算:
>   利润同比 = (BAS_0263[current] - BAS_0263[yoy_same]) / BAS_0263[yoy_same]
>   利润同比.示例: BAS_0263[current=1420, yoy_same=1200] -> 0.1833
```

Optional descriptions:

```markdown
> 描述:
>   请基于表格数据生成经营分析描述，重点关注利润总额同比变化、与铜川平均值和全省平均值的对比，并给出盈利能力判断。
```

Do not modify the uploaded source template during a run. If the user rejects compute or description checkpoints, tell them what block to edit and rerun.

## SQLBot modes

Default Step 3 uses mock data:

```bash
python /mnt/skills/public/chatbi-report/scripts/sqlbot_client.py query \
  --parsed /mnt/user-data/outputs/<stem>.parsed.json \
  --mock \
  --out /mnt/user-data/outputs/<stem>.query.json
```

Default fixture:

```text
/mnt/skills/public/chatbi-report/example/mock_sqlbot/profit_yoy.json
```

Use another fixture with `--mock-fixture`.

For real SQLBot mode:

1. Remove `--mock` from Step 3.
2. Set `SQLBOT_BASE_URL` in runtime env.
3. Keep the same command shape without `--mock`.

Endpoint:

```text
${SQLBOT_BASE_URL}/api/v1/indicator/query-report-info
```

Current client uses no API key or Authorization header.

## Failure handling

- Continue-capable steps `3`, `8a`, and `8d` must still tell the user what failed and why the pipeline continues.
- Checkpoint stops write `status=error`, `error_class=USER_ABORTED`, and the checkpoint `exit_step`.
- Blocking steps `1`, `2`, `4`, and `9` stop with the raw error summary and a concrete fix.

## Common symptoms

| Symptom | Likely cause | Fix |
|---|---|---|
| Step 3 query fails or cells show `⚠️QUERY_FAILED` | SQLBot unreachable or no matching data | Check `SQLBOT_BASE_URL`; verify SQLBot response |
| All idx show `⚠️QUERY_FAILED` | `data_dt` mismatch between tbody and SQLBot response | Verify `> 时期:` matches SQLBot periods |
| Compute column is `⚠️COMPUTE_FAILED` | AST/signature/smoke/example validation failed | Read Step 8a stderr; fix `> 计算:` block and rerun if needed |
| Description is `⚠️DESCRIPTION_FAILED` | description generation failed twice | Fix `> 描述:` prompt and rerun if needed |
| DOCX shows English or wrong header | missing `data-idx` or malformed header cell | Run `md_lint.py` and fix template |
| Sandbox cannot import pandas | runtime image/deps stale | restart with `make dev` |
| Chart missing in report | No `> 图表:` block or manifest not passed to renderer | Add chart block; check Step 8c.5 output; pass `--charts-manifest <stem>.charts.json` to renderers |
| Chart shows `CHART_PARTIAL` | Axis label unmatched or ambiguous | Use exact header text from `<th>` |
| Chinese labels show boxes in chart | CJK font not loaded | Verify `/mnt/skills/public/matplotlib/fonts/wqy-microhei.ttc` exists |

## Do not do these during normal report runs

- Do not edit `/mnt/skills/public/chatbi-report/SKILL.md`, scripts, or prompts.
- Do not edit `/mnt/user-data/uploads/<file>.md`.
- Do not add analysis dimensions, columns, or interpretation unless the user asks.
- Do not paste raw `status.json` or raw script OK lines to the user.
