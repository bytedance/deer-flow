# Enterprise Report Workflow

Use this workflow when handling `/report`, `/r`, `/报告`, or any request for a formal business analysis report.

## Principle

The Agent owns the report. Code is only a calculator and data access layer.
The final output must be assembled by the Agent using judgement, industry context,
query results, and explicit conclusions.

## Required Steps

1. **Clarify the business surface**
   - Infer likely industry from user wording, table name, file name, column names, and sample values.
   - If ambiguous, state the assumed industry in the report and mark confidence.
   - Do not rely on hardcoded Python industry classifiers.

2. **Select experts dynamically**
   - Read `workflow_specs/expert_library/INDEX.md`.
   - Select one primary expert and optional supporting experts.
   - Read every selected expert Markdown file completely before making the analysis plan.
   - Record selected experts and confidence in the report notes or appendix.
   - Do not encode expert selection or expert rules as Python if/else logic.

3. **Build an analysis plan before writing**
   - Use the selected expert files as the analysis playbook.
   - Decide which views are supported by available data.
   - List unsupported views as data gaps instead of fabricating conclusions.
   - Build a pyramid storyline before writing: top conclusion, supporting findings, evidence charts, appendix data.
   - Plan multiple finding branches. Each finding branch must also follow pyramid logic internally: local conclusion, supporting observations, evidence chart, attribution explanation, action.
   - Assign appendix data table IDs before writing, e.g. `A1`, `A2`, `A3`. Every major conclusion and finding must cite at least one appendix table ID.
   - Extract and execute each selected expert file's `Cross Analysis Matrix`, `Anomaly Patterns`, and `Deep Attribution Paths`.

4. **Use local tools only for evidence**
   - Use DuckDB/SQL/Python for profiling, grouping, period comparison, anomaly scan, and attribution math.
   - Use existing engines such as `insight_engine.py`, `attribution_engine.py`, and `forecast_engine.py` only as evidence providers.
   - The Agent writes the interpretation, not the tool.
   - Evidence for main findings should be converted into charts first. Tables are supporting detail, not the primary proof.
   - At minimum, collect evidence for baseline comparison, anomaly scan, cross-analysis, and driver attribution when data supports them.
   - Do not expose SQL in the main report body. Translate calculation logic into plain business wording.

5. **Write conclusion-first**
   - Start with 3-5 business conclusions.
   - Each conclusion should answer: what happened, why it likely happened, what to do next.
   - Include numbers and comparison periods when available.
   - Follow global pyramid writing: conclusion -> findings -> chart evidence -> attribution explanation -> action -> appendix data.
   - Each finding must also follow local pyramid writing: finding conclusion -> observation -> chart evidence -> attribution -> local action.
   - Key conclusions and finding conclusions must cite appendix data tables, such as `[Data A1]` or `[Data A2, A4]`.
   - Every analysis module and every finding branch must include a short "统计口径说明" in plain language: data range, date grain, metric definition, grouping dimension, filters, and limitations. Do not show SQL.
   - Do not write a data dump, metric inventory, or table-by-table commentary.

6. **Generate the final artifact**
   - Before writing HTML, read `workflow_specs/html_templates/report_light.html` completely and use it as the report shell.
   - Use `workflow_specs/visual_templates/light.md` or `dark.md` only as visual direction; do not use Markdown visual notes as the final HTML shell.
   - Generate long reports section by section: cover, one-page conclusions, each finding branch, chart evidence, attribution, actions, appendix.
   - Assemble the section outputs into one unified HTML report only after all branches are complete and internally consistent.
   - Markdown report: suitable for direct reading or document conversion.
   - HTML report: standalone, enterprise/PDF-like layout, no external dependencies.
   - JSON report: only when user explicitly needs structured data; include evidence and conclusions.

## Enterprise Report Structure

Use this pyramid structure unless the user asks otherwise:

