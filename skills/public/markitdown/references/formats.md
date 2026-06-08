# Format Quick Reference

Single-screen reference for which formats markitdown supports and which have gotchas.

| 格式 | 后缀 | markitdown | 有 gotcha？ |
|---|---|---|---|
| PDF（文本型） | .pdf | ✓ | ⚠️ 详见 gotchas.md |
| PDF（扫描件） | .pdf | — | 走 MinerU（`markitdown[pdf]` 不能 OCR） |
| PowerPoint | .pptx | ✓ | ⚠️ 讲者备注默认不含 |
| Word | .docx | ✓ | ⚠️ 批注 / 修订默认不含 |
| Excel | .xlsx, .xls | ✓ | — |
| 图片 | .jpg, .jpeg, .png | — | 走 MinerU；HEIC 不支持 |
| HTML | .html, .htm | ✓ | — |
| CSV | .csv | ✓ | — |
| JSON | .json | ✓ | — |
| XML | .xml | ✓ | — |
| EPUB | .epub | ✓ | — |
| ZIP | .zip | ✓ | 内部文件分别转 |
| 音频 | .mp3, .wav | ✓ | 不在 gotchas 范围 |
| YouTube URL | — | ✓ | 不在 gotchas 范围 |

**OCR 后端**：内部 MinerU 服务（env: `MINERU_API_URL`, `MINERU_API_KEY`）。
不依赖 tesseract，不依赖 OpenRouter，不依赖 Azure Document Intelligence。
