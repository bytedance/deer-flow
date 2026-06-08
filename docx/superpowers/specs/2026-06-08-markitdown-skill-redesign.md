# MarkItDown Skill Redesign — Design Spec

**Date**: 2026-06-08
**Status**: Draft — pending independent review
**Scope**: Restructure `skills/public/markitdown/` to align with 8 principles from
"Anthropic — Lessons from building Claude Code: How we use skills" (2026-06-03).
No new features. No new dependencies.

## 1. Background

The current markitdown skill is a literal port of the upstream Microsoft
`markitdown` README: 450-line `SKILL.md`, a 185-line `README.md` that duplicates
it, 3 scripts, 2 reference docs, and 1 example asset. It works, but it is not
shaped for an LLM consumer.

Symptoms measured against the blog principles:

| Symptom | Blog principle violated |
|---|---|
| `SKILL.md` and `README.md` duplicate each other | "Use the file system and progressive disclosure" |
| 450-line `SKILL.md` includes `pip install` and Python basics | "Don't state the obvious" |
| No `Gotchas` section anywhere | "Build a gotchas section" |
| Description lists supported formats instead of trigger conditions | "Write descriptions for the model, not for humans" |
| `assets/example_usage.md` is read-only docs, no executable workflow | "Skills are folders, not markdown files" |
| No memory / state across runs | "Help Claude remember" (out of scope here — single-shot conversion) |

## 2. Goals & non-goals

**Goals**
- Re-shape the skill so the lead agent can decide in <2 seconds whether to invoke it (clear description + clear triggers).
- Make the highest-signal content (gotchas) loadable on demand via `references/gotchas.md`.
- Match the file-path and trigger-rule conventions of the sibling `data-analysis` skill.
- Wire up the internal **MinerU OCR service** as the OCR backend, replacing
  tesseract for scanned PDFs and image inputs.
- Cut total file count from 7 to 5 and total LOC from ~1100 to ~400 (rough
  budget: SKILL.md 150 + gotchas.md 80 + formats.md 20 + batch_convert.py
  100 + mineru_client.py 50).

**Non-goals**
- Add AI image description (OpenRouter) — out of scope per user.
- Add audio / YouTube transcription workflows — out of scope per user.
- Add memory / state persistence — conversion is single-shot.
- Touch any other skill in `skills/public/`.

## 3. Environment constraints (DeerFlow)

- Runs inside a container. Sandbox virtual paths:
  - `/mnt/user-data/uploads/<file>` — user-uploaded input
  - `/mnt/user-data/outputs/<file>` — agent-written output
  - `/mnt/skills/public/markitdown/` — this skill
- `markitdown[pdf,docx,pptx,xlsx,html,csv,...]` is pre-installed in the
  container image. No `pip install` guidance in the skill.
- LAN / offline. No internet egress; the only network reachable from the
  container is the internal LAN where the **MinerU OCR service** runs.
  - MinerU is an internal OCR HTTP service that returns Markdown for image /
    scanned-PDF inputs.
  - Wired in via env vars: `MINERU_API_URL` (e.g. `http://mineru.lan:8000`)
    and `MINERU_API_KEY`. The skill **fails fast** with a clear error if
    `MINERU_API_URL` is unset and an OCR call is attempted — better than
    silently returning empty output.
- LAN / offline also means: no batch-convert-a-folder of arbitrary files is
  a use case. Users supply file paths in the message.

## 4. File structure (target)

```
skills/public/markitdown/
├── SKILL.md                 ~150 lines (rewrite)
├── references/
│   ├── gotchas.md           ~80 lines  (new — highest-signal content)
│   └── formats.md           ~20 lines  (new — quick reference)
└── scripts/
    ├── batch_convert.py     ~100 lines (modified — see §7, adds OCR routing)
    └── mineru_client.py     ~50 lines  (new — thin HTTP wrapper)
```

**Deletions** (with reason):

| File | Reason |
|---|---|
| `README.md` | Duplicates `SKILL.md`; model does not read it |
| `references/api_reference.md` | Content is just the standard `markitdown.MarkItDown` API surface (constructor params, `convert()` / `convert_stream()` signatures) — model already knows this from Python knowledge |
| `references/file_formats.md` | Per-format blurb with `pip install` and "Best For / Limitations" prose — exactly the "feature table" anti-pattern. Replaced by the 1-screen `formats.md` table |
| `assets/example_usage.md` | Information merged into `gotchas.md` + decision table |
| `scripts/convert_with_ai.py` | Depends on OpenRouter; out of scope |
| `scripts/convert_literature.py` | Specialized workflow; replaced by general gotchas |

