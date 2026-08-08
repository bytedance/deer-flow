# Upload Markdown Provenance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve each current-turn upload's exact converted Markdown companion through the web message contract so `UploadsMiddleware` grounds the agent with the correct document outline.

**Architecture:** Add a pure frontend mapper that carries the existing nullable `markdown_file` response into `HumanMessage.additional_kwargs.files`, then validate that metadata inside `UploadsMiddleware`. Explicit valid companions use a new exact-Markdown extraction function, explicit null or invalid metadata disables sibling guessing, and legacy messages without the key retain the existing `<stem>.md` fallback.

**Tech Stack:** TypeScript, React submit pipeline, Rstest, Python 3.12+, LangChain/LangGraph middleware, pytest, Ruff, Blockbuster.

## Global Constraints

- Scope is current-turn web uploads only; do not add a historical manifest or change `list_uploaded_files`.
- Do not change conversion naming, upload collision policy, storage layout, or deletion behavior.
- Do not render `markdown_file` in the attachment UI or include the raw value in model-visible prompt text.
- A present `markdown_file` key is authoritative: valid string uses that file; null or invalid metadata produces no outline and never falls back to `<stem>.md`.
- An absent `markdown_file` key is legacy metadata and must retain sibling lookup.
- Companion strings must be basename-only `.md` names, must not be staging names or symlinks, and must identify an existing regular file when the uploads directory is available.
- Invalid companion metadata must not reject an otherwise valid source upload or fail the agent run.
- Add no dependency.
- Follow red-green-refactor: every production behavior change is preceded by a focused test that is observed failing for the intended reason.
- Keep `backend/AGENTS.md` and `backend/docs/FILE_UPLOAD.md` synchronized with the implemented contract.

---

## File Structure

- Create `frontend/src/core/uploads/message-files.ts`: pure API-response-to-message metadata mapping.
- Create `frontend/tests/unit/core/uploads/message-files.test.ts`: mapper contract tests.
- Modify `frontend/src/core/uploads/api.ts`: reflect the backend's nullable `markdown_file` response.
- Modify `frontend/src/core/uploads/index.ts`: export the mapper.
- Modify `frontend/src/core/messages/utils.ts`: extend `FileInMessage` with nullable provenance.
- Modify `frontend/src/core/threads/hooks.ts`: use one mapper for optimistic and submitted message paths.
- Modify `frontend/tests/unit/core/threads/send-message.test.ts`: verify provenance remains on the visible human message.
- Modify `backend/packages/harness/deerflow/utils/file_outline.py`: extract outline/preview from an exact Markdown path and retain the legacy wrapper.
- Modify `backend/packages/harness/deerflow/agents/middlewares/uploads_middleware.py`: validate tri-state companion metadata and select exact versus legacy extraction.
- Modify `backend/tests/test_uploads_middleware_core_logic.py`: cover collision grounding, null semantics, validation, and compatibility.
- Modify `backend/docs/FILE_UPLOAD.md`: document the message contract.
- Modify `backend/AGENTS.md`: record the maintained middleware invariant.

---

### Task 1: Carry nullable Markdown provenance through the frontend submit contract

**Files:**
- Create: `frontend/src/core/uploads/message-files.ts`
- Create: `frontend/tests/unit/core/uploads/message-files.test.ts`
- Modify: `frontend/src/core/uploads/api.ts:8-20`
- Modify: `frontend/src/core/uploads/index.ts:1-10`
- Modify: `frontend/src/core/messages/utils.ts:741-750`
- Modify: `frontend/src/core/threads/hooks.ts:17-35,2148-2160,2190-2198`
- Modify: `frontend/tests/unit/core/threads/send-message.test.ts:31-62`

**Interfaces:**
- Consumes: `UploadedFileInfo` from `frontend/src/core/uploads/api.ts`.
- Produces: `uploadedFileInfoToMessageFile(info: UploadedFileInfo): FileInMessage`.
- Produces: `FileInMessage.markdown_file?: string | null` in `additional_kwargs.files`.

- [ ] **Step 1: Write the failing mapper tests**

Create `frontend/tests/unit/core/uploads/message-files.test.ts`:

