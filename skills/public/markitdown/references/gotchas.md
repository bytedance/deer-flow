# MarkItDown Gotchas

Read this when the user has one of: PDF, PPTX, DOCX, JPG/PNG, or a MinerU routing question.
For other formats (XLSX/HTML/CSV/EPUB/JSON/XML), `MarkItDown().convert()` just works.

## PDF

| 问题 | 现象 | 解决 |
|---|---|---|
| 扫描件 / 图文 PDF | markitdown 输出 < 50 字符（接近空白） | 走 MinerU（`scripts/mineru_client.py`），OCR 后再喂 markitdown |
| 复杂表格 | 表格塌成纯文本 | 不可恢复；建议用户导出为 XLSX 再走 markitdown |
| 加密 PDF | 静默返回空 | 报错前先用 `pikepdf` 解密；或告知用户解密 |
| 多栏排版 | 跨栏错读 | 不可靠；告诉用户"建议单栏版本" |
| 大文件（>50MB） | 内存爆 | `convert_stream(f, file_extension=".pdf")` 分块流式 |

**OCR 检测规则**：`len(markitdown_output.strip()) < 50` 字符 → 判定为扫描件，自动 fallback 到 MinerU。阈值可在 `batch_convert.py` 的 `OCR_FALLBACK_THRESHOLD` 常量调。

## PPTX

| 问题 | 现象 | 解决 |
|---|---|---|
| 讲者备注 | 默认**不包含** | markitdown 用 `python-pptx` 默认不读 notes；如需，手动 `Presentation(path).slides[i].notes_slide.notes_text_frame.text` |
| SmartArt / 图表 | 转为占位文本 | 无法保留；告诉用户"图表内容无法提取" |
| 嵌入图片 | 默认不描述 | 走 OpenRouter 多模态（**不在本 skill 范围**） |
| 隐藏幻灯片 | 仍被转换 | 已知行为；如不需要，预处理删除 |

## DOCX

| 问题 | 现象 | 解决 |
|---|---|---|
| 批注 / 修订痕迹 | **不包含** | markitdown 不读 comments / tracked changes；如需，手动用 `python-docx` 解析 `document.element` 抽取 |
| 页眉 / 页脚 | 包含（✓） | 无需处理 |
| 嵌入对象（Excel/Visio） | 转成"二进制 blob" | 不可恢复；建议用户先解包 |
| 公式 | 转成纯文本 | 数学公式失去排版；如需 LaTeX，手工 `pandoc` 替代 |

## JPG / PNG

| 问题 | 现象 | 解决 |
|---|---|---|
| 走哪个后端？ | **始终走 MinerU** | 不依赖系统 tesseract，不依赖 OpenRouter |
| HEIC | **不支持** | 需先用 `pillow-heif` 转 PNG / JPG |
| EXIF 旋转 | 部分图片方向错 | MinerU 通常处理；如仍错，预处理 `PIL.Image.rotate` |
| 默认无图说 | MinerU 返回 OCR 文字 + 文字版面，**没有图片内容描述** | 想要"图说"需多模态模型直接看，**不在本 skill 范围** |
| 手写文字 | 识别率低 | MinerU 表现优于 tesseract，但仍非完美；告知用户 |

## MinerU（OCR 后端）

| 问题 | 现象 | 解决 |
|---|---|---|
| `MINERU_API_URL` 未设置 | 跑图片 / 扫描件时 `MinerUError: MINERU_API_URL is not set` | 在容器 `.env` 加上；`.env.example` 必须有这两行 |
| `MINERU_API_KEY` 未设置 | 同上 | 同上 |
| 容器到 MinerU LAN 不可达 | `MinerUError: MinerU connection error: ...` | 检查网络：容器里 `curl ${MINERU_API_URL}/health`（或实际 health 端点） |
| MinerU 返回 4xx/5xx | `MinerUError: MinerU HTTP <code>` | 失败信息带 `body` 字段可调试；本 skill 不重试，让调用方决定 |
| MinerU 返回非 JSON | `MinerUError: MinerU returned non-JSON: ...` | 极少见；可能 MinerU 端 BUG；记录 raw 后联系 MinerU 维护者 |
| MinerU 响应无 markdown 字段 | `MinerUError: MinerU response had no markdown/text/content field` | 检查实际响应字段名；`mineru_client.py` 支持 `markdown` / `text` / `content` 三种 key |

**环境变量**（必填，跑图片 / 扫描件时）：
- `MINERU_API_URL`：如 `http://mineru.lan:8000`
- `MINERU_API_KEY`：Bearer token

**端点形态**：`POST ${MINERU_API_URL}/ocr`，multipart/form-data，字段名 `file`，Bearer 鉴权。
返回 JSON 包含 `markdown`（或 `text` / `content`）字段。
如果 MinerU 实际部署用了不同 path / 字段名，按 `scripts/mineru_client.py` 顶部注释修改。

## 何时**不**用 markitdown / 本 skill

- 用户只要读一两行文本 → `Read` tool 直读原文件
- 用户要保留排版精确 → `pandoc` 优先
- 音视频 → 其它 skill / 工具（**不在本 skill 范围**）
- 需要"理解"图片内容（不是 OCR）→ 多模态模型直接看，不要先转 MD
- 已是文本（.md / .txt / 已知小 JSON）→ `Read` tool