Note: `batch_convert.py` is being **modified**, not deleted, and the `--plugins`
flag is dropped because no markitdown plugins are installed in the container
image (verified by inspection of `backend/Dockerfile` — `pip install` line
installs only the `[pdf,docx,pptx,xlsx,html]` extras).

## 5. Frontmatter `description`

The description is the trigger. Per the blog it must be written for the model,
be "pushy" (counter undertriggering), and explicitly state when **not** to use.

```yaml
description: |
  Convert a single uploaded document to clean Markdown for LLM consumption.
  Primary formats with non-obvious gotchas: PDF, PPTX, DOCX, JPG, PNG.
  Also supports XLSX, HTML, CSV, EPUB, JSON, XML.
  OCR for images and scanned PDFs is routed to the internal MinerU service
  (env: MINERU_API_URL, MINERU_API_KEY).
  markitdown is pre-installed in the sandbox — call directly.

  Triggers: "把这份 PDF 转成 markdown", "convert this to md",
  "extract text from this PPT/DOCX", "OCR this screenshot",
  "总结这个文档", "识别这个文件", "把这个截图读一下",
  "读这个扫描件".

  Do NOT use for: audio files, video files, YouTube URLs,
  batch-convert a folder, or anything already in text form
  (use Read tool directly).
```

Why this shape:
- **Single-file framing** — environment is offline; "batch-convert a folder"
  removed (would otherwise overtrigger).
- **"Also supports" line** — XLSX/HTML/CSV/EPUB/JSON/XML stay in scope (they are
  real supported formats), but are not the gotcha focus.
- **Sandbox note** — saves the model from attempting `pip install`.
- **OCR backend named** — makes the MinerU dependency discoverable without the
  model having to read `gotchas.md`.
- **Do NOT use for** — explicit negative triggers to counter false positives.

## 6. `SKILL.md` body skeleton

Modelled on the `data-analysis` skill's "触发匹配规则" + "强制 Simple Mode" pattern.

Sections:
1. **触发匹配规则（Agent 加载后必读）** — load conditions, never-load conditions.
2. **路径约定（沙箱）** — `/mnt/user-data/uploads/`, `/mnt/user-data/outputs/`,
   `/mnt/skills/public/markitdown/`.
3. **决策表** — 6 rows (PDF/PPTX/DOCX/JPG/PNG/others) × 3 columns
   (default backend, fallback, ref).
4. **Quickstart — text-based file** — 10-line Python snippet using `MarkItDown`.
5. **Quickstart — image / scanned file** — 6-line Python snippet calling
   `mineru_client.ocr_to_markdown()`.
6. **单文件批量** — only when the user pastes multiple paths in one message:
   `python /mnt/skills/.../batch_convert.py --files a b c --output-dir /mnt/user-data/outputs/`.
7. **Gotchas 详解** — pointer to `references/gotchas.md`.
8. **强制单步模式（首轮）** — model must not proactively suggest "want me to
   also OCR / convert other formats / add image descriptions". User follow-up
   = new request.

"Don't state the obvious" enforcement: no `pip install`, no Python tutorial,
no enumeration of all 15 formats (lives in `formats.md`).

The decision table (section 3) looks like:

| 格式 | 主路径 | fallback | 必看 gotcha |
|---|---|---|---|
| PDF（文本型） | `MarkItDown().convert()` | — | 复杂表格、多栏 |
| PDF（扫描件） | `mineru_client.ocr_to_markdown()` | markitdown 若返回 < 50 字符则改走 MinerU | — |
| PPTX | `MarkItDown().convert()` | — | 讲者备注默认不含 |
| DOCX | `MarkItDown().convert()` | — | 批注 / 修订不含 |
| JPG/PNG | `mineru_client.ocr_to_markdown()` | — | HEIC 不支持、需先转 |
| XLSX/HTML/CSV/EPUB/JSON/XML | `MarkItDown().convert()` | — | — |

## 7. `scripts/batch_convert.py` changes

**Old interface** (current):
```
batch_convert.py <input_dir> <output_dir> --extensions .pdf --recursive --workers 4 --plugins
```

**New interface** (target):
```
batch_convert.py --files <path1> <path2> ... --output-dir <dir> [--workers 4] [--verbose]
```

Changes:
- Replace `--input-dir` + `--extensions` + `--recursive` with explicit `--files <nargs+>`.
- Make `--files` and `--output-dir` both required (no positional args).
- Keep `--workers` (default 4) and `--verbose`.
- Drop `--plugins` (no plugins installed in the image — see §4).
- Default extension guessing: infer from `Path.suffix`; no need for a default
  extension list since the user supplies paths explicitly.

