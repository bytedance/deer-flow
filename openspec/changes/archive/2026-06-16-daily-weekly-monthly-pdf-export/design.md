## Context

三个内置报告（日报、周报、月报）当前只能下载 Markdown。用户看到"PDF 不可用（weasyprint 未安装）"因为：

- 三个 `skills/custom/*/scripts/export_report.py` 只有 Markdown 生成逻辑，没有 PDF 渲染能力
- Sandbox 容器中未安装 weasyprint 和 GTK/Cairo/Pango 系统库
- 三个 SOUL.md 均硬编码 `pdf_available = False`

**统一后的执行路径**：

| 步骤 | 日报 | 周报 | 月报 |
|------|------|------|------|
| 数据查询 | Gateway (`report_direct_execute`) | Sandbox (SOUL 内联 Python) | Sandbox (SOUL 内联 Python) |
| KPI 计算 | Gateway (`report_direct_execute`) | Sandbox (SOUL 内联 Python) | Sandbox (SOUL 内联 Python) |
| Markdown 导出 | Gateway (`report_direct_execute`) | Sandbox (`export_report.py`) | Sandbox (`export_report.py`) |
| **PDF 导出** | **Sandbox (SOUL 内联 Python)** | **Sandbox (`export_report.py`)** | **Sandbox (`export_report.py`)** |

所有 PDF 生成统一在 Sandbox 内完成，Gateway 侧不参与 PDF 渲染。`DirectReportExecutor` 和 Gateway `exporter.py` 不受影响。

## Goals / Non-Goals

**Goals:**
- 在 Sandbox 容器中统一完成日报、周报、月报的 PDF 生成
- Sandbox Docker 镜像安装 weasyprint + GTK/Cairo/Pango 运行时库
- 三个 `export_report.py` 均添加 `write_report_pdf()` 函数
- SOUL.md 运行时检测 weasyprint 可用性（替换硬编码 `pdf_available = False`）
- 日报 SOUL.md 新增 Sandbox 内联 Python PDF 导出步骤
- PDF 不可用时优雅降级，仅提供 Markdown 下载

**Non-Goals:**
- 不修改 Gateway 侧 `DirectReportExecutor` 或 `exporter.py`
- 不修改现有 API 契约或 artifact 下载路由
- 不修改前端行为
- 不修改 `build_export_result()` — Sandbox 路径直接调用 `write_report_pdf()`，不经由 CLI→build_export_result→stdout JSON 链路
- 三个 `export_report.py` 保持各自独立（不提取公共 PDF 模块）

## Decisions

### Decision 1: PDF 生成统一在 Sandbox

**选择**: 所有 PDF 生成在 Sandbox 容器内完成，Gateway 不参与。

**日报执行流程**：
1. `report_direct_execute` 在 Gateway 完成数据查询 + KPI 计算 + Markdown 导出（保持现有逻辑不变）
2. SOUL.md 在 `report_direct_execute` 返回后，新增 Sandbox 内联 Python 代码块：
   - 读取已生成的 `/mnt/user-data/outputs/daily_report.md`（避免重复渲染）
   - 调用 `write_report_pdf(md_text, output_dir, "daily_report")` 生成 PDF
   - 更新下载链接和 `present_files`

**周报/月报执行流程**：保持现有 SOUL.md 内联 Python 模式，在已有 `write_report()` 调用后增加 `write_report_pdf()` 调用。

**备选方案及否决理由**:
- **Gateway 侧生成 PDF**: 日报走 `report_direct_execute` → `DirectReportExecutor` subprocess，周报/月报走 Sandbox。两条路径不一致，且需要维护两处 weasyprint 环境。
- **全部改用 `report_direct_execute`**: 需要大幅重构周报/月报的 SOUL.md，风险高且无用户价值。

### Decision 2: PDF 函数签名与行为

**选择**: 在每个 `export_report.py` 中添加 `write_report_pdf(md_text: str, output_dir: Path, filename_base: str) -> Path | None`。成功返回 PDF 路径，失败返回 None。

