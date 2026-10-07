# Knowledge-base acceptance samples (RFC v3 — 15-suffix matrix)

Original, license-clear samples for the real-stack acceptance (Task 8) of the
local knowledge base: one file per accepted suffix, each carrying a unique
marker token `ACCEPT8-<KIND>-<digits>` so a parse → chunk → index → retrieve
pass can prove THAT file's content landed, not just that the name is listed.
All files are authored for this repository and carry its MIT license.

| File | Marker | Notes |
| --- | --- | --- |
| `sample.md` | `ACCEPT8-MD-3174` | Markdown 正文 |
| `sample.markdown` | `ACCEPT8-MARKDOWN-8620` | Markdown 正文（长后缀） |
| `sample.txt` | `ACCEPT8-TXT-4509` | 纯文本 |
| `sample.csv` | `ACCEPT8-CSV-5527` | 逗号分隔表格，标记在单元格 |
| `sample.tsv` | `ACCEPT8-TSV-6118` | 制表符分隔表格 |
| `sample.xlsx` | `ACCEPT8-XLSX-7302` | 工作簿；A5 内嵌示意图，图内第二标记 `IMG-8841` 经 VLM caption 入切片 |
| `sample.xls` | `ACCEPT8-XLS-9266` | 旧版工作簿（xlwt 直写 BIFF） |
| `sample.pdf` | `ACCEPT8-PDF-1053` | PDF 正文（reportlab，CID 中文字体） |
| `sample.docx` | `ACCEPT8-DOCX-2287` | OOXML 文档 |
| `sample.doc` | `ACCEPT8-DOC-3390` | 旧版二进制文档（Word COM，`wdFormatDocument97`） |
| `sample.pptx` | `ACCEPT8-PPTX-4416` | OOXML 演示文稿 |
| `sample.ppt` | `ACCEPT8-PPT-5570` | 旧版二进制演示文稿（PowerPoint COM，97-2003） |
| `sample.png` | `ACCEPT8-PNG-6633` | 图片；图内文字经 caption 进入切片 |
| `sample.jpg` | `ACCEPT8-JPG-7745` | 同上（JPEG q92） |
| `sample.jpeg` | `ACCEPT8-JPEG-8812` | 同上（JPEG q92） |

## Regenerating

```bash
# needs openpyxl Pillow python-docx python-pptx reportlab xlwt
python make_samples.py .

# needs desktop Office (Word + PowerPoint); converts the two _legacy_* sources
# and removes them only after both outputs pass the OLE magic check
pwsh -NoProfile -File convert_legacy.ps1
```

`sample.doc` / `sample.ppt` must be real legacy binaries (OLE compound file,
magic `D0 CF 11 E0`). Copying an OOXML file to a `.doc`/`.ppt` name is NOT an
acceptable substitute — the point of the matrix is the legacy parse path.