1. 封面：报告主题、分析对象、周期、口径、专家模式
2. 一页纸结论：3-5 条核心结论，每条包含影响、原因判断、建议动作、数据引用
3. 关键发现分支：按业务重要性排序；每个分支内部遵守“局部结论 -> 发现 -> 图表举证 -> 解释归因 -> 行动建议”
4. 图表举证：每个关键发现必须配一个主图表和一句证据解释
5. 归因与异常：解释变化来自哪里、异常出现在哪里、是否可行动
6. 行动建议：按优先级列出下一步动作、预期影响、所需数据
7. 附录数据：汇总所有分支用到的数据表、SQL、字段口径、缺失数据、详细样本，并提供可引用编号

Forbidden report structures:

- 先介绍大量背景，再把结论放到最后。
- 直接罗列数据表、字段画像或统计量，缺少业务判断。
- 用表格替代举证图表。
- 按工具输出顺序拼接 insight/forecast/attribution 文本。
- 前文结论没有引用附录数据表。
- 关键发现只列标题，没有内部结论、图表证据和归因解释。

## Pyramid Writing Contract

The whole report must follow this global pyramid:

1. **Top conclusion**: 3-5 board-level conclusions.
2. **Finding branches**: multiple branches that support the top conclusions.
3. **Evidence charts**: charts that prove each branch.
4. **Attribution explanation**: why the evidence likely happened.
5. **Actions**: what to do next.
6. **Appendix data**: all data tables used by the branches.

Every finding branch must follow this local pyramid:

1. **Conclusion**: one sentence that a business owner can act on.
2. **Finding**: 2-3 supporting observations with exact numbers.
3. **Evidence chart**: line/bar/funnel/waterfall/heatmap/scatter/map as appropriate.
4. **Interpretation**: why this likely happened and what uncertainty remains.
5. **Action**: recommended business response.
6. **Data reference**: cite appendix table IDs that support the conclusion.

Example:

- Conclusion: `6 月 GMV 下滑主要由华东渠道订单数下降驱动，客单价不是主因。[Data A1, A3]`
- Finding: `华东贡献了总下滑的 62%，订单数环比 -18%，AOV 仅 -1.7%。`
- Evidence chart: waterfall for regional contribution + line chart for order trend.
- Action: `优先排查华东渠道投放、库存和履约，而不是全站调价。`

## Appendix Data Citation Contract

All evidence tables used in the report must be collected in the appendix and assigned stable IDs:

- `A1`: executive KPI summary and period comparison.
- `A2`: trend data used by line/area charts.
- `A3`: contribution or attribution data used by waterfall/bar charts.
- `A4`: cross-analysis data used by heatmaps, segmented bars, scatter plots, or matrices.
- `A5+`: additional expert-specific evidence tables.

Citation rules:

- Every top conclusion must cite one or more appendix tables.
- Every finding branch conclusion must cite one or more appendix tables.
- Every chart must cite the appendix table it was generated from.
- Appendix tables must include enough rows/columns to reproduce the claim or chart.
- Do not place large evidence tables in the main body; show a compact cited snippet only when it improves readability.

## Expert Library

Expert playbooks live in `workflow_specs/expert_library/`.

The Agent must not summarize from memory when an expert is selected. It must read
the selected expert file and follow its mission, required analysis views, required
data checks, cross analysis matrix, anomaly patterns, deep attribution paths,
core metrics, report questions, and dashboard modules.

When multiple experts apply, use a primary/supporting structure:

- Primary expert decides the report storyline and main KPI tree.
- Supporting experts add risk, quality, finance, campaign, product, or customer angles.
- Conflicts are resolved by the user’s stated objective and available evidence.

## Evidence Rules

- Every strong conclusion needs at least one number, comparison, rank, or contribution statement.
- Every strong conclusion and every finding branch conclusion needs an appendix data citation.
- Every claim must respect the actual fields and data supplied by the user.
- Do not invent business concepts that are not present in the data or user instruction. For example, do not mention target achievement rate, budget variance, SLA compliance, retention, funnel conversion, profit margin, or ROI unless the required fields or user-provided definitions exist.
- Every report must attempt the mandatory expert reasoning loop from `expert_library/INDEX.md`.
- Every selected primary expert must produce:
  - one baseline comparison
  - one anomaly scan
  - one cross-analysis
  - one attribution/drill-down path