**降级链**:
1. `from weasyprint import HTML` — ImportError/OSError → 返回 None
2. `import markdown` 做 HTML 转换 — ImportError → 用 `<pre>` 包裹
3. `HTML(string=html).write_pdf()` — 任何异常 → log warning，返回 None

### Decision 3: SOUL.md 运行时检测

**选择**: 用 try/except Exception 替换硬编码的 `pdf_available = False`。

```python
pdf_available = True
try:
    write_report_pdf(md_text, output_dir, "weekly_report")
except Exception:
    pdf_available = False
```

**为什么用 `except Exception` 而非 `except ImportError`**：Linux 上 weasyprint 可能成功 import 但渲染时因缺失系统库（GTK/Cairo）而抛出 OSError。宽捕获确保优雅降级。

**参考**: `fault-diagnosis--rotating/SOUL.md` 已有类似模式（但用的是 `except ImportError`，我们的实现会改为 `except Exception`）。

### Decision 4: 日报/月报 SOUL.md PDF 导出方式

**选择**: 日报和月报的 Sandbox 内联 Python 直接读取已生成的 `.md` 文件获取 `md_text`，不重新调用 `render_markdown()`。周报沿用现有 `render_markdown()` 输出（已在同一代码块中调用）。

```python
# 日报/月报：读已有 .md 文件
from pathlib import Path
md_text = Path("/mnt/user-data/outputs/daily_report.md").read_text(encoding="utf-8")
write_report_pdf(md_text, output_dir, "daily_report")
```

**理由**:
- 避免 Markdown 重复渲染（Gateway 已生成一次）
- 月报 SOUL.md 明确注释"不要在 SOUL 端再 import render_markdown"
- 读文件比重新渲染更简洁、更快
- `report_direct_execute` 保持向后兼容
- PDF 生成失败时，Markdown 始终可用（由 Gateway/现有流程生成）

### Decision 5: 字体支持

**选择**: Sandbox 镜像添加 `fonts-wqy-zenhei`（文泉驿正黑）包，提供完整 CJK 字形覆盖。

**备选方案及否决理由**:
- `fonts-liberation`: 主要覆盖拉丁字符，中文支持有限，工业报告中设备名称、异常描述全是中文，可能导致 tofu（缺字方块）。
- `fonts-noto-cjk`: CJK 覆盖最好但体积 ~100MB，对 Sandbox 镜像影响过大。

## Risks / Trade-offs

- **[Sandbox 镜像 +200MB]** → GTK/Cairo/Pango 共享库体积大。缓解：镜像构建一次后缓存，仅影响 Sandbox 镜像不影响 Gateway。
- **[基础镜像 OS 未知]** → `all-in-one-sandbox:latest` 不确定基于 Debian 还是 Alpine，影响包管理器选择（apt vs apk）。缓解：实现前 `docker run --rm <base> cat /etc/os-release` 确认；大概率 Debian-based（>95% 的 Python 镜像都用 Debian）。
- **[weasyprint SVG 图表渲染不完整]** → 报告使用 base64 内联 SVG，weasyprint 可能不支持全部 SVG 特性。缓解：渲染失败时降级为仅 Markdown。
- **[>50KB SVG 图表在 PDF 中丢失]** → `_embed_chart_image()` 对大图表写文件后用 `/api/threads/...` URL 引用，weasyprint 在 Sandbox 内无法访问。已知限制，不做修复——实际报告中 SVG 图表通常 10-30KB，极少触发此阈值。
- **[Markdown→HTML 转换质量]** → `markdown` 库可能未安装。缓解：回退到 `<pre>` 包裹纯文本。
- **[SOUL.md 是 LLM prompt，不是确定性的代码]** → Agent 可能偏离 PDF 导出模式。缓解：fault-diagnosis 报告已使用相同模式且运行稳定。

## Open Questions

_无。_
