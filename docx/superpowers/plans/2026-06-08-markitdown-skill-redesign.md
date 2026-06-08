# MarkItDown Skill Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure `skills/public/markitdown/` from 7 files / ~1100 LOC to 5 files / ~400 LOC, add MinerU OCR integration, and align with the 8 principles from "Lessons from building Claude Code: How we use skills" (2026-06-03).

**Architecture:** Keep markitdown as the primary text/structure extractor. Add a thin `mineru_client.py` HTTP wrapper for the internal MinerU OCR service. Route JPG/PNG directly to MinerU; route PDF/DOCX/PPTX through markitdown with a fallback to MinerU when markitdown returns < 50 chars (scanned-PDF detection). Two new reference docs (`gotchas.md`, `formats.md`) replace the previous `api_reference.md` / `file_formats.md` / `example_usage.md` / `README.md` clutter.

**Tech Stack:** Python 3.12, `markitdown[pdf,docx,pptx,xlsx,html]` (pre-installed), `requests` (stdlib-style HTTP; the existing markitdown dep chain pulls in HTTP libs but we keep the wrapper `requests`-free for minimal surface — see Task 1 note), internal MinerU OCR service (LAN HTTP), `pytest` (dev-only, for unit tests).

**Spec:** `docx/superpowers/specs/2026-06-08-markitdown-skill-redesign.md`

---

## File Structure

```
skills/public/markitdown/
├── SKILL.md                  # Trigger surface + quickstarts (rewrite, ~150 lines)
├── references/
│   ├── gotchas.md            # PDF/PPTX/DOCX/JPG-PNG/MinerU gotchas (new, ~80 lines)
│   └── formats.md            # All formats quick reference (new, ~20 lines)
├── scripts/
│   ├── batch_convert.py      # Multi-file convert with OCR routing (rewrite, ~100 lines)
│   ├── mineru_client.py      # Thin MinerU HTTP wrapper (new, ~50 lines)
│   └── tests/
│       ├── __init__.py
│       ├── conftest.py       # pytest fixtures: tmp uploads/outputs dirs, monkeypatched env
│       ├── test_mineru_client.py   # HTTP wrapper tests with mocked urllib
│       └── test_batch_convert.py   # Routing tests with mocked MarkItDown + mineru
```

**Created files (5):** `SKILL.md` (rewrite), `references/gotchas.md`, `references/formats.md`, `scripts/mineru_client.py`, `scripts/batch_convert.py` (rewrite), `scripts/tests/{__init__,conftest,test_mineru_client,test_batch_convert}.py`

**Deleted files (6):** `README.md`, `references/api_reference.md`, `references/file_formats.md`, `assets/example_usage.md`, `scripts/convert_with_ai.py`, `scripts/convert_literature.py`

**No changes to:** `extensions_config.json` (markitdown not registered there; auto-discovery picks it up).

---

## Task 1: `mineru_client.py` HTTP wrapper with TDD

**Files:**
- Create: `skills/public/markitdown/scripts/tests/__init__.py`
- Create: `skills/public/markitdown/scripts/tests/conftest.py`
- Create: `skills/public/markitdown/scripts/tests/test_mineru_client.py`
- Create: `skills/public/markitdown/scripts/mineru_client.py`

- [ ] **Step 1: Create empty `__init__.py`**

Create `skills/public/markitdown/scripts/tests/__init__.py` with empty content (single newline). Lets pytest discover the test module.

- [ ] **Step 2: Create `conftest.py` with shared fixtures**

Create `skills/public/markitdown/scripts/tests/conftest.py`:

```python
"""Pytest fixtures for markitdown skill tests."""
import os
import pytest


@pytest.fixture
def mineru_env(monkeypatch):
    """Set MinerU env vars for the duration of one test."""
    monkeypatch.setenv("MINERU_API_URL", "http://mineru.lan:8000")
    monkeypatch.setenv("MINERU_API_KEY", "test-key-abc123")
    return {
        "url": "http://mineru.lan:8000",
        "key": "test-key-abc123",
    }


@pytest.fixture
def sample_text_file(tmp_path):
    """A small text file used to simulate a 'file to convert' in routing tests."""
    p = tmp_path / "doc.txt"
    p.write_text("hello world", encoding="utf-8")
    return p
```