**Routing logic** (in `convert_file()`):
```python
def convert_file(file_path, output_dir, verbose):
    suffix = file_path.suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png"}:
        # Pure image: always MinerU
        text = mineru_client.ocr_to_markdown(str(file_path))
    else:
        # Try markitdown first
        result = MarkItDown().convert(str(file_path))
        text = result.text_content
        if len(text.strip()) < OCR_FALLBACK_THRESHOLD:  # default: 50 chars
            # Scanned PDF / image-only PDF: fall back to MinerU
            if verbose:
                print(f"markitdown returned <{OCR_FALLBACK_THRESHOLD} chars, falling back to MinerU")
            text = mineru_client.ocr_to_markdown(str(file_path))
    # Write output (unchanged shape)
```

`OCR_FALLBACK_THRESHOLD` is a module constant; default `50`. Configurable via
`--ocr-fallback-threshold N` CLI flag for tuning, but the default is the
contract.

**Output format** (per file):
```
# <stem>

**Source**: <original filename>

---

<markdown content from markitdown or MinerU>
```
Drops the `**Format**:` line and the `result.title` header from the current
script (the model can read the file extension from the source name, and
`result.title` is not reliably populated for all formats).

**Error semantics** (explicit, was implicit before):
- A path in `--files` that does not exist → print `⚠ Skipping: <path> (not found)` and continue with the remaining files. Do **not** abort.
- A path that exists but `MarkItDown().convert()` raises → catch the exception, print `✗ Error: <path>: <error>`, write a placeholder `.md` containing the error message, and continue.
- A MinerU call raises (network / 4xx / 5xx / timeout) → catch, print `✗ Error: <path>: MinerU <status>`, write placeholder, and continue. Do **not** retry — that is the caller's concern.
- Exit code: `0` if at least one file succeeded, `1` if all files failed.

**`convert_file()` helper signature** changes:
- Old: `convert_file(md, file_path, output_dir, verbose)`
- New: `convert_file(file_path, output_dir, verbose)` — `md` is constructed once in `batch_convert()` (was already there) and `enable_plugins` is removed. Return type unchanged: `(success: bool, path: str, message: str)`.

## 7.1. `scripts/mineru_client.py` (new)

Thin HTTP wrapper. Public API:

```python
def ocr_to_markdown(file_path: str, *, timeout: int = 60) -> str:
    """POST file to MinerU, return Markdown text. Raises on error.

    Requires env: MINERU_API_URL (required), MINERU_API_KEY (required).
    """
    ...
```

Behavior:
- Reads file as binary, `POST` to `${MINERU_API_URL}/ocr` (path is the
  implementer's call; if MinerU's actual endpoint differs, adjust — confirm
  with the MinerU deployment doc during implementation).
- Sends `Authorization: Bearer ${MINERU_API_KEY}` header.
- Multipart form with `file` field.
- Parses JSON response, returns the `markdown` (or `text` / `content` — confirm
  field name in the response).
- Raises `MinerUError` on any non-2xx, with the response body in `.body` for
  debugging.
- 60-second default timeout (configurable).

No retry logic in this module — kept simple. `batch_convert.py` does not retry
either. If the LAN has transient failures, the implementer can add a thin
decorator later (out of scope).

## 8. `references/gotchas.md` content outline

5 sections (PDF, PPTX, DOCX, JPG/PNG, MinerU) plus a "何时不用 markitdown" close.

Each section is a Markdown table with three columns: 问题 / 现象 / 解决.
Includes explicit "out of scope" markers for AI image description
(OpenRouter) and other features the user excluded.

The **MinerU section** covers:
- Required env vars: `MINERU_API_URL` and `MINERU_API_KEY`. If unset when an
  image / scanned PDF is converted, the skill fails fast with a clear error.
- API endpoint shape (path, auth header) — to be confirmed during
  implementation against the actual MinerU deployment; the spec is a contract
  on the wrapper, not on the wire format.
- Network reachability from the container: assumed LAN-routable; if not,
  smoke test (§10.5) catches it.
- Image-only PDFs: detected by `len(markitdown_output.strip()) < 50` chars
  (configurable). Below threshold → fall back to MinerU.
- HEIC / other unsupported image formats: tell the user to convert to PNG /
  JPG first.
- Failure mode: any non-2xx from MinerU raises `MinerUError`; the caller
  (batch_convert or the agent) decides whether to retry / fail.

