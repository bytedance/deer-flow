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
- Cut total file count from 7 to 4 and total LOC from ~1100 to ~330 (rough budget: SKILL.md 150 + gotchas.md 80 + formats.md 20 + batch_convert.py 80).

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
- LAN / offline. No network access for the user; batch-convert a folder of
  arbitrary files is **not** a use case. Users supply file paths in the message.

## 4. File structure (target)

```
skills/public/markitdown/
├── SKILL.md                 ~150 lines (rewrite)
├── references/
│   ├── gotchas.md           ~80 lines  (new — highest-signal content)
│   └── formats.md           ~20 lines  (new — quick reference)
└── scripts/
    └── batch_convert.py     ~80 lines  (modified — see §7)
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
  markitdown is pre-installed in the sandbox — call directly.

  Triggers: "把这份 PDF 转成 markdown", "convert this to md",
  "extract text from this PPT/DOCX", "OCR this screenshot",
  "总结这个文档", "识别这个文件", "把这个截图读一下".

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
- **Do NOT use for** — explicit negative triggers to counter false positives.

## 6. `SKILL.md` body skeleton

Modelled on the `data-analysis` skill's "触发匹配规则" + "强制 Simple Mode" pattern.

Sections:
1. **触发匹配规则（Agent 加载后必读）** — load conditions, never-load conditions.
2. **路径约定（沙箱）** — `/mnt/user-data/uploads/`, `/mnt/user-data/outputs/`,
   `/mnt/skills/public/markitdown/`.
3. **决策表** — 5 formats × 3 columns (default, gotcha, ref).
4. **Quickstart** — 10-line copy-pasteable Python snippet.
5. **单文件批量** — only when the user pastes multiple paths in one message:
   `python /mnt/skills/.../batch_convert.py --files a b c --output-dir /mnt/user-data/outputs/`.
6. **Gotchas 详解** — pointer to `references/gotchas.md`.
7. **强制单步模式（首轮）** — model must not proactively suggest "want me to
   also OCR / convert other formats / add image descriptions". User follow-up
   = new request.

"Don't state the obvious" enforcement: no `pip install`, no Python tutorial,
no enumeration of all 15 formats (lives in `formats.md`).

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

**Output format** (per file):
```
# <stem>

**Source**: <original filename>

---

<markdown content from markitdown>
```
Drops the `**Format**:` line and the `result.title` header from the current
script (the model can read the file extension from the source name, and
`result.title` is not reliably populated for all formats).

**Error semantics** (explicit, was implicit before):
- A path in `--files` that does not exist → print `⚠ Skipping: <path> (not found)` and continue with the remaining files. Do **not** abort.
- A path that exists but `MarkItDown().convert()` raises → catch the exception, print `✗ Error: <path>: <error>`, write a placeholder `.md` containing the error message, and continue.
- Exit code: `0` if at least one file succeeded, `1` if all files failed. (Mirrors the current behaviour in the existing `batch_convert.py`.)

**`convert_file()` helper signature** changes:
- Old: `convert_file(md, file_path, output_dir, verbose)`
- New: `convert_file(file_path, output_dir, verbose)` — `md` is constructed once in `batch_convert()` (was already there) and `enable_plugins` is removed. Return type unchanged: `(success: bool, path: str, message: str)`.

## 8. `references/gotchas.md` content outline

5 sections (PDF, PPTX, DOCX, JPG/PNG) plus a "何时不用 markitdown" close.

Each section is a Markdown table with three columns: 问题 / 现象 / 解决.
Includes explicit "out of scope" markers for AI image description
(OpenRouter) and other features the user excluded.

Includes tesseract install hint for OCR: `apt-get install -y tesseract-ocr`.
The container runs Linux (per `backend/Dockerfile` base image); `brew` is
unavailable inside the container. **Whether tesseract is pre-installed in the
DeerFlow image is unverified** — the implementer must `which tesseract` during
the smoke test (§10.5). If absent, either add it to the Dockerfile (out of
scope for this spec, file a follow-up issue) or instruct the user to install
it on the host before building the image.

## 9. `references/formats.md` content

A 14-row table: format, suffix, supported, has-gotcha. Single screenful. Acts
as the "all formats" reference the description deliberately omits.

## 10. Migration steps (executed by writing-plans)

1. Create `references/gotchas.md` and `references/formats.md` with content from
   §8 and §9.
2. Rewrite `SKILL.md` per §5 + §6.
3. Modify `scripts/batch_convert.py` per §7 (signature changes per §7 are
   explicit; do not assume the old signature is preserved).
4. Delete the 6 files listed in §4.
5. Smoke test:
   - Run `which tesseract` inside the container to confirm OCR availability.
     If missing, file a follow-up issue and mark the JPG/PNG gotcha as
     "OCR unavailable in current image".
   - Pick one sample per high-friction format (PDF, PPTX, DOCX, JPG/PNG) from
     `/mnt/user-data/uploads/` (or a fixture), run `MarkItDown().convert()`,
     assert output lands in `/mnt/user-data/outputs/`.
   - Run `batch_convert.py --files a.pdf b.docx missing.pdf --output-dir /tmp/o`
     and assert: `missing.pdf` produces a `⚠ Skipping` line, exit code reflects
     partial success (0 if ≥1 success, 1 if 0).
   - No integration test required (markitdown is a vendor lib).

## 11. Risks & open questions

- **Trigger phrase coverage**: the description lists 7 trigger phrases. Real
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

## 12. Out of scope (explicit)

- Audio / video / YouTube transcription support.
- AI image description (OpenRouter).
- Persistent state / `CLAUDE_PLUGIN_DATA` memory.
- Cross-skill composition (e.g. markitdown → data-analysis pipeline).