- [ ] **Step 3: Write failing test for happy path**

Create `skills/public/markitdown/scripts/tests/test_mineru_client.py`:

```python
"""Unit tests for scripts/mineru_client.py."""
import io
import urllib.error
from unittest import mock

import pytest

from mineru_client import MinerUError, ocr_to_markdown


def test_ocr_to_markdown_sends_post_with_file_and_returns_markdown(mineru_env, tmp_path):
    fake_file = tmp_path / "scan.png"
    fake_file.write_bytes(b"\x89PNG\r\n\x1a\nfakepng")

    fake_response = io.BytesIO(b'{"markdown": "# Page 1\\n\\nHello OCR world"}')
    fake_response.headers = {"Content-Type": "application/json"}

    with mock.patch("urllib.request.urlopen", return_value=fake_response) as m_open:
        result = ocr_to_markdown(str(fake_file))

    assert result == "# Page 1\n\nHello OCR world"
    # Verify the request was a POST to the right URL with the right headers
    call_args = m_open.call_args
    request_obj = call_args.args[0]
    assert request_obj.full_url == "http://mineru.lan:8000/ocr"
    assert request_obj.get_method() == "POST"
    assert request_obj.get_header("Authorization") == "Bearer test-key-abc123"
    assert request_obj.get_header("Content-type", "").startswith("multipart/form-data")
```

- [ ] **Step 4: Run test, verify it fails**

Run from `skills/public/markitdown/`:
```bash
cd /Users/raidery/bench/harness/raidery/deer-flow/skills/public/markitdown
python -m pytest scripts/tests/test_mineru_client.py::test_ocr_to_markdown_sends_post_with_file_and_returns_markdown -v
```
Expected: `ModuleNotFoundError: No module named 'mineru_client'`.

- [ ] **Step 5: Implement minimal `mineru_client.py`**

Create `skills/public/markitdown/scripts/mineru_client.py`:

```python
"""Thin HTTP wrapper around the internal MinerU OCR service."""
import os
import urllib.request
import urllib.error
import json
import uuid
import mimetypes
from pathlib import Path


class MinerUError(Exception):
    """Raised when the MinerU API returns a non-2xx response or the call fails."""

    def __init__(self, message: str, status: int | None = None, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


def ocr_to_markdown(file_path: str, *, timeout: int = 60) -> str:
    """POST a file to MinerU and return the markdown string from the response.

    Requires env: MINERU_API_URL (required), MINERU_API_KEY (required).
    Raises MinerUError on any failure.
    """
    url = os.environ.get("MINERU_API_URL", "").rstrip("/")
    api_key = os.environ.get("MINERU_API_KEY", "")
    if not url:
        raise MinerUError("MINERU_API_URL is not set")
    if not api_key:
        raise MinerUError("MINERU_API_KEY is not set")

    p = Path(file_path)
    if not p.exists():
        raise MinerUError(f"File not found: {file_path}")

    boundary = f"----markitdown{uuid.uuid4().hex}"
    mime, _ = mimetypes.guess_type(str(p))
    if mime is None:
        mime = "application/octet-stream"

    with open(p, "rb") as f:
        file_bytes = f.read()

    body = _build_multipart(boundary, p.name, mime, file_bytes)

    req = urllib.request.Request(
        f"{url}/ocr",
        data=body,
        method="POST",
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace") if e.fp else ""
        raise MinerUError(f"MinerU HTTP {e.code}", status=e.code, body=body_text) from e
    except urllib.error.URLError as e:
        raise MinerUError(f"MinerU connection error: {e.reason}") from e

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        raise MinerUError(f"MinerU returned non-JSON: {raw[:200]}") from e

    md = payload.get("markdown") or payload.get("text") or payload.get("content")
    if not md:
        raise MinerUError(
            f"MinerU response had no markdown/text/content field: {raw[:200]}"
        )
    return md


def _build_multipart(boundary: str, filename: str, mime: str, data: bytes) -> bytes:
    """Build a multipart/form-data body for a single file field named 'file'."""
    crlf = b"\r\n"
    parts: list[bytes] = []
    parts.append(f"--{boundary}".encode())
    parts.append(
        f'Content-Disposition: form-data; name="file"; filename="{filename}"'.encode()
    )
    parts.append(f"Content-Type: {mime}".encode())
    parts.append(b"")
    parts.append(data)
    parts.append(f"--{boundary}--".encode())
    parts.append(b"")
    return crlf.join(parts)
```