**Out of scope** (explicit): tesseract, OpenRouter, Azure Document Intelligence,
any other OCR backend. MinerU is the only OCR backend this skill uses.

## 9. `references/formats.md` content

A 14-row table: format, suffix, supported, has-gotcha. Single screenful. Acts
as the "all formats" reference the description deliberately omits.

## 10. Migration steps (executed by writing-plans)

1. Create `references/gotchas.md` and `references/formats.md` with content from
   §8 and §9.
2. Create `scripts/mineru_client.py` per §7.1. Confirm the actual MinerU
   endpoint path and response field name against the deployment during
   implementation; the wrapper contract is fixed but the wire format is TBD.
3. Rewrite `SKILL.md` per §5 + §6.
4. Modify `scripts/batch_convert.py` per §7 (signature changes per §7 are
   explicit; do not assume the old signature is preserved).
5. Delete the 6 files listed in §4.
6. Smoke test:
   - **Confirm MinerU env vars** are set in the container (`echo $MINERU_API_URL`
     non-empty; `echo $MINERU_API_KEY` non-empty). If unset, document in
     `.env.example` and the README, and the smoke test must surface this
     rather than skip.
   - **Confirm MinerU reachability** with a 1-line curl: `curl -fsS
     ${MINERU_API_URL}/health` (or whatever the actual health endpoint is).
   - Pick one sample per high-friction format (PDF text-based, PDF scanned,
     PPTX, DOCX, JPG, PNG) from `/mnt/user-data/uploads/` (or a fixture).
   - Run `MarkItDown().convert()` and `mineru_client.ocr_to_markdown()` against
     the samples; assert output lands in `/mnt/user-data/outputs/`.
   - Run `batch_convert.py --files a.pdf b.docx missing.pdf image.png
     scanned.pdf --output-dir /tmp/o` and assert:
     - `missing.pdf` produces a `⚠ Skipping` line
     - `image.png` and `scanned.pdf` go through the MinerU path
     - `a.pdf` and `b.docx` go through the markitdown path
     - Exit code reflects partial success (0 if ≥1 success, 1 if 0).
   - No integration test required (markitdown is a vendor lib; MinerU is
     a vendor service).

## 11. Risks & open questions

- **Trigger phrase coverage**: the description lists 8 trigger phrases. Real
  usage may surface others. Mitigation: future iterations re-run
  `skill-creator/scripts/run_eval.py` against a trigger-eval set (requires
  enabling the `skill-creator` skill — currently disabled in
  `extensions_config.json`; track as a follow-up).
- **Gotcha correctness**: §8 content is written from common markitdown
  knowledge, not validated against the current container image. Implementation
  must verify each gotcha empirically during the smoke test.
- **Backward compatibility**: deleting `README.md` and 5 other files. The
  skill directory is untracked in git (no prior commits reference it), and
  grep confirms no other skill/script imports the 5 deleted files. Deletion is
  safe.
- **Single path vs `batch_convert.py` routing**: §6 says "单文件批量" only
  fires when the user pastes multiple paths. If the user pastes exactly one
  path, the model should use the Python Quickstart one-liner, not invoke
  `batch_convert.py` (it would just add a subprocess layer for no benefit).
  This rule is implicit in §6; if the implementer is unsure, default to the
  Python one-liner.
- **MinerU API contract drift**: §7.1 codifies a wrapper contract, but the
  wire format (path, request body, response field name) is TBD until
  implementation confirms it against the actual MinerU deployment. If MinerU
  returns a different field name than `markdown`, the wrapper must be
  updated. The skill-internal contract (function signature, exception type)
  does not change.
- **MinerU availability**: if `MINERU_API_URL` is unset or unreachable, OCR
  paths fail. The skill is intentionally **fail-fast** (no silent fallback to
  tesseract or any other OCR), because the user's stated requirement is to
  use MinerU, not to find *some* OCR. Document the env vars in `.env.example`.
- **OCR fallback threshold (50 chars)**: a magic number. May be too lax for
  small legitimate PDFs ("Hello world" PDF) and too strict for image-heavy
  PDFs that produce 200 chars of metadata. Configurable via
  `--ocr-fallback-threshold`; default 50 is the contract, tuning happens at
  evaluation time.

## 12. Out of scope (explicit)

- Audio / video / YouTube transcription support.
- AI image description (OpenRouter).
- Tesseract / any local OCR. The only OCR backend is the internal MinerU
  service.
- Azure Document Intelligence.
- Persistent state / `CLAUDE_PLUGIN_DATA` memory.
- Cross-skill composition (e.g. markitdown → data-analysis pipeline).
