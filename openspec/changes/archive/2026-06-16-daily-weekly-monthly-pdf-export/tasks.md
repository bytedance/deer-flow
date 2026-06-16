## 1. Sandbox Docker 镜像 — PDF 基础设施

- [x] 1.0 预检：`docker run --rm <base-image> cat /etc/os-release` 确认基础镜像发行版（Ubuntu 22.04 Jammy，apt-get 可用）
- [x] 1.1 在 `docker/sandbox/Dockerfile` 中添加 GTK/Cairo/Pango 运行时库（`apt-get install libcairo2 libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 libpangoft2-1.0-0`；已移除不存在的 `libgobject-2.0-0`）
- [x] 1.2 在 `docker/sandbox/Dockerfile` 中添加 `fonts-wqy-zenhei`（文泉驿正黑）用于 CJK 文字渲染
- [x] 1.3 在 `docker/sandbox/requirements.txt` 中添加 `weasyprint>=62.0` 和 `markdown>=3.7`
- [x] 1.4 重新构建 Sandbox 镜像，验证 `from weasyprint import HTML` 成功导入 + 中文 PDF 渲染成功

## 2. 日报 — export_report.py PDF + SOUL.md Sandbox 导出步骤

- [x] 2.1 在 `skills/custom/daily-report/scripts/export_report.py` 中添加 `write_report_pdf(md_text, output_dir, filename_base)` 函数（Markdown→HTML→PDF，含三级降级）
- [x] 2.2 在 `agents/builtin/ai-report--daily/SOUL.md` 中 `report_direct_execute` 返回后，新增 Sandbox 内联 Python 块：读取已生成的 `daily_report.md` 文件获取 `md_text`、调用 `write_report_pdf()`、更新下载链接和 `present_files`
- [x] 2.3 确保 `except Exception` 而非 `except ImportError`（覆盖 OSError 场景）

## 3. 周报 — export_report.py PDF + SOUL.md 运行时检测

- [x] 3.1 在 `skills/custom/weekly-report/scripts/export_report.py` 中添加 `write_report_pdf(md_text, output_dir, filename_base)` 函数
- [x] 3.2 更新 `agents/builtin/ai-report--weekly/SOUL.md`：将 `pdf_available = False` 替换为 try/except Exception 运行时检测
- [x] 3.3 更新周报 `present_files` 逻辑：PDF 可用时同时 present `.md` 和 `.pdf`

## 4. 月报 — export_report.py PDF + SOUL.md 运行时检测

- [x] 4.1 在 `skills/custom/monthly-report/scripts/export_report.py` 中添加 `write_report_pdf(md_text, output_dir, filename_base)` 函数
- [x] 4.2 更新 `agents/builtin/ai-report--monthly/SOUL.md`：将 `pdf_available = False` 替换为 try/except Exception 运行时检测，通过读取已生成的 `monthly_report.md` 获取 `md_text`（不 import `render_markdown`，遵守现有注释约定）
- [x] 4.3 更新月报 `present_files` 逻辑：PDF 可用时同时 present `.md` 和 `.pdf`

## 5. 验证

- [ ] 5.1 日报 PDF：触发日报生成，确认 PDF 下载链接出现且文件有效
- [ ] 5.2 周报 PDF：触发周报生成，确认 PDF 下载链接出现且文件有效
- [ ] 5.3 月报 PDF：触发月报生成，确认 PDF 下载链接出现且文件有效
- [ ] 5.4 降级验证：在未安装 weasyprint 的 Sandbox 中，确认仅提供 Markdown 下载，显示"PDF 不可用"提示
