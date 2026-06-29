# chatbi-report runlog

- Step 1 lint: success, errors=0, warnings=0
- Step 2 parse: success, sections=1, reports=1, idx=1, out=/tmp/chatbi-report-run/input.parsed.json
- Step 3 query: success, queried=4, successful_items=4, failures=0, out=/tmp/chatbi-report-run/input.query.json
- Step 4 assemble-wide: success, rows=4, cols=4, out=/tmp/chatbi-report-run/input.wide.json
- Step 5 unit-convert: success, out=/tmp/chatbi-report-run/input.wide.json
- Step 6 extract-ir: success, compute_irs=3, out=/tmp/chatbi-report-run/input.ir.json
- Step 7 codegen: success, specs=3, outputs=/tmp/chatbi-report-run/input.compute.*.py

## Step 8a validate

- 结果：3/3 compute 源码通过宽表 smoke 校验。
- 暴露问题：从 IR 示例直接传入 JSON 标量对象时，`compute.py validate --example-input '{"2024":"1200","2023":"1000"}'` 会触发 pandas `ValueError: If using all scalar values, you must pass an index`。本次用 CLI 当前可接受的 kv 形式继续：`BAS_0263@2024=1200,BAS_0263@2023=1000`。

## Step 8b/8c evaluate + apply-computed

- 结果：3 个 computed JSON 生成，并合并为 `/tmp/chatbi-report-run/input.wide.computed.json`。

## Step 8d describe

- 结果：写入 `/tmp/chatbi-report-run/input.description.report-0.txt`。

## Step 9 render/status

- Markdown: `/tmp/chatbi-report-run/input.report.md`
- DOCX: `/tmp/chatbi-report-run/input.report.docx`
- Status: `/tmp/chatbi-report-run/input.status.json`
- 暴露问题：示例目录没有提供 DOCX style JSON，本次使用临时 `/tmp/chatbi-report-run/style.json` 才能完成 DOCX 渲染。
- 暴露问题：`assemble_status.py --exit-step` 实际要求整数，不能传 `done` 这类状态名。