```typescript
import { expect, test } from "@rstest/core";

import type { UploadedFileInfo } from "@/core/uploads/api";
import { uploadedFileInfoToMessageFile } from "@/core/uploads/message-files";

const BASE_INFO: UploadedFileInfo = {
  filename: "a.pdf",
  size: 42,
  path: "backend-path/a.pdf",
  virtual_path: "/mnt/user-data/uploads/a.pdf",
  artifact_url: "/api/artifacts/a.pdf",
};

test("preserves a collision-renamed Markdown companion", () => {
  expect(
    uploadedFileInfoToMessageFile({
      ...BASE_INFO,
      markdown_file: "a_1.md",
    }),
  ).toEqual({
    filename: "a.pdf",
    size: 42,
    path: "/mnt/user-data/uploads/a.pdf",
    status: "uploaded",
    markdown_file: "a_1.md",
  });
});

test("records explicit null when the upload has no Markdown companion", () => {
  expect(uploadedFileInfoToMessageFile(BASE_INFO)).toEqual({
    filename: "a.pdf",
    size: 42,
    path: "/mnt/user-data/uploads/a.pdf",
    status: "uploaded",
    markdown_file: null,
  });
});
```

Extend `frontend/tests/unit/core/threads/send-message.test.ts` so the existing `keeps uploaded files on the visible user message only` case passes `markdown_file: "report_1.md"` in `filesForSubmit` and expects the same field in `messages[1].additional_kwargs.files[0]`.

- [ ] **Step 2: Run the frontend tests and verify RED**

From `frontend/`, run:

```powershell
pnpm test -- tests/unit/core/uploads/message-files.test.ts tests/unit/core/threads/send-message.test.ts
```

Expected: FAIL because `@/core/uploads/message-files` and `uploadedFileInfoToMessageFile` do not exist. If the send-message assertion is reached before the missing-module failure, it must not report any production-code exception unrelated to the new contract.

- [ ] **Step 3: Implement the nullable types and pure mapper**

In `frontend/src/core/uploads/api.ts`, change the field to:

```typescript
  markdown_file?: string | null;
```

In `frontend/src/core/messages/utils.ts`, extend `FileInMessage`:

```typescript
export interface FileInMessage {
  filename: string;
  size: number; // bytes
  path?: string; // virtual path, may not be set during upload
  status?: "uploading" | "uploaded";
  markdown_file?: string | null; // explicit converted companion provenance
}
```

Create `frontend/src/core/uploads/message-files.ts`:

```typescript
import type { FileInMessage } from "../messages/utils";
import type { UploadedFileInfo } from "./api";

export function uploadedFileInfoToMessageFile(
  info: UploadedFileInfo,
): FileInMessage {
  return {
    filename: info.filename,
    size: info.size,
    path: info.virtual_path,
    status: "uploaded",
    markdown_file: info.markdown_file ?? null,
  };
}
```

Export it from `frontend/src/core/uploads/index.ts`:

```typescript
export * from "./message-files";
```

- [ ] **Step 4: Wire both submit paths to the shared mapper**

In `frontend/src/core/threads/hooks.ts`, import the mapper with the existing upload helpers:

```typescript
import {
  promptInputFilePartToFile,
  uploadedFileInfoToMessageFile,
  uploadFiles,
} from "../uploads";
```

Replace the optimistic uploaded-file mapping with:

```typescript
const uploadedFiles = uploadedFileInfo.map(uploadedFileInfoToMessageFile);
```

Replace the submitted-file mapping with:

```typescript
const filesForSubmit = uploadedFileInfo.map(uploadedFileInfoToMessageFile);
```

Keep `uploadedFileInfo: UploadedFileInfo[]` typed as it is; do not change the pre-upload optimistic objects because no API provenance exists before upload completes.

- [ ] **Step 5: Run focused frontend verification and verify GREEN**

From `frontend/`, run:

```powershell
pnpm test -- tests/unit/core/uploads/message-files.test.ts tests/unit/core/threads/send-message.test.ts
pnpm typecheck
pnpm exec eslint src/core/uploads/api.ts src/core/uploads/message-files.ts src/core/uploads/index.ts src/core/messages/utils.ts src/core/threads/hooks.ts tests/unit/core/uploads/message-files.test.ts tests/unit/core/threads/send-message.test.ts
pnpm exec prettier --check src/core/uploads/api.ts src/core/uploads/message-files.ts src/core/uploads/index.ts src/core/messages/utils.ts src/core/threads/hooks.ts tests/unit/core/uploads/message-files.test.ts tests/unit/core/threads/send-message.test.ts
```