- [ ] **Step 6: Run test, verify it passes**

Run from `skills/public/markitdown/`:
```bash
cd /Users/raidery/bench/harness/raidery/deer-flow/skills/public/markitdown
python -m pytest scripts/tests/test_mineru_client.py::test_ocr_to_markdown_sends_post_with_file_and_returns_markdown -v
```
Expected: `PASSED`.

- [ ] **Step 7: Add test for missing env var**

Append to `skills/public/markitdown/scripts/tests/test_mineru_client.py`:

```python
def test_ocr_to_markdown_raises_when_url_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("MINERU_API_URL", raising=False)
    monkeypatch.setenv("MINERU_API_KEY", "k")
    fake = tmp_path / "x.png"
    fake.write_bytes(b"x")
    with pytest.raises(MinerUError, match="MINERU_API_URL is not set"):
        ocr_to_markdown(str(fake))


def test_ocr_to_markdown_raises_when_key_unset(monkeypatch, tmp_path):
    monkeypatch.setenv("MINERU_API_URL", "http://x")
    monkeypatch.delenv("MINERU_API_KEY", raising=False)
    fake = tmp_path / "x.png"
    fake.write_bytes(b"x")
    with pytest.raises(MinerUError, match="MINERU_API_KEY is not set"):
        ocr_to_markdown(str(fake))
```

- [ ] **Step 8: Add test for non-2xx response**

Append:

```python
def test_ocr_to_markdown_raises_mineru_error_on_500(mineru_env, tmp_path):
    fake = tmp_path / "x.png"
    fake.write_bytes(b"x")
    err = urllib.error.HTTPError(
        "http://mineru.lan:8000/ocr", 500, "Internal Server Error", {}, io.BytesIO(b"oops")
    )
    with mock.patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(MinerUError) as exc_info:
            ocr_to_markdown(str(fake))
    assert exc_info.value.status == 500
    assert exc_info.value.body == "oops"
```

- [ ] **Step 9: Run all mineru_client tests**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow/skills/public/markitdown
python -m pytest scripts/tests/test_mineru_client.py -v
```
Expected: 4 passed.

- [ ] **Step 10: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
git add skills/public/markitdown/scripts/mineru_client.py \
        skills/public/markitdown/scripts/tests/
git commit -m "feat(skill:markitdown): add mineru_client.py HTTP wrapper

TDD: 4 pytest cases (happy path, env validation, HTTP error).
Used urllib stdlib (no new dep). 60s default timeout.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: `batch_convert.py` rewrite with routing + CLI

**Files:**
- Create: `skills/public/markitdown/scripts/tests/test_batch_convert.py`
- Modify: `skills/public/markitdown/scripts/batch_convert.py` (full rewrite)

- [ ] **Step 1: Write failing routing test (image → MinerU)**

Create `skills/public/markitdown/scripts/tests/test_batch_convert.py`:

```python
"""Unit tests for scripts/batch_convert.py routing logic."""
import sys
from pathlib import Path
from unittest import mock

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import batch_convert  # noqa: E402


def test_convert_file_routes_image_to_mineru(mineru_env, tmp_path):
    img = tmp_path / "photo.jpg"
    img.write_bytes(b"fake-jpg-bytes")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    with mock.patch.object(batch_convert.mineru_client, "ocr_to_markdown", return_value="# OCR result") as ocr:
        with mock.patch.object(batch_convert, "MarkItDown") as md_cls:
            ok, _, msg = batch_convert.convert_file(img, out_dir, verbose=False)

    assert ok is True
    assert "Converted" in msg
    ocr.assert_called_once_with(str(img))
    md_cls.assert_not_called()

    out = out_dir / "photo.md"
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "# photo" in content
    assert "**Source**: photo.jpg" in content
    assert "# OCR result" in content
```

- [ ] **Step 2: Run, verify it fails**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow/skills/public/markitdown
python -m pytest scripts/tests/test_batch_convert.py::test_convert_file_routes_image_to_mineru -v
```
Expected: `ModuleNotFoundError: No module named 'batch_convert'`.

