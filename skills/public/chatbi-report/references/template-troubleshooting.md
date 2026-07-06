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

The `Orchestrator` class in `scripts/pipeline.py` selects `MockSQLBotClient` when
`--mock-fixture` is passed to `phase1`, and `RealSQLBotClient` otherwise.

Default `phase1` invocation (mock fixture):

```bash
python /mnt/skills/public/chatbi-report/scripts/pipeline.py phase1 \
  --md /mnt/user-data/uploads/<file>.md \
  --out-dir /mnt/user-data/outputs \
  --mock-fixture /mnt/skills/public/chatbi-report/example/mock_sqlbot/profit_yoy.json
```

Default fixture:

```text
/mnt/skills/public/chatbi-report/example/mock_sqlbot/profit_yoy.json
```

For real SQLBot mode:

1. Drop `--mock-fixture` from the `phase1` command.
2. Set `SQLBOT_BASE_URL` in runtime env.
3. Keep the same `phase1` command shape.

Endpoint:

```text
${SQLBOT_BASE_URL}/api/v1/indicator/query-report-info
```

Current client uses no API key or Authorization header.

## Failure handling

- `pipeline.py phase1` / `pipeline.py phase2` non-zero exit → Python traceback on stderr; the agent displays the traceback and stops. No `assemble_status` write.
- `phase1` returns `CheckpointSignal("1.5" | "3.5", ...)` → agent calls `ask_clarification` per the mapping table in `references/pipeline.md`. If user picks "停止", agent writes `status.json` with `error_class=USER_ABORTED` via `assemble_status.write_status`. If user picks "继续", agent re-invokes `phase1` with `--skip-lint-checkpoint` and/or `--skip-query-checkpoint`.
- `phase2` returns `CheckpointSignal("8d.5", ...)` → same routing.
- 8a / 8b / 8d internal failures (compute, evaluate, description) → cells become `⚠️COMPUTE_FAILED` / `⚠️DESCRIPTION_FAILED` sentinels; pipeline continues to `report.md` / `report.docx` / `status.json` with `error_class=None`.

## Common symptoms

| Symptom | Likely cause | Fix |
|---|---|---|
| `phase1` returns `kind=checkpoint, step=3.5` with `ok < total` | SQLBot returned `success=false` for some idx_id OR `data` empty | Check `SQLBOT_BASE_URL`; verify mock fixture has matching `idx_id` keys; if real SQLBot, check periods match `time_info` |
| `phase1` returns `kind=checkpoint, step=1.5` with `n_err > 0` | markdown template has lint errors (missing `data-idx`, malformed `> 计算:` block, etc.) | Run `python -m md_lint scripts/md_lint.py <file>.md` for the error list |
| `phase2` finishes but `status.json` shows many `⚠️COMPUTE_FAILED` cells | Compute source code failed `validate_ast` / `validate_signature` / `run_smoke` / `run_example` | Re-read `prompts/compute_codegen.md`; regenerate compute source via LLM |
| `phase2` returns `kind=checkpoint, step=8d.5` | Description file missing or unreadable | Verify the description file paths passed via `--descriptions-dir` exist; check `out_dir` permissions |
| `phase2` produces empty `report.md` | wide.per_report has no rows | Check `query.json` — likely no idx_id succeeded; see first row |
| Sandbox can't import pandas | Container missing deps | Restart with `make dev` |

## Do not do these during normal report runs

- Do not edit `/mnt/skills/public/chatbi-report/SKILL.md`, scripts, or prompts.
- Do not edit `/mnt/user-data/uploads/<file>.md`.
- Do not add analysis dimensions, columns, or interpretation unless the user asks.
- Do not paste raw `status.json` or raw script OK lines to the user.