Expected: both focused test files pass; TypeScript, ESLint, and Prettier exit 0.

- [ ] **Step 6: Commit the frontend contract**

```powershell
git add frontend/src/core/uploads/api.ts frontend/src/core/uploads/message-files.ts frontend/src/core/uploads/index.ts frontend/src/core/messages/utils.ts frontend/src/core/threads/hooks.ts frontend/tests/unit/core/uploads/message-files.test.ts frontend/tests/unit/core/threads/send-message.test.ts
git commit -m "fix(frontend): preserve upload markdown provenance"
```

---

### Task 2: Validate and consume explicit Markdown companions in UploadsMiddleware

**Files:**
- Modify: `backend/tests/test_uploads_middleware_core_logic.py:70-167,624-728`
- Modify: `backend/packages/harness/deerflow/utils/file_outline.py:127-162`
- Modify: `backend/packages/harness/deerflow/agents/middlewares/uploads_middleware.py:18-23,163-199,244-252`

**Interfaces:**
- Consumes: `additional_kwargs.files[].markdown_file` as absent, null, or string.
- Produces: `_normalize_markdown_companion(file_metadata, uploads_dir, source_filename) -> tuple[bool, str | None]`; the boolean records key presence.
- Produces: `extract_outline_from_markdown(md_path: Path) -> tuple[list[dict], list[str]]`.
- Preserves: `extract_outline_for_file(file_path: Path)` as the legacy sibling-lookup interface.

- [ ] **Step 1: Add failing metadata-normalization tests**

Extend the existing mock import so the symlink check is portable on Windows:

```python
from unittest.mock import MagicMock, patch
```

Add these cases to `TestFilesFromKwargs` in `backend/tests/test_uploads_middleware_core_logic.py`:

```python
    def test_preserves_valid_explicit_markdown_companion(self, tmp_path):
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "a.pdf").write_bytes(b"pdf")
        (uploads_dir / "a_1.md").write_text("# PDF OUTLINE", encoding="utf-8")
        msg = _human(
            "summarize",
            files=[
                {
                    "filename": "a.pdf",
                    "size": 3,
                    "path": "/mnt/user-data/uploads/a.pdf",
                    "markdown_file": "a_1.md",
                }
            ],
        )

        result = mw._files_from_kwargs(msg, uploads_dir)

        assert result is not None
        assert result[0]["markdown_file"] == "a_1.md"

    def test_preserves_explicit_null_markdown_companion(self, tmp_path):
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "a.pdf").write_bytes(b"pdf")
        msg = _human(
            "summarize",
            files=[{"filename": "a.pdf", "size": 3, "markdown_file": None}],
        )

        result = mw._files_from_kwargs(msg, uploads_dir)

        assert result is not None
        assert "markdown_file" in result[0]
        assert result[0]["markdown_file"] is None

    def test_normalizes_invalid_explicit_markdown_companions_to_null(self, tmp_path):
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "a.pdf").write_bytes(b"pdf")

        for invalid_value in (
            "../outside.md",
            "..\\outside.md",
            "notes.txt",
            ".upload-active.part",
            "missing.md",
            42,
        ):
            msg = _human(
                "summarize",
                files=[
                    {
                        "filename": "a.pdf",
                        "size": 3,
                        "markdown_file": invalid_value,
                    }
                ],
            )

            result = mw._files_from_kwargs(msg, uploads_dir)

            assert result is not None
            assert "markdown_file" in result[0]
            assert result[0]["markdown_file"] is None

    def test_rejects_a_symlink_markdown_companion(self, tmp_path):
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "a.pdf").write_bytes(b"pdf")
        (uploads_dir / "a.md").write_text("# linked", encoding="utf-8")
        msg = _human(
            "summarize",
            files=[
                {
                    "filename": "a.pdf",
                    "size": 3,
                    "markdown_file": "a.md",
                }
            ],
        )

        with patch.object(Path, "is_symlink", return_value=True):
            result = mw._files_from_kwargs(msg, uploads_dir)

        assert result is not None
        assert result[0]["markdown_file"] is None
```

