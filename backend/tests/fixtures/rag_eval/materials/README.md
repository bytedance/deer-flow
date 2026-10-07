# RAG evaluation materials (RFC v3 §8.1)

Distributable, license-clear corpus for the no-cloud CI path and the
real-stack smoke. All files are original content authored for this repository
and carry the repository's MIT license; no third-party corpus is included.

| File | Modality | Format | Notes |
| --- | --- | --- | --- |
| `core-java.md` | 文字 | `.md` | 语言基础考点（JDK/JRE/JVM、包装类、String、equals/hashCode、OOP、泛型） |
| `collections.md` | 文字 | `.md` | 集合框架考点 |
| `concurrency.md` | 文字 | `.md` | 并发考点 |
| `jvm.md` | 文字 | `.md` | 虚拟机考点 |
| `overview.txt` | 文字 | `.txt` | 库简介（主题级问题） |
| `lock-comparison.csv` | 表格 | `.csv` | 锁机制对比表（行卡锚定） |
| `collection-complexity.xlsx` | 表格 | `.xlsx` | 集合复杂度表（`rag.table` 门内） |
| `jvm-architecture.xlsx` | 含图 | `.xlsx` | 内嵌 JVM 架构图：图注文字经 VLM caption 进入切片正文 |

The staged pipeline (parse → chunk → embed → index) runs for real in CI; only
external model outputs are replayed from the recording (`rag_eval/ci/`),
matched by input fingerprint. `make_xlsx.py` regenerates the two workbooks
(prep-time helper; needs `openpyxl` + `Pillow`).

Index-input fingerprint: see `rag_eval/ci/manifest.json` — it binds these
files, the chunker constants and the embedding identity; a drift makes the
replay refuse to serve instead of silently mismatching.