- Every key finding should have a primary chart. Use tables only for appendix or compact supporting detail.
- Choose chart types by analytical purpose:
  - Trend/change: line or area chart.
  - Ranking/contribution: bar chart or waterfall.
  - Funnel loss: funnel chart.
  - Retention/cohort: heatmap.
  - Relationship: scatter chart.
  - Geographic distribution: map with bar fallback.
  - City transaction distribution: when a city field and transaction amount/sales amount/GMV field are both present, add a city transaction map. Use `geo + effectScatter` or a province/city map recipe; do not force city data into province totals unless province mapping exists.
  - Structure: treemap, stacked bar, or pie only when categories are few.
- If evidence is weak, phrase as “初步判断” or “需要补充数据验证”.
- When discussing seasonality or external factors, do not assert causality from internal data alone. Prefer wording such as: `补充节假日、活动投放、价格、库存、天气、渠道策略等数据后，可以进一步判断这是季节性波动还是外部因素导致。`
- Do not overfit one chart. Reports must include interpretation and action.
- Do not hide data limitations.

## Statistical Scope Contract

Each report module must show the necessary statistical scope in conversational language:

- Data range: which table/file, row count, date range if available.
- Date grain: daily, weekly, monthly, order-level, user-level, transaction-level, or "no date field available".
- Metric scope: which numeric field is summed, averaged, counted, or compared.
- Grouping scope: which dimension fields are used for ranking, segmentation, or cross-analysis.
- Filter scope: any user-provided filter, period, segment, or cleaning rule.
- Limitation: what the current data cannot prove.

The main report should say this as a reader-facing explanation, for example:

`统计口径说明：本模块基于订单表中 12,430 条记录，按 order_date 观察每日变化，金额口径为 amount 汇总，分组优先看 region 和 channel。当前数据没有投放、节假日和库存字段，因此不能直接判断波动是否由外部因素导致。`

Do not display SQL in the main body. SQL can only appear in the appendix when the user asks for audit detail.

## HTML Report Visual Rules

- Read and apply `workflow_specs/html_templates/report_light.html` as the default HTML report shell.
- Read `workflow_specs/visual_templates/light.md` by default as supplemental visual direction.
- Read `workflow_specs/visual_templates/dark.md` only when the user asks for dark mode, then adapt the HTML shell tokens without weakening the PDF-like structure.
- The HTML should look like an enterprise PDF: paper-like page, formal header, numbered sections, compact tables, print-friendly CSS.
- The Agent may adapt layout and CSS to match the user’s brand or industry.
- The generated CSS must visibly implement the HTML shell: page background, paper canvas, typography scale, section rhythm, chart panels, table style, status colors, and print rules.
- If HTML looks like browser-default output, a plain Markdown conversion, or a loose table page, regenerate before returning.

## Chart Generation Contract

Every chart embedded in a report must be generated from an explicit chart recipe context:

1. Read `references/examples/INDEX.md` to select the chart type.
2. Read the selected `references/examples/<chart-name>.md` file completely before writing the chart option.
3. Query or calculate the exact evidence table that powers the chart.
4. Generate a standalone ECharts option from that recipe and data.
5. Generate charts one by one. Do not assemble the report until each chart has a stable chart ID, selected recipe name, option, and appendix data reference.
6. Embed the full local `assets/echarts/echarts.min.js` library before any report chart bootstrap code. CDN scripts, local `<script src>`, runtime loaders, and placeholder ECharts stubs are invalid.
7. Embed the validated chart specs into the report template as a `reportChartSpecs` list; initialize each chart independently so one failed chart cannot break all other charts.
8. Keep ECharts JavaScript syntactically closed. In particular, `new echarts.graphic.LinearGradient(...)` and `new echarts.graphic.RadialGradient(...)` must close the constructor with `)` before closing the surrounding option object.
9. Cite the appendix data table ID used by the chart.
10. Validate the generated HTML with `python scripts/validate_chart.py <output.html>` when possible. If it fails for external ECharts CDN, missing inlined ECharts library, or unclosed graphic constructor, repair and rerun before returning.

Do not create charts by freehand memory when a recipe exists. If a required recipe is missing, state the gap and choose the closest supported recipe from the index.