- [ ] **Step 2: Add failing Agent grounding tests**

Add these cases to `TestBeforeAgent`:

```python
    def test_explicit_companion_prevents_same_stem_outline_crosstalk(self, tmp_path):
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "a.pdf").write_bytes(b"pdf")
        (uploads_dir / "a.md").write_text("# WRONG DOCX OUTLINE", encoding="utf-8")
        (uploads_dir / "a_1.md").write_text("# CORRECT PDF OUTLINE", encoding="utf-8")
        msg = _human(
            "summarize",
            files=[
                {
                    "filename": "a.pdf",
                    "size": 3,
                    "markdown_file": "a_1.md",
                }
            ],
        )

        result = mw.before_agent(self._state(msg), _runtime())

        assert result is not None
        content = result["messages"][-1].content
        assert "CORRECT PDF OUTLINE" in content
        assert "WRONG DOCX OUTLINE" not in content
        assert "a_1.md" not in content

    def test_explicit_null_does_not_guess_a_same_stem_companion(self, tmp_path):
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "a.pdf").write_bytes(b"pdf")
        (uploads_dir / "a.md").write_text("# UNRELATED OUTLINE", encoding="utf-8")
        msg = _human(
            "summarize",
            files=[{"filename": "a.pdf", "size": 3, "markdown_file": None}],
        )

        result = mw.before_agent(self._state(msg), _runtime())

        assert result is not None
        content = result["messages"][-1].content
        assert "UNRELATED OUTLINE" not in content
        assert "Document outline" not in content

    def test_unsafe_explicit_companion_does_not_fallback_or_escape(self, tmp_path):
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "a.pdf").write_bytes(b"pdf")
        (uploads_dir / "a.md").write_text("# UNRELATED SIBLING", encoding="utf-8")
        (uploads_dir.parent / "outside.md").write_text("# OUTSIDE", encoding="utf-8")
        msg = _human(
            "summarize",
            files=[
                {
                    "filename": "a.pdf",
                    "size": 3,
                    "markdown_file": "../outside.md",
                }
            ],
        )

        result = mw.before_agent(self._state(msg), _runtime())

        assert result is not None
        content = result["messages"][-1].content
        assert "UNRELATED SIBLING" not in content
        assert "OUTSIDE" not in content
```

Do not modify the existing `test_outline_injected_when_md_file_exists`; it is the legacy absent-key compatibility anchor.

- [ ] **Step 3: Run the backend regression file and verify RED**

From `backend/`, run:

```powershell
$env:PYTHONPATH='.'
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONUTF8='1'
uv run pytest tests/test_uploads_middleware_core_logic.py -v
```

Expected: the existing tests pass, while the new tests fail because `_files_from_kwargs` drops `markdown_file` and `before_agent` reads `a.md` instead of the explicit `a_1.md`.

- [ ] **Step 4: Extract exact-Markdown outline parsing**

In `backend/packages/harness/deerflow/utils/file_outline.py`, move the body that currently reads `file_path.with_suffix(".md")` into this exact-path function:

```python
def extract_outline_from_markdown(md_path: Path) -> tuple[list[dict], list[str]]:
    """Return the document outline and fallback preview for an exact Markdown path."""
    if not md_path.is_file():
        return [], []

    outline = extract_outline(md_path)
    if outline:
        logger.debug("Extracted %d outline entries from %s", len(outline), md_path.name)
        return outline, []

    preview: list[str] = []
    try:
        with md_path.open(encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    preview.append(stripped)
                if len(preview) >= _OUTLINE_PREVIEW_LINES:
                    break
    except Exception:
        logger.debug("Failed to read preview lines from %s", md_path, exc_info=True)
    return [], preview
```

Keep the existing public function as the compatibility wrapper:

```python
def extract_outline_for_file(file_path: Path) -> tuple[list[dict], list[str]]:
    """Return outline data from the legacy same-stem Markdown companion."""
    return extract_outline_from_markdown(file_path.with_suffix(".md"))
```