- [ ] **Step 3: Write failing routing test (text PDF → markitdown, no fallback)**

Append to `scripts/tests/test_batch_convert.py`:

```python
def test_convert_file_routes_text_pdf_to_markitdown(tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    fake_result = mock.Mock()
    fake_result.text_content = "Long enough PDF body " * 20  # > 50 chars

    fake_md_instance = mock.Mock()
    fake_md_instance.convert.return_value = fake_result

    with mock.patch.object(batch_convert, "MarkItDown", return_value=fake_md_instance) as md_cls:
        with mock.patch.object(batch_convert.mineru_client, "ocr_to_markdown") as ocr:
            ok, _, _ = batch_convert.convert_file(pdf, out_dir, verbose=False)

    assert ok is True
    md_cls.assert_called_once_with()
    fake_md_instance.convert.assert_called_once_with(str(pdf))
    ocr.assert_not_called()


def test_convert_file_falls_back_to_mineru_for_scanned_pdf(tmp_path):
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    fake_result = mock.Mock()
    fake_result.text_content = "x"  # < 50 chars -> scanned

    fake_md_instance = mock.Mock()
    fake_md_instance.convert.return_value = fake_result

    with mock.patch.object(batch_convert, "MarkItDown", return_value=fake_md_instance):
        with mock.patch.object(batch_convert.mineru_client, "ocr_to_markdown", return_value="# OCR scan") as ocr:
            ok, _, _ = batch_convert.convert_file(pdf, out_dir, verbose=False)

    assert ok is True
    ocr.assert_called_once_with(str(pdf))


def test_convert_file_skips_missing_path(tmp_path, capsys):
    missing = tmp_path / "ghost.pdf"
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    ok, _, msg = batch_convert.convert_file(missing, out_dir, verbose=False)

    assert ok is False
    assert "Skipping" in msg
    captured = capsys.readouterr()
    assert "ghost.pdf" in captured.out


def test_convert_file_continues_on_markitdown_exception(tmp_path):
    pdf = tmp_path / "broken.pdf"
    pdf.write_bytes(b"x")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    fake_md_instance = mock.Mock()
    fake_md_instance.convert.side_effect = RuntimeError("markitdown blew up")

    with mock.patch.object(batch_convert, "MarkItDown", return_value=fake_md_instance):
        ok, _, msg = batch_convert.convert_file(pdf, out_dir, verbose=False)

    assert ok is False
    assert "Error" in msg
    placeholder = out_dir / "broken.md"
    assert placeholder.exists()
    assert "markitdown blew up" in placeholder.read_text(encoding="utf-8")
```

- [ ] **Step 4: Implement `batch_convert.py`**

Create `skills/public/markitdown/scripts/batch_convert.py` (full rewrite):

