## Context

ISSUE-03 和 ISSUE-04 分别打通了 chat↔report 跳转链路和 upload→index→retrieve→report 知识主链。当前状态：

- `ReportRunRecord` 已存储 `template_id`、`template_version`、`template_version_ref`、`thread_id`、`run_id`、`parameters_summary`、`artifact_paths`、`data_snapshot_paths`
- `report_payload.json` 已包含 `template.{id,version,name}`、`run.{id,thread_id,generated_at}`、`parameters`、`sections[]`
- 前端详情页已展示模板链接、状态、参数摘要、产物下载、错误信息
- `report-to-source-traceability` spec 定义了 run→thread 和 artifact→run 的跳转
- `chat-to-report-navigation` spec 定义了 chat→report 和 chat→artifact 的跳转

缺口：
1. 运行记录无法查看到产生它的确切模板 DSL 版本
2. `data_snapshot_paths` 字段定义了但从未被填充，知识来源不可见
3. 模板被删除/归档、知识库不可用时的错误码未标准化
4. 缺少端到端验证测试覆盖完整的模板→产物链路

## Goals / Non-Goals

**Goals:**
- 运行详情页可查看模板版本 DSL 快照（跳转到版本详情页）
- 运行详情页展示触发上下文（来源对话链接）和输入来源（参数、数据文件路径）
- 产物下载与运行记录之间双向导航
- 定义四类错误码（TEMPLATE_UNAVAILABLE / KB_UNAVAILABLE / RUN_INTERRUPTED / DATA_STEP_FAILED）
- 一条端到端验证路径覆盖模板→版本→运行→参数→数据→payload→产物

**Non-Goals:**
- 不引入新的持久化字段（复用现有 `data_snapshot_paths`、`parameters_path`）
- 不修改 DSL schema
- 不引入后台 JobRunner（取消、重试仍走现有 LLM-driven 路径）
- 不实现数据快照的完整生命周期管理（那是后续 issue 的范围）

## Decisions

### D1: 模板版本追溯 — 前端跳转，后端透传

**选择**：运行详情页的模板链接改为跳转到具体版本详情页（`/workspace/report-templates/{template_id}?version={template_version}`），后端 GET run 响应中已包含 `template_id` + `template_version`，无需新增字段。

**替代方案**：在运行详情页内嵌 DSL YAML 查看器 → 不选，因为版本查看器已存在于模板详情页，内嵌会造成 UI 重复和维护负担。

**替代方案**：在 `report_payload.json` 中嵌入完整 DSL → 不选，payload 是产物格式不应膨胀，且 `template_version_ref` 已足够定位。

### D2: 输入来源展示 — 分级可见

**选择**：
- **参数**：`parameters_summary` 已在详情页展示（现有），额外增加 `parameters_path` 可下载链接（当路径指向 `{run_output_dir}/parameters.json` 时，通过 artifact API 提供下载）
- **数据快照**：利用现有的 `{run_output_dir}/data/` 目录下的数据文件，在运行详情页列出可下载的数据文件列表（通过 artifact API）
- **知识来源**：本期不单独存储知识来源列表（`data_snapshot_paths` 保持空），因为 RAG 检索发生在 agent 运行时而非 data_runner 中。知识来源通过关联的 chat thread 间接可见

**替代方案**：在 data_runner 中为每个数据步骤创建快照 → 不选，当前数据步骤是 CLI 脚本调用外部 API（如 InS），脚本输出本身就是数据来源；额外快照增加 IO 开销但价值有限。

### D3: 错误码分类 — 四类标准化语义

**选择**：定义以下错误码前缀，在 `error_code` 字段中使用：

| 错误码 | 场景 | 用户提示要点 |
|--------|------|-------------|
| `TEMPLATE_UNAVAILABLE` | 模板已删除/归档 | "报告模板已失效，请联系管理员" |
| `KB_UNAVAILABLE` | 知识库文档不可用 | "知识来源不可用：{doc_title}" |
| `RUN_INTERRUPTED` | 运行被取消或超时 | "报告生成已中断" |
| `DATA_STEP_FAILED` | 数据脚本执行失败 | "数据步骤 {step_id} 失败：{message}" |

这些错误码由运行时工具层在遇到对应异常时写入 `ReportRunRecord.error_code`。`TEMPLATE_UNAVAILABLE` 在 `prepare_run` 时校验模板状态；其他三类已由现有异常处理路径覆盖，仅需统一错误码前缀。

### D4: 端到端验证 — 单测模拟完整链路

**选择**：在 `tests/test_report_template_traceability_e2e.py` 中创建测试，模拟：
1. 创建模板 → 发布版本
2. 创建 ReportRun（prepare_run）
3. 运行数据步骤 → 组装 payload → 导出产物
4. 验证 payload 中的 template/run 元数据
5. 验证 run record 的 artifact_paths 指向正确文件
6. 验证从 run 可追溯到模板版本

使用 `tempfile.TemporaryDirectory` 作为存储后端，全程不依赖数据库或外部服务。

## Risks / Trade-offs

- **知识来源可见性受限于 agent 运行时**：data_runner 无法获知 RAG 检索了哪些文档，完整的知识来源链路需要 agent 运行时在调用 `report_template_assemble_payload` 前显式记录 → 本期接受此限制，通过关联的 chat thread 间接提供上下文
- **数据快照列表依赖文件系统扫描**：列出 `{run_output_dir}/data/` 下的文件可能有权限问题 → 后端 list 时做 `Path.exists()` 守卫，文件缺失时静默跳过