- [ ] **Step 5: Validate tri-state companion metadata in UploadsMiddleware**

Import both outline functions:

```python
from deerflow.utils.file_outline import extract_outline_for_file, extract_outline_from_markdown
```

Add this static method immediately before `_files_from_kwargs`:

```python
    @staticmethod
    def _normalize_markdown_companion(
        file_metadata: dict,
        uploads_dir: Path | None,
        source_filename: str,
    ) -> tuple[bool, str | None]:
        """Return explicit-key presence and a safe Markdown companion basename."""
        if "markdown_file" not in file_metadata:
            return False, None

        raw = file_metadata.get("markdown_file")
        if raw is None:
            return True, None

        reason: str | None = None
        if not isinstance(raw, str) or not raw:
            reason = "value must be a non-empty string or null"
        elif "/" in raw or "\\" in raw or Path(raw).name != raw:
            reason = "value must be a basename"
        elif is_upload_staging_file(raw):
            reason = "staging files are not valid companions"
        elif Path(raw).suffix.lower() != ".md":
            reason = "value must have a .md suffix"
        elif uploads_dir is not None:
            try:
                candidate = uploads_dir / raw
                if candidate.is_symlink() or not candidate.is_file():
                    reason = "file is missing or not a regular file"
            except (OSError, ValueError):
                reason = "file cannot be inspected safely"

        if reason is not None:
            logger.warning(
                "Ignoring Markdown companion metadata for upload %s: %s",
                source_filename,
                reason,
            )
            return True, None
        return True, raw
```

Refactor `_files_from_kwargs` to build `file_info`, preserve the tri-state key, and append once:

```python
            file_info = {
                "filename": filename,
                "size": int(f.get("size") or 0),
                "path": f"/mnt/user-data/uploads/{filename}",
                "extension": Path(filename).suffix,
            }
            has_explicit_companion, markdown_file = self._normalize_markdown_companion(
                f,
                uploads_dir,
                filename,
            )
            if has_explicit_companion:
                file_info["markdown_file"] = markdown_file
            files.append(file_info)
```

- [ ] **Step 6: Select exact or legacy outline extraction**

Replace the outline extraction inside `before_agent` with:

```python
                if "markdown_file" not in file:
                    outline, preview = extract_outline_for_file(phys_path)
                elif file["markdown_file"] is None:
                    outline, preview = [], []
                else:
                    outline, preview = extract_outline_from_markdown(uploads_dir / file["markdown_file"])
                file["outline"] = outline
                file["outline_preview"] = preview
```

Do not add `markdown_file` to `_format_file_entry`; the raw metadata must remain model-invisible.

- [ ] **Step 7: Run focused backend verification and verify GREEN**

From `backend/`, run:

```powershell
$env:PYTHONPATH='.'
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONUTF8='1'
uv run pytest tests/test_uploads_middleware_core_logic.py -v
uv run pytest tests/blocking_io/test_uploads_middleware.py -v
uv run ruff check packages/harness/deerflow/utils/file_outline.py packages/harness/deerflow/agents/middlewares/uploads_middleware.py tests/test_uploads_middleware_core_logic.py
uv run ruff format --check packages/harness/deerflow/utils/file_outline.py packages/harness/deerflow/agents/middlewares/uploads_middleware.py tests/test_uploads_middleware_core_logic.py
```

Expected: both pytest commands pass; Ruff check and format verification exit 0.

- [ ] **Step 8: Commit the backend grounding fix**

```powershell
git add backend/packages/harness/deerflow/utils/file_outline.py backend/packages/harness/deerflow/agents/middlewares/uploads_middleware.py backend/tests/test_uploads_middleware_core_logic.py
git commit -m "fix(agent): ground uploads with explicit markdown provenance"
```

---

### Task 3: Document the Agent provenance invariant

**Files:**
- Modify: `backend/docs/FILE_UPLOAD.md:102-123`
- Modify: `backend/AGENTS.md:1457-1467`

**Interfaces:**
- Consumes: the implemented absent/null/string semantics from Tasks 1 and 2.
- Produces: maintained contributor documentation; no runtime interface.

- [ ] **Step 1: Update the upload feature documentation**