```python
#!/usr/bin/env python3
"""Convert multiple files to Markdown via markitdown + MinerU OCR fallback."""
import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from markitdown import MarkItDown

import mineru_client


# Module-level constant: short markitdown output => scanned PDF, route to MinerU.
OCR_FALLBACK_THRESHOLD = 50

# File extensions that always go to MinerU (pure image formats).
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def convert_file(file_path: Path, output_dir: Path, verbose: bool = False) -> tuple[bool, str, str]:
    """Convert one file. Returns (success, path_str, message).

    Routing:
      - image suffix (.jpg/.jpeg/.png) -> mineru_client.ocr_to_markdown
      - else: markitdown.convert(); if text < OCR_FALLBACK_THRESHOLD, fall back to mineru
    """
    try:
        suffix = file_path.suffix.lower()
        if suffix in IMAGE_SUFFIXES:
            if verbose:
                print(f"OCR (image): {file_path}")
            text = mineru_client.ocr_to_markdown(str(file_path))
        else:
            md = MarkItDown()
            result = md.convert(str(file_path))
            text = result.text_content or ""
            if len(text.strip()) < OCR_FALLBACK_THRESHOLD:
                if verbose:
                    print(
                        f"markitdown returned <{OCR_FALLBACK_THRESHOLD} chars, "
                        f"falling back to MinerU: {file_path}"
                    )
                text = mineru_client.ocr_to_markdown(str(file_path))

        output_file = output_dir / f"{file_path.stem}.md"
        content = f"# {file_path.stem}\n\n**Source**: {file_path.name}\n\n---\n\n{text}"
        output_file.write_text(content, encoding="utf-8")
        return True, str(file_path), f"✓ Converted to {output_file.name}"

    except FileNotFoundError:
        print(f"⚠ Skipping: {file_path} (not found)")
        return False, str(file_path), "Skipping: not found"
    except mineru_client.MinerUError as e:
        placeholder = output_dir / f"{file_path.stem}.md"
        placeholder.write_text(
            f"# {file_path.stem}\n\n**Source**: {file_path.name}\n\n"
            f"---\n\n[ERROR] MinerU failed (status={e.status}): {e}\n",
            encoding="utf-8",
        )
        return False, str(file_path), f"Error: MinerU {e.status or e}"
    except Exception as e:
        placeholder = output_dir / f"{file_path.stem}.md"
        placeholder.write_text(
            f"# {file_path.stem}\n\n**Source**: {file_path.name}\n\n"
            f"---\n\n[ERROR] {type(e).__name__}: {e}\n",
            encoding="utf-8",
        )
        return False, str(file_path), f"Error: {e}"


def batch_convert(
    files: list[Path],
    output_dir: Path,
    workers: int = 4,
    verbose: bool = False,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    if not files:
        print("No files to convert.")
        return {"total": 0, "success": 0, "failed": 0, "details": []}

    print(f"Converting {len(files)} file(s) with {workers} worker(s)")
    results = {"total": len(files), "success": 0, "failed": 0, "details": []}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(convert_file, fp, output_dir, verbose): fp for fp in files
        }
        for future in as_completed(futures):
            ok, path, msg = future.result()
            if ok:
                results["success"] += 1
            else:
                results["failed"] += 1
            results["details"].append({"file": path, "success": ok, "message": msg})
            print(msg)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert files to Markdown via markitdown + MinerU OCR fallback"
    )
    parser.add_argument(
        "--files", nargs="+", required=True,
        help="Explicit file paths to convert (e.g., /mnt/user-data/uploads/a.pdf)",
    )
    parser.add_argument(
        "--output-dir", required=True, type=Path,
        help="Output directory (e.g., /mnt/user-data/outputs/)",
    )
    parser.add_argument("--workers", "-w", type=int, default=4)
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    files = [Path(p) for p in args.files]
    results = batch_convert(files, args.output_dir, workers=args.workers, verbose=args.verbose)

    print("\n" + "=" * 50)
    print("CONVERSION SUMMARY")
    print("=" * 50)
    print(f"Total files:     {results['total']}")
    print(f"Successful:      {results['success']}")
    print(f"Failed:          {results['failed']}")
    if results["failed"] > 0:
        print("\nFailed conversions:")
        for d in results["details"]:
            if not d["success"]:
                print(f"  - {d['file']}: {d['message']}")
    return 0 if results["success"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run all batch_convert tests**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow/skills/public/markitdown
python -m pytest scripts/tests/test_batch_convert.py -v
```
Expected: 4 passed.

