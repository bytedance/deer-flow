---
name: markitdown
license: MIT
source: https://github.com/microsoft/markitdown
description: |
  Convert an uploaded document to clean Markdown. Supports PDF, PPTX, DOCX, JPG, PNG ; XLSX/HTML/CSV/EPUB/JSON/XML are also fine. Images and scanned PDFs are OCR'd via the internal MinerU service.
  Triggers: "把这份 PDF 转成 markdown", "把这个截图读一下", "识别这个文件", "读这个扫描件", "总结这个文档".
  Do NOT use for: audio/video files, YouTube URLs, batch-converting a folder, or files already in text form (use Read tool).
---

# MarkItDown Skill

Convert one uploaded document to Markdown. Use for: PDF, PPTX, DOCX, JPG, PNG
(gotchas), plus XLSX / HTML / CSV / EPUB / JSON / XML (straight convert).
OCR backend: internal MinerU service (LAN HTTP, returns Markdown).

## 触发匹配规则（Agent 加载后必读）

**加载条件**：用户消息含以下任一组合：
- 文档类动词 + 文件名/路径：`转换 / 转成 / 提取 / 读一下 / 解析 / OCR / 识别 / 总结 / 看一下`
- 明确的文件扩展名：`.pdf / .pptx / .docx / .xlsx / .html / .csv / .epub / .json / .xml / .jpg / .png`

**绝不加载**：
- 文件是音频 / 视频 / YouTube
- 文件已是文本（`.md / .txt / .py / .json` 已被 user 编辑过 / `.csv` 已经很小）
- 用户只问"这个文件存在吗"等元信息
- 用户要求批处理一个目录（本 skill 只处理用户在消息里贴出的文件路径）

## 路径约定（沙箱）

| 类型 | 路径 |
|---|---|
| 用户上传 | `/mnt/user-data/uploads/<file>` |
| 输出 MD | `/mnt/user-data/outputs/<stem>.md` |
| 技能脚本 | `/mnt/skills/public/markitdown/scripts/{batch_convert.py, mineru_client.py}` |
| 技能文档 | `/mnt/skills/public/markitdown/references/{gotchas.md, formats.md}` |

## 决策表

| 格式 | 主路径 | fallback | 必看 gotcha |
|---|---|---|---|
| PDF（文本型） | `MarkItDown().convert()` | — | 复杂表格、多栏 |
| PDF（扫描件） | `mineru_client.ocr_to_markdown()` | markitdown 若返回 < 50 字符则改走 MinerU | — |
| PPTX | `MarkItDown().convert()` | — | 讲者备注默认不含 |
| DOCX | `MarkItDown().convert()` | — | 批注 / 修订不含 |
| JPG / PNG | `mineru_client.ocr_to_markdown()` | — | HEIC 不支持、需先转 |
| XLSX / HTML / CSV / EPUB / JSON / XML | `MarkItDown().convert()` | — | — |

## Quickstart — 文本型文件

```python
from markitdown import MarkItDown
from pathlib import Path

src = Path("/mnt/user-data/uploads/report.pdf")
dst = Path("/mnt/user-data/outputs/report.md")

md = MarkItDown()
result = md.convert(str(src))
content = result.text_content or ""
dst.write_text(content, encoding="utf-8")
# 也把内容写到 stdout，让 agent 在最终回复里直接展示给用户
# （见 "## 输出与后续处理"）
print(content)
```

## Quickstart — 图片 / 扫描件

```python
import sys
sys.path.insert(0, "/mnt/skills/public/markitdown/scripts")
import mineru_client

text = mineru_client.ocr_to_markdown("/mnt/user-data/uploads/photo.png")
with open("/mnt/user-data/outputs/photo.md", "w", encoding="utf-8") as f:
    f.write(text)
# 也把内容写到 stdout，让 agent 在最终回复里直接展示给用户
# （见 "## 输出与后续处理"）
print(text)
```

**注意**：`MINERU_API_URL` 和 `MINERU_API_KEY` 必须在容器 env 中设置；缺则 `MinerUError`。

## 单文件批量（多个独立上传）

> 仅当用户在一次消息里贴了**多个**文件路径时使用。单文件用上面的 Quickstart。

```bash
python /mnt/skills/public/markitdown/scripts/batch_convert.py \
  --files /mnt/user-data/uploads/a.pdf /mnt/user-data/uploads/b.docx \
  --output-dir /mnt/user-data/outputs/
```

可选 `--workers N`（默认 4）、`--verbose`。

## 输出与后续处理

script 内部已经 `print(content)` 把 MD body 写到 stdout —— agent 拿到 tool result 后应当：

- 单文件 MD < 500 行：把 content 直接放进 agent 的最终回复里给用户看
- 单文件 MD ≥ 500 行：内容已经在 `/mnt/user-data/outputs/<stem>.md`，agent 调 `present_files` 工具分享给用户，不要把全文塞进回复
- 多文件批量：按上面的阈值逐个判断，**整批**全 ≥ 500 行时只 share 文件
- 关键发现用 2-3 句自然语言总结（标题、章节、表格、图片数等）
- 不主动建议"要不要也 OCR 别的格式 / 加图片描述" —— 用户追问再处理

## Gotchas 详解

**必读** `references/gotchas.md`：
- PDF：扫描件检测、表格、加密、多栏
- PPTX：讲者备注、SmartArt
- DOCX：批注、修订、嵌入对象
- JPG / PNG：HEIC、EXIF、无图说
- MinerU：env vars、不可达、4xx/5xx

**速查** `references/formats.md`：所有支持格式一览。

**Don't state the obvious**：本文不写 pip install、Python 基础语法、markitdown 安装。
模型已会这些。

## 强制单步模式（首轮）

- 单个文件 → 直接 convert + 写 outputs
- **不主动建议** "要不要也 OCR / 跑别的格式 / 加图片描述"
- 用户追问 → 视为新请求
