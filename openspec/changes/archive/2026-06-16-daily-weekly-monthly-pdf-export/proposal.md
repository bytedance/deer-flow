## Why

日报、周报、月报当前只支持 Markdown 格式下载，PDF 按钮始终显示"PDF 不可用（weasyprint 未安装）"。三个报告的 SOUL.md 中均硬编码 `pdf_available = False`，且各自的 `export_report.py`（运行在 Sandbox 容器内）只有 Markdown 生成逻辑，缺少 PDF 渲染能力。用户需要可直接下载的 PDF 格式报告用于分发和归档。

## What Changes

- Sandbox Docker 镜像添加 weasyprint Python 包及 GTK/Cairo/Pango 系统运行时库
- 日报、周报、月报各自的 `skills/custom/*/scripts/export_report.py` 新增 `write_report_pdf()` 函数，从 Markdown 渲染 HTML 再转为 PDF
- **所有 PDF 生成统一在 Sandbox 容器内完成**，不依赖 Gateway 侧的 weasyprint
- 日报 SOUL.md 在 `report_direct_execute` 返回后，新增 Sandbox 内联 Python 步骤调用 `export_report.py` 生成 PDF
- 周报、月报 SOUL.md 将 `pdf_available` 从硬编码 `False` 改为运行时检测（尝试导入 weasyprint），PDF 失败时自动降级仅 Markdown
- 不改变任何现有 API 契约或前端行为 — PDF 路径沿用已有的 artifact 下载路由

## Capabilities

### New Capabilities

- `sandbox-pdf-export`: Sandbox 容器内 PDF 渲染基础设施（weasyprint + GTK 系统库），供所有直接执行报告共用
- `report-pdf-export`: 日报/周报/月报在 Sandbox 中生成 PDF，失败时优雅降级

### Modified Capabilities

_无现有 spec 的行为变更需求。各报告已有的 `pdf_available = False` 降级分支保留，当 weasyprint 确实不可用时行为不变。_

## Impact

- `docker/sandbox/Dockerfile`: 添加 GTK 系统库安装步骤
- `docker/sandbox/requirements.txt`: 添加 `weasyprint>=62.0`
- `skills/custom/daily-report/scripts/export_report.py`: 新增 PDF 导出函数
- `skills/custom/weekly-report/scripts/export_report.py`: 新增 PDF 导出函数
- `skills/custom/monthly-report/scripts/export_report.py`: 新增 PDF 导出函数
- `agents/builtin/ai-report--daily/SOUL.md`: 新增 Sandbox 内联 Python PDF 导出步骤
- `agents/builtin/ai-report--weekly/SOUL.md`: `pdf_available` 改为运行时检测
- `agents/builtin/ai-report--monthly/SOUL.md`: `pdf_available` 改为运行时检测
- `backend/` 侧无变更（`DirectReportExecutor` / `exporter.py` 不受影响）
- Sandbox 镜像大小预计增加 ~200MB（GTK 运行时库）