- [ ] **Step 6: Run full test suite**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow/skills/public/markitdown
python -m pytest scripts/tests/ -v
```
Expected: 8 passed (4 from mineru_client + 4 from batch_convert).

- [ ] **Step 7: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
git add skills/public/markitdown/scripts/batch_convert.py \
        skills/public/markitdown/scripts/tests/test_batch_convert.py
git commit -m "feat(skill:markitdown): rewrite batch_convert with OCR routing

New CLI: --files <list> --output-dir <dir> (replaces --input-dir/--extensions).
Routing: .jpg/.png -> MinerU; .pdf/.docx/.pptx -> markitdown; markitdown
output <50 chars -> MinerU fallback (scanned-PDF detection).
Error semantics: per-file failure is logged, placeholder .md is written,
and the batch continues. Exit 0 if >=1 success, 1 if all failed.

4 new pytest cases for routing. Coexists with mineru_client tests.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: Create `references/formats.md`

**Files:**
- Create: `skills/public/markitdown/references/formats.md`

- [ ] **Step 1: Create the file**

Create `skills/public/markitdown/references/formats.md` with the following content:

```markdown
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
```

- [ ] **Step 2: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
git add skills/public/markitdown/references/formats.md
git commit -m "docs(skill:markitdown): add formats.md quick reference

Replaces references/file_formats.md (deleted in Task 6).
Single screen, table-only, points to gotchas.md for details.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: Create `references/gotchas.md`

**Files:**
- Create: `skills/public/markitdown/references/gotchas.md`

- [ ] **Step 1: Create the file**

Create `skills/public/markitdown/references/gotchas.md` with the following content:

```markdown
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
```

- [ ] **Step 2: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
git add skills/public/markitdown/references/gotchas.md
git commit -m "docs(skill:markitdown): add gotchas.md

Highest-signal content. 5 sections (PDF/PPTX/DOCX/JPG-PNG/MinerU) +
explicit out-of-scope close. Replaces info from api_reference.md /
file_formats.md / example_usage.md (all deleted in Task 6).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: Rewrite `SKILL.md`

**Files:**
- Modify: `skills/public/markitdown/SKILL.md` (full rewrite)

- [ ] **Step 1: Write new `SKILL.md`**

Replace the contents of `skills/public/markitdown/SKILL.md` with:

```markdown
---
name: markitdown
license: MIT
source: https://github.com/microsoft/markitdown
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
dst.write_text(result.text_content, encoding="utf-8")
```

## Quickstart — 图片 / 扫描件

```python
import sys
sys.path.insert(0, "/mnt/skills/public/markitdown/scripts")
import mineru_client

text = mineru_client.ocr_to_markdown("/mnt/user-data/uploads/photo.png")
with open("/mnt/user-data/outputs/photo.md", "w", encoding="utf-8") as f:
    f.write(text)
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
```

- [ ] **Step 2: Validate frontmatter parses**

Run:
```bash
python3 -c "
import yaml, sys
with open('/Users/raidery/bench/harness/raidery/deer-flow/skills/public/markitdown/SKILL.md') as f:
    content = f.read()
parts = content.split('---', 2)
fm = yaml.safe_load(parts[1])
print('name:', fm['name'])
print('description starts:', fm['description'].split(chr(10))[1].strip())
print('description length (chars):', len(fm['description']))
print('OK')
"
```
Expected: `name: markitdown`, description line printed, `OK`.

- [ ] **Step 3: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
git add skills/public/markitdown/SKILL.md
git commit -m "docs(skill:markitdown): rewrite SKILL.md with model-targeted triggers

Replaces 450-line README-style doc with 150-line trigger-focused doc.
Sections: 触发规则 / 路径约定 / 决策表 / 2 quickstarts / batch 调用 /
强制单步模式. Description rewritten per blog: model-targeted, pushy,
explicit Do-NOT-use-for clause.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: Delete obsolete files

**Files:**
- Delete: `skills/public/markitdown/README.md`
- Delete: `skills/public/markitdown/references/api_reference.md`
- Delete: `skills/public/markitdown/references/file_formats.md`
- Delete: `skills/public/markitdown/assets/example_usage.md`
- Delete: `skills/public/markitdown/scripts/convert_with_ai.py`
- Delete: `skills/public/markitdown/scripts/convert_literature.py`
- Delete: empty `skills/public/markitdown/assets/` directory (now empty)
- Delete: empty `skills/public/markitdown/references/` if it became empty (it will not — gotchas.md and formats.md exist)

- [ ] **Step 1: Verify no other skill references these files**

Run from repo root:
```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
grep -rln "convert_with_ai\|convert_literature\|example_usage\|api_reference\|file_formats" --include="*.py" --include="*.md" --include="*.yaml" --include="*.json" -- . 2>/dev/null | grep -v "/.venv/" | grep -v "/node_modules/" | grep -v "/.deer-flow/"
```
Expected: no output (or only references inside the markitdown directory itself, which we are rewriting).

- [ ] **Step 2: Delete the 6 files + 1 empty assets dir**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
rm skills/public/markitdown/README.md
rm skills/public/markitdown/references/api_reference.md
rm skills/public/markitdown/references/file_formats.md
rm skills/public/markitdown/assets/example_usage.md
rmdir skills/public/markitdown/assets/ 2>/dev/null || echo "assets/ not empty, leaving it"
rm skills/public/markitdown/scripts/convert_with_ai.py
rm skills/public/markitdown/scripts/convert_literature.py
```

