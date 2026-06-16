# report-pdf-export

## Requirements

### Requirement: Daily report PDF export in Sandbox
日报 SOUL.md SHALL 在 `report_direct_execute` 返回后，通过 Sandbox 内联 Python 调用 `export_report.py` 的 `write_report_pdf()` 生成 PDF。

#### Scenario: Daily PDF generated in Sandbox
- **WHEN** 日报 `report_direct_execute` 成功返回且 Sandbox 中 weasyprint 可用
- **THEN** SOUL.md SHALL 在 Sandbox 中调用 `write_report_pdf()` 生成 `daily_report.pdf`，下载链接同时包含 Markdown 和 PDF

#### Scenario: Daily PDF gracefully degraded
- **WHEN** Sandbox 中 weasyprint 不可用或渲染失败
- **THEN** 下载链接 SHALL 仅包含 Markdown，显示"PDF 不可用（weasyprint 未安装）"

#### Scenario: Daily Markdown always available
- **WHEN** `report_direct_execute` 成功返回
- **THEN** `daily_report.md` SHALL 始终可下载，无论 PDF 生成是否成功

### Requirement: Weekly report PDF export in Sandbox
周报 `export_report.py` SHALL 在 Sandbox 中通过 `write_report_pdf()` 生成 PDF。

#### Scenario: Weekly PDF generated successfully
- **WHEN** Sandbox 中 `build_export_result(payload)` 被调用且 weasyprint 可导入
- **THEN** 结果 SHALL 包含 `pdf_path` 指向有效的 `weekly_report.pdf`

#### Scenario: Weekly PDF gracefully degraded
- **WHEN** weasyprint 不可导入或系统库缺失
- **THEN** 结果 SHALL 包含 `pdf_path: null` 和 `pdf_skipped_reason: "weasyprint_unavailable"`

#### Scenario: Weekly PDF render error
- **WHEN** weasyprint 可导入但 `write_pdf()` 抛出异常
- **THEN** 结果 SHALL 包含 `pdf_path: null` 和 `pdf_skipped_reason: "render_error"`，Markdown 仍然可用

### Requirement: Monthly report PDF export in Sandbox
月报 `export_report.py` SHALL 在 Sandbox 中通过 `write_report_pdf()` 生成 PDF。

#### Scenario: Monthly PDF generated successfully
- **WHEN** Sandbox 中 `build_export_result(payload)` 被调用且 weasyprint 可导入
- **THEN** 结果 SHALL 包含 `pdf_path` 指向有效的 `monthly_report.pdf`

#### Scenario: Monthly PDF gracefully degraded
- **WHEN** weasyprint 不可导入或系统库缺失
- **THEN** 结果 SHALL 包含 `pdf_path: null` 和 `pdf_skipped_reason: "weasyprint_unavailable"`

#### Scenario: Monthly PDF render error
- **WHEN** weasyprint 可导入但 `write_pdf()` 抛出异常
- **THEN** 结果 SHALL 包含 `pdf_path: null` 和 `pdf_skipped_reason: "render_error"`，Markdown 仍然可用

### Requirement: SOUL.md runtime PDF detection
周报和月报 SOUL.md SHALL 在运行时检测 weasyprint 可用性，而非硬编码 `pdf_available = False`。日报 SOUL.md SHALL 在 Sandbox 内联 Python 中做同样检测。

#### Scenario: Weekly SOUL detects weasyprint in Sandbox
- **WHEN** 周报 Agent 在已安装 weasyprint 的 Sandbox 中执行导出代码块
- **THEN** `pdf_available` SHALL 为 `True`，PDF 下载链接 SHALL 出现

#### Scenario: Weekly SOUL degrades without weasyprint
- **WHEN** 周报 Agent 在未安装 weasyprint 的 Sandbox 中执行导出代码块
- **THEN** `pdf_available` SHALL 为 `False`，显示"PDF 不可用（weasyprint 未安装）"

#### Scenario: Monthly SOUL detects weasyprint in Sandbox
- **WHEN** 月报 Agent 在已安装 weasyprint 的 Sandbox 中执行导出代码块
- **THEN** `pdf_available` SHALL 为 `True`，PDF 下载链接 SHALL 出现

#### Scenario: Daily SOUL detects weasyprint in Sandbox
- **WHEN** 日报 Agent 在 Sandbox 内联 Python 中尝试 `from weasyprint import HTML`
- **THEN** 成功时 SHALL 生成 PDF 并同时 present `.md` 和 `.pdf`，失败时仅 present `.md`

### Requirement: PDF output follows existing artifact path convention
所有 PDF 文件 SHALL 写入与对应 Markdown 相同的输出目录，使用已有 artifact 下载路由。

#### Scenario: PDF accessible via existing artifact route
- **WHEN** 周报 PDF 生成在 `/mnt/user-data/outputs/weekly_report.pdf`
- **THEN** 文件 SHALL 通过 `/api/threads/{thread_id}/artifacts/mnt/user-data/outputs/weekly_report.pdf` 可下载

#### Scenario: present_files includes PDF when available
- **WHEN** PDF 生成成功
- **THEN** `present_files()` SHALL 同时包含 `.md` 和 `.pdf` 路径

#### Scenario: present_files excludes PDF when unavailable
- **WHEN** PDF 生成失败
- **THEN** `present_files()` SHALL 仅包含 `.md` 路径