After the paragraph introducing `HumanMessage.additional_kwargs.files` in `backend/docs/FILE_UPLOAD.md`, add this contract in Chinese:

```markdown
Web 上传会把上传响应中的 `markdown_file` 一并写入每个文件的结构化元数据，
使 `UploadsMiddleware` 能按显式的“源文件 → 转换 Markdown”关系提取大纲；
同名源文件发生冲突重命名时，例如 `a.pdf → a_1.md`，不会再按
`a.pdf → a.md` 猜测。新消息中的 `markdown_file: null` 表示本次上传明确
没有转换产物，因此不回退到同名 Markdown。为兼容旧客户端和历史消息，
只有在该字段完全缺失时才沿用 `<stem>.md` 查找。非法、越界或已失效的
companion 元数据会被忽略，原始上传文件仍保留在 Agent 上下文中。
```

- [ ] **Step 2: Update the backend architecture invariant**

Extend the upload bullet in `backend/AGENTS.md` with:

```markdown
- Current-turn web upload metadata preserves the nullable `markdown_file`
  provenance returned by the upload API. `UploadsMiddleware` validates an
  explicit companion basename and reads that exact file; explicit null or
  invalid metadata disables sibling guessing, while an absent key retains the
  legacy `<stem>.md` fallback for old messages. Raw companion metadata is never
  rendered into `<current_uploads>`.
```

- [ ] **Step 3: Verify and commit documentation**

From the repository root, run:

```powershell
git diff --check
rg -n "markdown_file|legacy.*stem|current-turn web upload" backend/docs/FILE_UPLOAD.md backend/AGENTS.md
```

Expected: `git diff --check` exits 0 and the search returns the new contract in both files.

Commit:

```powershell
git add backend/docs/FILE_UPLOAD.md backend/AGENTS.md
git commit -m "docs: describe agent upload provenance contract"
```

---

### Task 4: Run full verification and prepare review evidence

**Files:**
- Verify only; modify production or test files only if a command exposes a real defect, and repeat the affected red-green cycle before committing that correction.

**Interfaces:**
- Consumes: all commits from Tasks 1-3.
- Produces: fresh test, lint, type, formatting, static-analysis, and diff evidence for code review and the PR description.

- [ ] **Step 1: Run the complete frontend verification**

From `frontend/`, run:

```powershell
pnpm test
pnpm check
pnpm format
```

Expected: the complete Rstest suite passes, ESLint and TypeScript exit 0, and Prettier reports all files formatted.

- [ ] **Step 2: Run the complete non-live backend verification**

From `backend/`, run:

```powershell
$env:PYTHONPATH='.'
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONUTF8='1'
uv run pytest -m "not live" tests/ -q
uv run pytest tests/blocking_io/test_uploads_middleware.py -v
uv run ruff check .
uv run ruff format --check .
```

Expected: all non-live tests and the strict blocking-I/O anchor pass; both Ruff commands exit 0. If an environment-dependent pre-existing failure appears, reproduce it on `origin/main` before classifying it as unrelated.

- [ ] **Step 3: Run the repository static blocking-I/O detector**

From the repository root, run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python scripts/detect_blocking_io_static.py --format summary
```

Expected: the command exits 0 and introduces no new finding in `uploads_middleware.py` or `file_outline.py` relative to `origin/main`.

- [ ] **Step 4: Inspect the final branch state**

From the repository root, run:

```powershell
git diff --check origin/main...HEAD
git status --short --branch
git log --oneline --decorate origin/main..HEAD
git diff --stat origin/main...HEAD
```

Expected: diff check exits 0, the worktree is clean, the log contains the design, frontend, backend, and documentation commits, and the stat contains only files named in this plan.

- [ ] **Step 5: Request code review**

Dispatch a reviewer with:

- Description: “Preserve current-turn upload Markdown provenance from the web upload response through Agent middleware; validate explicit companions and retain legacy fallback.”
- Requirements: `docs/superpowers/specs/2026-08-05-upload-markdown-provenance-design.md` and this plan.
- Base SHA: `git rev-parse origin/main`.
- Head SHA: `git rev-parse HEAD`.

Fix every Critical or Important review finding, rerun the affected focused tests, then rerun Steps 1-4 before declaring the branch ready.