- [ ] **Step 3: Verify final layout**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
find skills/public/markitdown -type f | sort
```
Expected output (5 files + 4 test files = 9 files):
```
skills/public/markitdown/SKILL.md
skills/public/markitdown/references/formats.md
skills/public/markitdown/references/gotchas.md
skills/public/markitdown/scripts/batch_convert.py
skills/public/markitdown/scripts/mineru_client.py
skills/public/markitdown/scripts/tests/__init__.py
skills/public/markitdown/scripts/tests/conftest.py
skills/public/markitdown/scripts/tests/test_batch_convert.py
skills/public/markitdown/scripts/tests/test_mineru_client.py
```

- [ ] **Step 4: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
git add -A skills/public/markitdown/
git status  # verify only deletions are staged
git commit -m "chore(skill:markitdown): remove obsolete docs/scripts

Delete 6 files totaling ~700 LOC of content that lived in
SKILL.md (duplicated), api_reference.md (vendor API surface),
file_formats.md (per-format blurb), example_usage.md (info merged
into gotchas.md), convert_with_ai.py (OpenRouter, out of scope),
convert_literature.py (specialized workflow, replaced by gotchas).

No external consumers (verified by grep).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 7: Smoke test in container

**Files:** none (no code changes)

This task runs in the DeerFlow container, not on the host. It validates the
end-to-end flow against real markitdown, real MinerU (or a stub), and real
sandbox paths.

- [ ] **Step 1: Bring up the gateway container**

From the repo root:
```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
make dev  # or whichever target brings up the gateway + langgraph containers
```
Wait for "ready" log line. (~30s)

- [ ] **Step 2: Verify env vars are set in the container**

```bash
docker exec -it <gateway-container> bash -c 'echo "URL=$MINERU_API_URL"; echo "KEY=${MINERU_API_KEY:0:8}..."'
```
Expected: `URL=http://mineru.lan:...` (non-empty), `KEY=` followed by at least 8 chars.
If either is empty, update `.env` (host) and restart the container. **Do not skip this step** — the smoke test cannot proceed without it.

- [ ] **Step 3: Verify MinerU reachability**

```bash
docker exec -it <gateway-container> curl -fsS "${MINERU_API_URL}/health"
```
Expected: HTTP 200 (or whatever success looks like for your MinerU deployment). If 404, try `/` or the actual health path; record the working path in `mineru_client.py` comment.

- [ ] **Step 4: Stage fixture files in uploads dir**

The fixtures can be tiny, just enough to exercise the routing:
- One text-PDF (any non-empty PDF; e.g. a one-page export from any tool)
- One scanned-PDF (print-to-PDF of a JPG, or a real scan if you have one)
- One DOCX (one paragraph)
- One JPG (any small image)
- One PNG (any small image)

```bash
docker exec -it <gateway-container> mkdir -p /mnt/user-data/uploads /mnt/user-data/outputs
# Copy fixtures in (host path -> container path; adjust as needed)
docker cp fixtures/text.pdf    <gateway-container>:/mnt/user-data/uploads/
docker cp fixtures/scanned.pdf <gateway-container>:/mnt/user-data/uploads/
docker cp fixtures/letter.docx <gateway-container>:/mnt/user-data/uploads/
docker cp fixtures/photo.jpg   <gateway-container>:/mnt/user-data/uploads/
docker cp fixtures/diagram.png <gateway-container>:/mnt/user-data/uploads/
```

- [ ] **Step 5: Run pytest inside the container**

```bash
docker exec -it <gateway-container> bash -c '
  cd /mnt/skills/public/markitdown &&
  python -m pytest scripts/tests/ -v
'
```
Expected: 8 passed. If failures, debug the test environment (env vars, path import).

- [ ] **Step 6: Run batch_convert end-to-end with mixed inputs**

```bash
docker exec -it <gateway-container> python /mnt/skills/public/markitdown/scripts/batch_convert.py \
  --files /mnt/user-data/uploads/text.pdf \
          /mnt/user-data/uploads/scanned.pdf \
          /mnt/user-data/uploads/letter.docx \
          /mnt/user-data/uploads/photo.jpg \
          /mnt/user-data/uploads/diagram.png \
          /mnt/user-data/uploads/ghost.pdf \
  --output-dir /mnt/user-data/outputs/ \
  --verbose
```
Expected output (abridged):
```
Converting 6 file(s) with 4 worker(s)
OCR (image): /mnt/user-data/uploads/photo.jpg
markitdown returned <50 chars, falling back to MinerU: /mnt/user-data/uploads/scanned.pdf
✓ Converted to text.md
✓ Converted to scanned.md
✓ Converted to letter.md
✓ Converted to photo.md
✓ Converted to diagram.md
⚠ Skipping: /mnt/user-data/uploads/ghost.pdf (not found)
[ERROR] ... (any per-file errors)
CONVERSION SUMMARY
Total files:     6
Successful:      5
Failed:          1
```

- [ ] **Step 7: Verify output files exist and look right**

```bash
docker exec -it <gateway-container> bash -c '
  ls -la /mnt/user-data/outputs/ &&
  echo "---text.md head---" && head -5 /mnt/user-data/outputs/text.md &&
  echo "---scanned.md head---" && head -5 /mnt/user-data/outputs/scanned.md &&
  echo "---ghost.md (should NOT exist)---" && ls /mnt/user-data/outputs/ghost.md 2>&1
'
```
Expected:
- 5 .md files exist (text.md, scanned.md, letter.md, photo.md, diagram.md)
- `ghost.md` does NOT exist (skipped path)
- text.md has `# text` header, `**Source**: text.pdf` line, then markitdown-extracted body
- scanned.md has `# scanned` header and OCR text from MinerU
- photo.md has `# photo` header and OCR text from MinerU

- [ ] **Step 8: Run with all-missing to verify exit code 1**

```bash
docker exec -it <gateway-container> python /mnt/skills/public/markitdown/scripts/batch_convert.py \
  --files /mnt/user-data/uploads/ghost1.pdf /mnt/user-data/uploads/ghost2.pdf \
  --output-dir /tmp/smoke-out 2>&1
echo "exit=$?"
```
Expected: exit code `1`, summary shows `Successful: 0`, `Failed: 2`.

- [ ] **Step 9: Verify skill auto-discovery**

In a fresh DeerFlow conversation, ask: **"把 `/mnt/user-data/uploads/text.pdf` 转成 markdown"**.
Expected: the lead agent loads this skill (description trigger fires) and produces the converted output via either the Python Quickstart or `batch_convert.py`. If it does not, the description is not pushy enough — re-iterate on §5 wording.

- [ ] **Step 10: Final commit (only if Step 7 / 9 surfaced a fix)**

If the smoke test surfaced a code or doc bug, fix it inline and commit:
```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
git add skills/public/markitdown/
git commit -m "fix(skill:markitdown): address smoke-test findings

<describe what was fixed and why>

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```
If no fix needed, this step is a no-op.

---

## Self-Review Notes

- **Spec coverage**: §3 (env) → Task 1 reads env vars; §4 (file structure) → Tasks 1, 2, 3, 4, 5 create them; §5 (description) → Task 5; §6 (SKILL.md body) → Task 5; §7 (batch_convert) → Task 2; §7.1 (mineru_client) → Task 1; §8 (gotchas) → Task 4; §9 (formats) → Task 3; §10 (migration steps) → all tasks; §11 (risks: tesseract out, MinerU fail-fast, threshold tuning) → all surfaced in gotchas.md and Task 7 smoke test.
- **No placeholders**: scanned — no TBD/TODO in code; TBDs only in the spec's §7.1 wire format note, which is a real TBD to confirm during Task 1.
- **Type consistency**: `convert_file(file_path, output_dir, verbose) -> tuple[bool, str, str]` is used identically in §7 of the spec, the implementation in Task 2, and all 4 test cases. `mineru_client.ocr_to_markdown(path, *, timeout=60) -> str` consistent across spec, impl, and 4 tests. `MinerUError(status, body)` consistent.
- **File count check**: 5 production files (SKILL.md, gotchas.md, formats.md, batch_convert.py, mineru_client.py) + 4 test files = 9 total. Spec §2 says "5 files / ~400 LOC"; test files are dev-only and not counted. ✓
