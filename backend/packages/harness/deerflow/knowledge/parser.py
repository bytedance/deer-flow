"""MinerU official API (v4) client for document parsing.

Provider dimension (spec 2026-09-14 §4.4): ``parse_document`` resolves
``rag.parse_provider`` through the curated allowlist — ``mineru-cloud`` (this module's
own client, below) or ``mineru-local`` (a self-hosted MinerU HTTP service, see
``parse_local.py``). Both return the same ``ParsedDocument`` and share
``normalize_mineru_markdown``; only the transport differs.

Local-file flow (精准解析 API):

1. ``POST /api/v4/file-urls/batch`` — apply for an OSS upload URL.
2. ``PUT <file_url>`` — bare-binary upload (no Content-Type, per MinerU docs);
   the service auto-submits the parse task once the file lands.
3. Poll ``GET /api/v4/extract-results/batch/{batch_id}`` until the file's
   state is ``done`` (grab ``full_zip_url``) or ``failed``.
4. Download the result zip and unpack ``full.md`` + ``images/*``.

Markdown/text inputs short-circuit: ``.md``/``.markdown``/``.txt`` files are
already parse output (or plain text), ``.csv``/``.tsv`` are delimited text, and
``.xlsx``/``.xls`` are workbooks — all are read locally without any MinerU call.
``.csv``/``.tsv`` normalize into a GFM pipe table and ``.xlsx``/``.xls`` into one
GFM table per sheet via python-calamine (gated by ``rag.table.enabled``,
spec 2026-09-09 §5); ``.xlsx`` additionally yields its embedded images through
the same local read (spec 2026-10-03 D2=乙: ``r:embed``-referenced media under
``xl/media/`` merges into its ``xdr:from`` anchor cell, out-of-range or
anchorless images fall back to the sheet tail, while ``.xls`` keeps no image
support, D1=甲). MinerU's own output has its HTML ``<table>`` blocks
normalized to GFM as well, because v4 with the default ``model_version="vlm"``
emits HTML rather than GFM (Task 0 实测门). The API token always comes from the
``MINERU_API_TOKEN`` env var — never from the caller.
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import os
import posixpath
import re
import time
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import httpx

from deerflow.config.app_config import get_app_config
from deerflow.config.rag_config_file import SECRET_ENV_VARS, configured_rag_secret
from deerflow.knowledge.providers import resolve_provider
from deerflow.utils.file_io import run_file_io

logger = logging.getLogger(__name__)

MINERU_BASE_URL = "https://mineru.net"
_TOKEN_ENV_VAR = SECRET_ENV_VARS["mineru_api_token"]
#: MinerU business codes (response body ``code``) for token problems.
_AUTH_CODES = {"A0202", "A0211"}
#: Poll states that mean "keep waiting".
_PENDING_STATES = frozenset({"waiting-file", "pending", "running", "converting"})

#: Upload allowlist (spec §6, frozen): local-read text formats + MinerU-parsed
#: document/image formats. Lowercase, dot-prefixed.
SUPPORTED_UPLOAD_SUFFIXES: frozenset[str] = frozenset(
    {
        ".md",
        ".markdown",
        ".txt",
        ".csv",
        ".pdf",
        ".doc",
        ".docx",
        ".ppt",
        ".pptx",
        ".png",
        ".jpg",
        ".jpeg",
    }
)

#: Suffixes read from local disk — they never hit MinerU. ``.csv``/``.tsv`` are
#: further routed to ``_parse_delimited`` (table-aware) ahead of the raw-text
#: branch; see ``_DELIMITED_SUFFIXES`` (spec 2026-09-09 §5).
_LOCAL_READ_SUFFIXES: frozenset[str] = frozenset({".md", ".markdown", ".txt", ".csv", ".tsv"})

#: Delimited-text suffixes parsed into a GFM pipe table instead of a raw text
#: dump (spec 2026-09-09 §5). ``.csv`` is an ungated member of the text set;
#: ``.tsv`` rides the ``rag.table`` gate for *upload* but is always parsed here.
_DELIMITED_SUFFIXES: frozenset[str] = frozenset({".csv", ".tsv"})

#: Excel workbook suffixes parsed by ``_parse_excel`` (python-calamine) into one
#: GFM table per sheet — gated behind ``rag.table.enabled`` and never sent to
#: MinerU (spec 2026-09-09 §5). ``.xlsx`` additionally yields its embedded images
#: via ``_extract_xlsx_images`` (spec 2026-10-03 D2=乙); ``.xls`` keeps no image
#: support (D1=甲). ``.tsv`` is deliberately absent: it is delimited text, not a
#: workbook (see ``_DELIMITED_SUFFIXES``).
_EXCEL_SUFFIXES: frozenset[str] = frozenset({".xlsx", ".xls"})

#: Video upload allowlist (spec 2026-09-08 §2, frozen): an independent
#: frozenset so the text set above stays byte-identical. Surfaced in the
#: upload gate and /supported-formats ONLY when ``rag.video.enabled`` is on
#: (see ``supported_upload_suffixes``).
VIDEO_UPLOAD_SUFFIXES: frozenset[str] = frozenset({".mp4", ".mov", ".mkv", ".webm"})

#: Spreadsheet upload allowlist (spec 2026-09-09 §4, frozen): an independent
#: frozenset so the text set above stays byte-identical. Surfaced in the upload
#: gate and /supported-formats ONLY when ``rag.table.enabled`` is on (see
#: ``supported_upload_suffixes``). ``.csv`` is deliberately absent: it already
#: lives in the text set, so its membership never changes — only its *handling*
#: does (raw text dump → table-aware parse), which is a correctness fix and is
#: therefore not gated.
TABLE_UPLOAD_SUFFIXES: frozenset[str] = frozenset({".xlsx", ".xls", ".tsv"})

_MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
}

#: OOXML namespaces the workbook-image extraction reads (spec 2026-10-03 §2.4):
#: the spreadsheet main namespace, the package relationships namespace, the
#: officeDocument relationship *attribute* namespace, and the drawing namespaces
#: (worksheetDrawing for the anchors, drawingml main for ``a:blip``).
_XLSX_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_XLSX_RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_XLSX_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_XLSX_XDR_NS = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
_XLSX_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"


def video_ingest_enabled() -> bool:
    """``rag.video.enabled`` master gate (spec 2026-09-08 §7). Config load
    failures degrade to off — the gate never widens the allowlist on error."""
    try:
        return bool(get_app_config().rag.video.enabled)
    except Exception:
        return False


def table_ingest_enabled() -> bool:
    """``rag.table.enabled`` master gate (spec 2026-09-09 §4). Config load
    failures degrade to off — the gate never widens the allowlist on error."""
    try:
        return bool(get_app_config().rag.table.enabled)
    except Exception:
        return False


def supported_upload_suffixes() -> frozenset[str]:
    """Config-gated upload allowlist: the frozen text set, unioned with the video
    set when ``rag.video.enabled`` is on and the spreadsheet set when
    ``rag.table.enabled`` is on. The two gates are independent legs. Single source
    for both the /supported-formats endpoint and the upload gate so they cannot
    drift (spec 2026-09-08 §2, spec 2026-09-09 §4)."""
    suffixes = SUPPORTED_UPLOAD_SUFFIXES
    if video_ingest_enabled():
        suffixes = suffixes | VIDEO_UPLOAD_SUFFIXES
    if table_ingest_enabled():
        suffixes = suffixes | TABLE_UPLOAD_SUFFIXES
    return suffixes


def video_upload_limit_bytes() -> int | None:
    """``rag.video.max_size_mb`` in bytes; None when the video gate is off
    (video suffixes are rejected at the door anyway)."""
    if not video_ingest_enabled():
        return None
    try:
        return int(get_app_config().rag.video.max_size_mb) * 1024 * 1024
    except Exception:
        return None


def table_upload_limit_bytes() -> int | None:
    """``rag.table.max_size_mb`` in bytes; None when the table gate is off
    (spreadsheet suffixes are rejected at the door anyway, and ``.csv`` — an
    ungated member of the text set — keeps its pre-table-ingest behaviour of no
    size ceiling, spec 2026-09-09 §4)."""
    if not table_ingest_enabled():
        return None
    try:
        return int(get_app_config().rag.table.max_size_mb) * 1024 * 1024
    except Exception:
        return None


def is_supported_suffix(suffix: str) -> bool:
    """Case-insensitive upload-allowlist membership (dot-prefixed suffix);
    the allowlist is config-gated (see ``supported_upload_suffixes``)."""
    return suffix.lower() in supported_upload_suffixes()


def is_local_suffix(suffix: str) -> bool:
    """Case-insensitive check for local-read (no MinerU) suffixes."""
    return suffix.lower() in _LOCAL_READ_SUFFIXES


def _read_local_text(path: Path) -> str:
    """Read a local text file: UTF-8 strict, then GBK fallback (legacy
    Windows encodings), else an explicit ``ValueError``. Newlines are
    normalized to ``\n`` (mirrors ``Path.read_text`` universal-newlines)."""
    raw = path.read_bytes()
    text: str | None = None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    if text is None:
        try:
            text = raw.decode("gbk")
        except UnicodeDecodeError as exc:
            raise ValueError(f"cannot decode {path.name}: not valid UTF-8 or GBK") from exc
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _gfm_cell(text: str) -> str:
    """One GFM table cell: collapse whitespace (a cell must stay single-line) and
    escape a literal ``|`` so it cannot break the column structure."""
    return re.sub(r"\s+", " ", text).strip().replace("|", "\\|")


def _gfm_row(cells: list[str]) -> str:
    return "| " + " | ".join(_gfm_cell(c) for c in cells) + " |"


def _gfm_separator(width: int) -> str:
    return "| " + " | ".join(["---"] * width) + " |"


def _fit_width(row: list[str], width: int) -> list[str]:
    """Pad a short row with empty cells / truncate a long row to *width*."""
    cells = list(row)
    if len(cells) < width:
        cells.extend([""] * (width - len(cells)))
    return cells[:width]


def _sniff_delimiter(suffix: str, text: str) -> str:
    """``.tsv`` → fixed tab; ``.csv`` → ``csv.Sniffer`` over comma/semicolon with a
    comma fallback (spec 2026-09-09 §5)."""
    if suffix == ".tsv":
        return "\t"
    try:
        delim = csv.Sniffer().sniff(text[:8192], delimiters=",;").delimiter
    except csv.Error:
        delim = ","
    return delim if delim in (",", ";") else ","


def _parse_delimited(path: Path) -> str:
    """Parse a ``.csv``/``.tsv`` file into a GFM pipe table (spec 2026-09-09 §5).

    Encoding reuses ``_read_local_text`` (UTF-8 strict → GBK fallback) plus BOM
    stripping. The first row is the header; ragged rows are padded/truncated to
    the header width and blank rows are skipped, so the output is always a valid
    single-line-per-row GFM table. Empty input yields ``""`` (the worker then
    raises EmptyParseResultError, exactly as for an empty text file).
    """
    text = _read_local_text(path)
    if text.startswith("\ufeff"):
        text = text[1:]  # strip UTF-8 BOM
    delimiter = _sniff_delimiter(path.suffix.lower(), text)
    rows = [row for row in csv.reader(io.StringIO(text), delimiter=delimiter) if any(cell.strip() for cell in row)]
    if not rows:
        return ""
    width = len(rows[0])
    lines = [_gfm_row(rows[0]), _gfm_separator(width)]
    lines.extend(_gfm_row(_fit_width(row, width)) for row in rows[1:])
    return "\n".join(lines)


def _cell_to_text(value: object) -> str:
    """Spreadsheet cell → text: ``None`` → empty; an integral float → its int form
    (calamine reads every numeric cell as float, so ``120`` would otherwise render
    as ``120.0``); anything else keeps its natural Python form (``_gfm_cell``
    collapses whitespace and escapes ``|`` downstream)."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _workbook_rows_to_markdown(
    sheets: Iterable[tuple[str, list[list[object]]]],
    *,
    trailing_images_by_sheet: dict[str, list[ParsedImage]] | None = None,
) -> str:
    """Assemble one ``## {sheet_name}`` + GFM pipe table per non-empty sheet.

    Pure transform over ``(sheet_name, rows)`` pairs (rows are calamine's
    ``to_python()`` output): the first row is the header, ragged rows are
    padded/truncated to the header width, blank rows and empty sheets are
    skipped, and sheets are concatenated in order (spec 2026-09-09 §5). The
    ``##`` heading lets the chunker file every row card under the sheet name.

    ``trailing_images_by_sheet`` (spec 2026-10-03 D2=乙) renders the images a
    sheet could not place into a cell after its table, one ``![图片](ref)`` line
    per image separated by blank lines — a sheet with images but no rows still
    emits its ``##`` section.
    """
    trailing = trailing_images_by_sheet or {}
    blocks: list[str] = []
    for sheet_name, raw_rows in sheets:
        rows = [[_cell_to_text(cell) for cell in row] for row in raw_rows]
        rows = [row for row in rows if any(cell.strip() for cell in row)]
        images = trailing.get(sheet_name, [])
        if not rows and not images:
            continue  # empty sheet
        block = f"## {sheet_name}"
        if rows:
            width = len(rows[0])
            table = [_gfm_row(rows[0]), _gfm_separator(width)]
            table.extend(_gfm_row(_fit_width(row, width)) for row in rows[1:])
            block += "\n\n" + "\n".join(table)
        if images:
            block += "\n\n" + "\n\n".join(f"![图片]({image.ref})" for image in images)
        blocks.append(block)
    return "\n\n".join(blocks)


def _merge_anchor_links(
    rows: list[list[object]],
    start: tuple[int, int] | None,
    images: list[tuple[ParsedImage, int | None, int | None]],
) -> tuple[list[list[object]], list[ParsedImage]]:
    """Place each image's link into its anchor cell, or fall back to the sheet tail.

    ``start`` is calamine's ``sheet.start`` — the 0-based absolute ``(row, col)``
    origin of the used range — so an anchor hits when ``abs − start`` lands inside
    the matrix (row < row count, column < header width). Anything unplaceable —
    out-of-range rows/columns, an ``absoluteAnchor`` without ``xdr:from``, a sheet
    with no ``start`` at all — goes to the returned tail, which the caller renders
    after the table. A hit cell becomes composite text: its own text first
    (``_cell_to_text``: numbers keep their integer form) then the link, with
    images sharing a cell joined by spaces in anchor order (spec 2026-10-03 D2=乙).
    """
    if not images:
        return rows, []
    matrix = [list(row) for row in rows]
    tail: list[ParsedImage] = []
    width = len(matrix[0]) if matrix else 0
    for image, abs_row, abs_col in images:
        if abs_row is None or abs_col is None or start is None:
            tail.append(image)
            continue
        row_idx, col_idx = abs_row - start[0], abs_col - start[1]
        if not (0 <= row_idx < len(matrix) and 0 <= col_idx < width):
            tail.append(image)
            continue
        row = matrix[row_idx]
        while len(row) <= col_idx:
            row.append(None)
        text = _cell_to_text(row[col_idx])
        link = f"![图片]({image.ref})"
        row[col_idx] = f"{text} {link}" if text else link
    return matrix, tail


async def _parse_excel(path: Path) -> ParsedDocument:
    """Parse an ``.xlsx``/``.xls`` workbook into one GFM table per sheet.

    Gated behind ``rag.table.enabled`` and needs ``python-calamine`` (lazy
    import): when the gate is off or the library is missing, raises a clear,
    actionable ``ValueError`` so the document fails loudly instead of silently
    producing nothing (spec 2026-09-09 §4/§8). The blocking workbook read runs on
    the file-IO pool via ``run_file_io``; each sheet becomes ``## {sheet_name}`` +
    a GFM pipe table (see ``_workbook_rows_to_markdown``).

    ``.xlsx`` embedded images ride along (spec 2026-10-03 D2=乙): each image's
    ``xdr:from`` anchor is normalized against calamine's ``sheet.start`` and the
    link merges into its cell (``原文本 ![图片](ref)``); unplaceable images fall
    back to the sheet tail. The extraction is best-effort — ``BadZipFile`` /
    ``ET.ParseError`` / ``KeyError`` degrade to the text-only leg with a warning.
    ``.xls`` never attempts the zip read (D1=甲: the old binary format keeps no
    image support).
    """
    if not table_ingest_enabled():
        raise ValueError("Excel 解析被门控关闭：需开启 rag.table.enabled 才能入库 .xlsx/.xls（spec 2026-09-09 §4）")

    def _blocking() -> list[tuple[str, list[list[object]], tuple[int, int] | None]]:
        try:
            from python_calamine import CalamineWorkbook  # 延迟 import：缺失即降级
        except ImportError as exc:
            raise ValueError("python-calamine 未安装：Excel 解析需要它（pip install python-calamine，对齐视频重依赖的 uv pip 安装先例）") from exc
        workbook = CalamineWorkbook.from_path(str(path))
        sheets: list[tuple[str, list[list[object]], tuple[int, int] | None]] = []
        for name in workbook.sheet_names:
            sheet = workbook.get_sheet_by_name(name)
            sheets.append((name, sheet.to_python(), sheet.start))
        return sheets

    sheets = await run_file_io(_blocking)

    images_by_sheet: dict[str, list[tuple[ParsedImage, int | None, int | None]]] = {}
    if path.suffix.lower() == ".xlsx":
        try:
            images_by_sheet = await run_file_io(lambda: _extract_xlsx_images(path))
        except (zipfile.BadZipFile, ET.ParseError, KeyError):
            logger.warning("failed to extract embedded images from workbook %s; parsing text only", path, exc_info=True)

    sheet_rows: list[tuple[str, list[list[object]]]] = []
    trailing_images_by_sheet: dict[str, list[ParsedImage]] = {}
    images: list[ParsedImage] = []
    for name, rows, start in sheets:
        entries = images_by_sheet.get(name, [])
        merged_rows, tail = _merge_anchor_links(rows, start, entries)
        sheet_rows.append((name, merged_rows))
        if tail:
            trailing_images_by_sheet[name] = tail
        images.extend(image for image, _, _ in entries)

    return ParsedDocument(markdown=_workbook_rows_to_markdown(sheet_rows, trailing_images_by_sheet=trailing_images_by_sheet), images=images)


# ── 工作簿内嵌图片提取（spec 2026-10-03 D2=乙/§2.4）────────────────────────────
#
# ``.xlsx`` is a zip: the images inside it are read straight from the OOXML
# relationship chain (workbook → sheet rels → drawing anchors → drawing rels →
# ``xl/media/``) with the stdlib only. The returned anchor is the ``xdr:from``
# 0-based absolute ``(row, col)`` — ``None``s when the anchor has none — which
# ``_parse_excel`` normalizes against calamine's sheet origin afterwards.


def _rels_part(part: str) -> str:
    """``xl/drawings/drawing1.xml`` → ``xl/drawings/_rels/drawing1.xml.rels``."""
    parent, _, base = part.rpartition("/")
    return f"{parent}/_rels/{base}.rels" if parent else f"_rels/{base}.rels"


def _resolve_part(base_part: str, target: str) -> str:
    """A relationship target → package part: absolute (``/xl/…``) or relative
    (``../media/…``, resolved against ``base_part``'s directory)."""
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join(base_part.rpartition("/")[0], target))


def _read_rels(zf: zipfile.ZipFile, part: str) -> dict[str, tuple[str, str, bool]]:
    """``part``'s relationships as ``{Id: (Type, Target, is_external)}``.

    A missing rels part reads as empty — sheets without relationships are normal
    (spec 2026-10-03 §2.4). A malformed part propagates: the ``_parse_excel``
    caller turns any ``BadZipFile``/``ET.ParseError``/``KeyError`` into the
    text-only fallback.
    """
    try:
        raw = zf.read(_rels_part(part))
    except KeyError:
        return {}
    rels: dict[str, tuple[str, str, bool]] = {}
    for node in ET.fromstring(raw).findall(f"{{{_XLSX_RELS_NS}}}Relationship"):
        rel_id = node.get("Id")
        if rel_id:
            rels[rel_id] = (node.get("Type") or "", node.get("Target") or "", node.get("TargetMode") == "External")
    return rels


def _anchor_cell(anchor: ET.Element) -> tuple[int | None, int | None]:
    """The anchor's ``xdr:from`` as 0-based absolute ``(row, col)``.

    ``None``s when it has none (``absoluteAnchor``) or the coordinates do not
    parse — both fall back to the sheet tail downstream (spec 2026-10-03 D2=乙).
    """
    from_el = anchor.find(f"{{{_XLSX_XDR_NS}}}from")
    if from_el is None:
        return None, None
    try:
        return int(from_el.findtext(f"{{{_XLSX_XDR_NS}}}row", "")), int(from_el.findtext(f"{{{_XLSX_XDR_NS}}}col", ""))
    except ValueError:
        return None, None


def _drawing_images(zf: zipfile.ZipFile, drawing_part: str, seen_media: set[str]) -> list[tuple[ParsedImage, int | None, int | None]]:
    """Images one drawing part anchors: ``r:embed`` refs into ``xl/media/`` only.

    ``r:link`` (external image) carries no bytes in the package and is skipped,
    along with out-of-boundary parts, non-allowlisted media types, dangling
    relationships and repeated references (``seen_media`` keeps the first
    anchor). A drawing or media part missing from the package is skipped per
    part — everything else still comes out (spec 2026-10-03 §2.4).
    """
    try:
        raw = zf.read(drawing_part)
    except KeyError:
        return []  # part-level: a missing drawing is skipped, the rest still comes out
    rels = _read_rels(zf, drawing_part)
    entries: list[tuple[ParsedImage, int | None, int | None]] = []
    for anchor in ET.fromstring(raw):
        if not anchor.tag.endswith("Anchor"):
            continue
        blip = anchor.find(f".//{{{_XLSX_A_NS}}}blip")
        embed_id = blip.get(f"{{{_XLSX_R_NS}}}embed") if blip is not None else None
        if not embed_id:
            continue  # r:link (external) or a blipless anchor
        rel = rels.get(embed_id)
        if rel is None or rel[2]:
            continue  # dangling relationship or an external target
        media_part = _resolve_part(drawing_part, rel[1])
        media_key = media_part.lower()
        if not media_key.startswith("xl/media/") or media_key in seen_media:
            continue  # out-of-boundary part or a repeated reference
        media_type = _MEDIA_TYPES.get(posixpath.splitext(media_key)[1])
        if media_type is None:
            continue  # not in the frozen image allowlist (e.g. .emf/.wmf)
        try:
            content = zf.read(media_part)
        except KeyError:
            continue  # part-level: a missing media part is skipped, the rest still comes out
        seen_media.add(media_key)
        row, col = _anchor_cell(anchor)
        entries.append((ParsedImage(ref=f"images/{posixpath.basename(media_part)}", content=content, media_type=media_type), row, col))
    return entries


def _xlsx_sheet_images(zf: zipfile.ZipFile) -> dict[str, list[tuple[ParsedImage, int | None, int | None]]]:
    """Extract the workbook's embedded images, sheet by sheet, from an open zip.

    Follows ``xl/workbook.xml`` → workbook rels → worksheet part → sheet rels →
    drawing part (spec 2026-10-03 §2.4). Sheets come back in workbook order,
    images in anchor order; a sheet with nothing extracted is absent.
    """
    sheets: dict[str, list[tuple[ParsedImage, int | None, int | None]]] = {}
    seen_media: set[str] = set()
    workbook_rels = _read_rels(zf, "xl/workbook.xml")
    root = ET.fromstring(zf.read("xl/workbook.xml"))
    for node in root.findall(f"{{{_XLSX_MAIN_NS}}}sheets/{{{_XLSX_MAIN_NS}}}sheet"):
        name = node.get("name")
        rel = workbook_rels.get(node.get(f"{{{_XLSX_R_NS}}}id") or "")
        if not name or rel is None or rel[2] or not rel[0].endswith("/worksheet"):
            continue
        sheet_part = _resolve_part("xl/workbook.xml", rel[1])
        entries: list[tuple[ParsedImage, int | None, int | None]] = []
        for rel_type, target, external in _read_rels(zf, sheet_part).values():
            if external or not rel_type.endswith("/drawing"):
                continue
            entries.extend(_drawing_images(zf, _resolve_part(sheet_part, target), seen_media))
        if entries:
            sheets[name] = entries
    return sheets


def _extract_xlsx_images(path: Path) -> dict[str, list[tuple[ParsedImage, int | None, int | None]]]:
    """``_xlsx_sheet_images`` over a workbook path (see there for the rules).

    Raises ``zipfile.BadZipFile`` for a non-zip file — the caller degrades that
    to the text-only leg (spec 2026-10-03 §2.4).
    """
    with zipfile.ZipFile(path) as zf:
        return _xlsx_sheet_images(zf)


class MineruError(Exception):
    """MinerU parse failure: business error code or HTTP error."""

    def __init__(self, message: str, *, code: str | int | None = None, status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


class MineruAuthError(MineruError):
    """Token missing/invalid/expired (A0202/A0211 or env var unset)."""


class MineruParseFailedError(MineruError):
    """The document itself failed to parse (state=failed, err_msg set)."""


class MineruTimeoutError(MineruError):
    """Polling exceeded the configured timeout."""


@dataclass(slots=True)
class ParsedImage:
    """One image unpacked from the result zip; ``ref`` matches the markdown."""

    ref: str
    content: bytes
    media_type: str


@dataclass(slots=True)
class ParsedDocument:
    markdown: str
    images: list[ParsedImage] = field(default_factory=list)


_TOKEN_ENV_HINT = f"{_TOKEN_ENV_VAR} is not set; add it to .env (see .env.example)"


def _read_token() -> str:
    token = configured_rag_secret("mineru_api_token") or os.environ.get(_TOKEN_ENV_VAR)
    if not token:
        raise MineruAuthError(_TOKEN_ENV_HINT)
    return token


def _check_envelope(payload: dict) -> dict:
    """Unwrap the MinerU envelope; raise on non-zero business codes."""
    code = payload.get("code", 0)
    if code == 0:
        return payload.get("data") or {}
    msg = payload.get("msg") or f"MinerU error {code}"
    if str(code) in _AUTH_CODES:
        raise MineruAuthError(msg, code=code)
    raise MineruError(msg, code=code)


def _check_http(response: httpx.Response) -> None:
    if response.status_code >= 400:
        raise MineruError(f"MinerU HTTP {response.status_code}: {response.text[:200]}", status=response.status_code)


async def _apply_upload_url(client: httpx.AsyncClient, *, file_name: str, data_id: str, model_version: str, language: str = "ch", base_url: str = MINERU_BASE_URL, token: str) -> tuple[str, str]:
    response = await client.post(
        f"{base_url}/api/v4/file-urls/batch",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"files": [{"name": file_name, "data_id": data_id}], "model_version": model_version, "language": language},
    )
    _check_http(response)
    data = _check_envelope(response.json())
    file_urls = data.get("file_urls") or []
    if not data.get("batch_id") or not file_urls:
        raise MineruError(f"MinerU returned no batch_id/file_urls: {data!r}")
    return data["batch_id"], file_urls[0]


async def _upload_file(client: httpx.AsyncClient, upload_url: str, content: bytes) -> None:
    # Bare binary PUT: MinerU explicitly requires no Content-Type header.
    response = await client.put(upload_url, content=content)
    if response.status_code not in (200, 201):
        raise MineruError(f"MinerU upload HTTP {response.status_code}", status=response.status_code)


async def _poll_result(client: httpx.AsyncClient, *, batch_id: str, file_name: str, token: str, poll_interval_seconds: float, timeout_seconds: float, base_url: str = MINERU_BASE_URL) -> str:
    deadline = time.monotonic() + timeout_seconds
    url = f"{base_url}/api/v4/extract-results/batch/{batch_id}"
    while True:
        response = await client.get(url, headers={"Authorization": f"Bearer {token}"})
        _check_http(response)
        data = _check_envelope(response.json())
        results = data.get("extract_result") or []
        entry = next((r for r in results if r.get("file_name") == file_name), results[0] if results else None)
        state = (entry or {}).get("state", "")
        if state == "done":
            zip_url = (entry or {}).get("full_zip_url")
            if not zip_url:
                raise MineruError(f"MinerU task done but full_zip_url missing: {entry!r}")
            return zip_url
        if state == "failed":
            raise MineruParseFailedError((entry or {}).get("err_msg") or "MinerU parse failed")
        if state not in _PENDING_STATES:
            logger.warning("Unknown MinerU poll state %r; continuing to poll", state)
        if time.monotonic() >= deadline:
            raise MineruTimeoutError(f"MinerU parse timed out after {timeout_seconds:.0f}s (batch {batch_id})")
        await asyncio.sleep(poll_interval_seconds)


#: 与 chunker 同口径的标题边界（H1/H2）与代码 fence 起始行，仅用于文末标题归一化。
_HEADING_LINE_RE = re.compile(r"^(#{1,2})\s+(\S.*)$")
_FENCE_LINE_RE = re.compile(r"^\s*```")


def _relocate_trailing_title(markdown: str) -> str:
    """把 MinerU 放到文末的唯一 H1/H2 标题行搬回文档开头（2026-09-04 实测）。

    MinerU VLM 偶发把页面标题作为 ``##`` 标题行输出在正文之后（春秋肠.pdf
    复现）；chunker 会忠实保留该顺序并把尾部「纯标题小块」并入正文块，切片
    随之变成「正文在前、加粗标题在后」的颠倒形态。仅当同时满足以下保守条件
    时才搬移，合法结构（多标题文档末尾的悬空小节标题等）不受影响：

    1. 全文最后一个非空行是代码 fence 外的 H1/H2 标题行；
    2. 该标题是全文唯一标题；
    3. 标题之前存在非空正文（全文仅一行标题时无可搬移对象）。
    """
    lines = markdown.splitlines()
    last = len(lines) - 1
    while last >= 0 and not lines[last].strip():
        last -= 1
    if last <= 0 or not _HEADING_LINE_RE.match(lines[last]):
        return markdown
    in_fence = False
    headings = 0
    has_body = False
    for line in lines[:last]:
        if _FENCE_LINE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            has_body = has_body or bool(line.strip())
            continue
        if _HEADING_LINE_RE.match(line):
            headings += 1
        elif line.strip():
            has_body = True
    if in_fence or headings or not has_body:
        return markdown
    body = "\n".join(lines[:last]).rstrip()
    return f"{lines[last].rstrip()}\n\n{body}"


#: Matches a ``<table>``/``</table>`` open or close token (group 1 == "/" on close).
_TABLE_TOKEN_RE = re.compile(r"<(/?)table\b[^>]*>", re.IGNORECASE)


def _find_table_spans(markdown: str) -> list[tuple[int, int, bool]]:
    """Locate each top-level ``<table>…</table>`` span as ``(start, end, nested)``.

    Only balanced top-level tables are recorded. A span that contains another
    ``<table>`` is flagged *nested* so the caller leaves it as residual HTML for
    the chunker's atomic-block defense (spec 2026-09-09 §6).
    """
    spans: list[tuple[int, int, bool]] = []
    stack: list[int] = []
    for match in _TABLE_TOKEN_RE.finditer(markdown):
        if match.group(1) != "/":
            stack.append(match.start())
        elif stack:
            start = stack.pop()
            if not stack:  # a top-level table just closed
                inner = markdown[start : match.end()]
                opens = sum(1 for t in _TABLE_TOKEN_RE.finditer(inner) if t.group(1) != "/")
                spans.append((start, match.end(), opens > 1))
    return spans


def _span_int(attrs: dict, key: str) -> int:
    """rowspan/colspan as an int ≥ 1 (missing/invalid → 1)."""
    try:
        return max(1, int(str(attrs.get(key) or "1").strip()))
    except (TypeError, ValueError):
        return 1


class _TableCellParser(HTMLParser):
    """Collect ``<tr>`` rows of cells from one non-nested table.

    Each cell records its text (nested tags stripped, sibling ``<p>`` blocks
    joined by a single space — never a newline, char refs decoded, whitespace
    collapsed), its rowspan/colspan, and whether it is a header cell (``<th>`` or
    inside ``<thead>``). Covers the two MinerU forms frozen in spec 2026-09-09 §5.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[dict]] = []
        self._row: list[dict] | None = None
        self._cell: dict | None = None
        self._in_thead = False

    def handle_starttag(self, tag: str, attrs) -> None:
        attributes = dict(attrs)
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._cell = {
                "parts": [],
                "rowspan": _span_int(attributes, "rowspan"),
                "colspan": _span_int(attributes, "colspan"),
                "is_header": tag == "th" or self._in_thead,
            }
        elif tag == "thead":
            self._in_thead = True
        elif tag == "p" and self._cell is not None and self._cell["parts"]:
            self._cell["parts"].append(" ")  # join sibling <p> blocks with one space

    def handle_endtag(self, tag: str) -> None:
        if tag == "thead":
            self._in_thead = False
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None
        elif tag in ("td", "th") and self._cell is not None:
            self._cell["text"] = re.sub(r"\s+", " ", "".join(self._cell["parts"])).strip()
            if self._row is not None:
                self._row.append(self._cell)
            self._cell = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell["parts"].append(data)


def _flatten_rows(rows: list[list[dict]], width: int) -> list[list[str]]:
    """Flatten rowspan/colspan into a rectangular *width*-column grid of strings.

    A rowspan value sinks down into the rows it spans (each retrieval row card
    stays self-contained); a colspan value lands in its first column and leaves
    the remaining spanned columns empty. Cells beyond *width* are dropped and
    short rows stay empty-padded (spec 2026-09-09 §5).
    """
    grid: list[list[str]] = []
    pending: dict[int, tuple[int, str]] = {}  # column → (rows remaining, value)
    for row in rows:
        out = [""] * width
        carried = set(pending)
        for col in carried:
            remaining, value = pending[col]
            if col < width:
                out[col] = value
            if remaining <= 1:
                del pending[col]
            else:
                pending[col] = (remaining - 1, value)
        col = 0
        for cell in row:
            while col < width and col in carried:
                col += 1
            if col >= width:
                break
            colspan = cell["colspan"]
            rowspan = cell["rowspan"]
            out[col] = cell["text"]
            if rowspan > 1:
                for span_col in range(col, min(col + colspan, width)):
                    pending[span_col] = (rowspan - 1, cell["text"] if span_col == col else "")
            col += colspan
        grid.append(out)
    return grid


def _normalize_one_table(table_html: str) -> str | None:
    """Convert one non-nested ``<table>…</table>`` into a GFM pipe table.

    Returns ``None`` when it cannot be flattened (no rows / no columns) so the
    caller keeps the original HTML as residual (chunker defends, spec §6). The
    header is the first ``<th>``/``<thead>`` row, else the first ``<tr>`` (form A);
    an all-empty header is kept empty — column names are never guessed.
    """
    cell_parser = _TableCellParser()
    try:
        cell_parser.feed(table_html)
        cell_parser.close()
    except Exception:  # malformed markup → residual HTML
        return None
    rows = [row for row in cell_parser.rows if row]
    if not rows:
        return None
    header_idx = next((i for i, row in enumerate(rows) if any(cell["is_header"] for cell in row)), 0)
    width = sum(cell["colspan"] for cell in rows[header_idx])
    if width <= 0:
        width = max((sum(cell["colspan"] for cell in row) for row in rows), default=0)
    if width <= 0:
        return None
    grid = _flatten_rows(rows, width)
    header = grid[header_idx]
    data = grid[header_idx + 1 :] + grid[:header_idx]
    lines = [_gfm_row(header), _gfm_separator(width)]
    lines.extend(_gfm_row(row) for row in data)
    return "\n".join(lines)


def _normalize_tables_to_gfm(markdown: str) -> str:
    """Rewrite every top-level HTML ``<table>`` into a GFM pipe table.

    MinerU v4 + ``model_version="vlm"`` emits HTML tables rather than GFM (Task 0
    实测门, spec 2026-09-09 §5), so this is a required step on the MinerU branch —
    never on user-authored local ``.md``. Content outside ``<table>`` spans
    (prose, headings, existing GFM tables) is preserved byte-for-byte, making the
    pass an idempotent no-op when there is no HTML table. Nested/malformed tables
    stay residual for the chunker's atomic-block defense (§6).
    """
    spans = _find_table_spans(markdown)
    if not spans:
        return markdown
    pieces: list[str] = []
    cursor = 0
    for start, end, nested in spans:
        pieces.append(markdown[cursor:start])
        original = markdown[start:end]
        replacement = None if nested else _normalize_one_table(original)
        pieces.append(original if replacement is None else replacement)
        cursor = end
    pieces.append(markdown[cursor:])
    return "".join(pieces)


def normalize_mineru_markdown(markdown: str) -> str:
    """The two MinerU-output steps, in order: trailing-title relocation, then GFM tables.

    Both belong to *any* MinerU provider, not just the cloud one (spec §4.4): a
    self-hosted service emits the same markdown generator's output, so it has the same
    HTML-``<table>`` shape and the same occasional trailing-title quirk. User-authored
    local ``.md`` never goes through here.
    """
    return _normalize_tables_to_gfm(_relocate_trailing_title(markdown))


def _unpack_zip(zip_bytes: bytes) -> ParsedDocument:
    markdown: str | None = None
    images: list[ParsedImage] = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        md_name = next((n for n in names if n.endswith("full.md")), None) or next((n for n in names if n.endswith(".md")), None)
        if md_name is None:
            raise MineruError("MinerU result zip contains no markdown file")
        markdown = zf.read(md_name).decode("utf-8")
        for name in names:
            path = Path(name)
            if path.parts and path.parts[0] == "images" and path.suffix.lower() in _MEDIA_TYPES:
                images.append(ParsedImage(ref=name, content=zf.read(name), media_type=_MEDIA_TYPES[path.suffix.lower()]))
    return ParsedDocument(markdown=markdown, images=images)


class MineruCloudParseProvider:
    """The MinerU cloud client (spec §4.4: 云 provider = 现有实现，不改行为).

    Class-shaped so the parse leg matches the other provider legs
    (``parse(path) -> ParsedDocument``) and the curated allowlist can name it; the
    request sequence is exactly the pre-provider one.
    """

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        model_version: str,
        language: str,
        base_url: str,
        poll_interval_seconds: float = 5.0,
        timeout_seconds: float = 1800.0,
    ) -> None:
        self._client = client
        self._model_version = model_version
        self._language = language
        self._base_url = base_url
        self._poll_interval_seconds = poll_interval_seconds
        self._timeout_seconds = timeout_seconds

    async def parse(self, file_path: str | Path) -> ParsedDocument:
        path = Path(file_path)
        token = _read_token()
        own_client = self._client is None
        http = self._client or httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=30.0))
        try:
            batch_id, upload_url = await _apply_upload_url(http, file_name=path.name, data_id=path.stem, model_version=self._model_version, language=self._language, base_url=self._base_url, token=token)
            await _upload_file(http, upload_url, path.read_bytes())
            zip_url = await _poll_result(
                http,
                batch_id=batch_id,
                file_name=path.name,
                token=token,
                poll_interval_seconds=self._poll_interval_seconds,
                timeout_seconds=self._timeout_seconds,
                base_url=self._base_url,
            )
            zip_parsed = _unpack_zip(await _download_zip(zip_url))
            return ParsedDocument(markdown=normalize_mineru_markdown(zip_parsed.markdown), images=zip_parsed.images)
        finally:
            if own_client:
                await http.aclose()


def build_parse_provider(
    *,
    rag: Any | None = None,
    client: httpx.AsyncClient | None = None,
    model_version: str | None = None,
    language: str | None = None,
    base_url: str | None = None,
    poll_interval_seconds: float = 5.0,
    timeout_seconds: float = 1800.0,
) -> object:
    """Resolve ``rag.parse_provider`` through the curated allowlist (spec §4.1).

    Same rule as the rerank factory: the provider id picks the implementation, the caller never
    supplies a class path. Constructor kwargs differ per provider, so the split lives here —
    ``mineru-local`` takes the configured address and tier hint, the cloud provider takes
    ``model_version`` / ``language`` / ``base_url``, each resolved from the ``rag`` section when
    the caller passes nothing (spec 2026-09-29 D2; the cloud address falls back to the vendor
    constant only when nothing is configured).

    ``rag`` overrides the RAG section for this call, so the save-time check can construct the
    provider from the configuration it is about to write instead of the live one (spec 2026-09-17
    alignment §3 D2). Everything else keeps its default: **construction never touches the
    network** (the cloud client reads its token in ``parse()``), which is what lets that check
    cover this leg for free.
    """
    section = get_app_config().rag if rag is None else rag
    spec = resolve_provider("parse", section.parse_provider)
    kwargs: dict = {"client": client, "poll_interval_seconds": poll_interval_seconds, "timeout_seconds": timeout_seconds}
    if spec.provider_id == "mineru-local":
        kwargs["base_url"] = section.parse_base_url
        kwargs["tier"] = section.parse_tier
    else:
        kwargs["model_version"] = model_version if model_version is not None else section.parse_model_version
        kwargs["language"] = language if language is not None else section.parse_language
        kwargs["base_url"] = base_url if base_url is not None else (section.parse_base_url or MINERU_BASE_URL)
    from deerflow.reflection import resolve_variable

    return resolve_variable(spec.implementation)(**kwargs)


async def parse_document(
    file_path: str | Path,
    *,
    client: httpx.AsyncClient | None = None,
    model_version: str | None = None,
    language: str | None = None,
    base_url: str | None = None,
    poll_interval_seconds: float = 5.0,
    timeout_seconds: float = 1800.0,
) -> ParsedDocument:
    """Parse a local document with the configured MinerU provider.

    Provider is ``rag.parse_provider`` (default ``mineru-cloud`` = the MinerU v4 API;
    ``mineru-local`` = a self-hosted MinerU HTTP service, which needs
    ``rag.parse_base_url``). ``model_version`` / ``language`` / ``base_url`` are cloud-only
    knobs; passing ``None`` reads the configured ``rag`` values (spec 2026-09-29 D2).

    ``.md``/``.markdown``/``.txt`` files are read locally (UTF-8 strict with GBK
    fallback); ``.csv``/``.tsv`` are parsed locally into a GFM pipe table and
    ``.xlsx``/``.xls`` into one GFM table per sheet via python-calamine
    (spec 2026-09-09 §5; ``.xlsx`` also contributes its embedded images, their
    links merged into the anchor cells — spec 2026-10-03 D2=乙) — none of these
    ever hit the network, whichever provider is configured. Provider output has
    its HTML ``<table>`` blocks normalized to GFM and a
    trailing title relocated (see ``normalize_mineru_markdown``). The cloud token comes
    from the ``MINERU_API_TOKEN`` env var; the local service ships without auth. Image
    references in the returned markdown point at ``ParsedImage.ref`` entries.
    """
    path = Path(file_path)
    suffix = path.suffix.lower()
    if suffix in _DELIMITED_SUFFIXES:
        return ParsedDocument(markdown=_parse_delimited(path), images=[])
    if suffix in _EXCEL_SUFFIXES:
        return await _parse_excel(path)
    if is_local_suffix(suffix):
        return ParsedDocument(markdown=_read_local_text(path), images=[])

    provider = build_parse_provider(
        client=client,
        model_version=model_version,
        language=language,
        base_url=base_url,
        poll_interval_seconds=poll_interval_seconds,
        timeout_seconds=timeout_seconds,
    )
    return await provider.parse(path)


async def _download_via(zip_url: str, *, proxy: str | None) -> bytes:
    kwargs: dict = {"timeout": httpx.Timeout(120.0, connect=30.0), "follow_redirects": True}
    if proxy:
        kwargs["proxy"] = proxy
    async with httpx.AsyncClient(**kwargs) as client:
        response = await client.get(zip_url)
        _check_http(response)
        return response.content


async def _download_zip(zip_url: str) -> bytes:
    """下载 MinerU result zip。

    企业安全软件（实测为 Hillstone Secure Connect，2026-08-23 定位）可能在网络层
    切断本机到 cdn-mineru 的 TLS 流量（握手放行、传输切断），导致 ConnectError。
    设置 ``MINERU_ZIP_PROXY`` 环境变量（如 ``http://127.0.0.1:57519``）后优先走
    代理；代理不可达时自动降级直连，两种网络环境（安全软件开/关）都能工作。
    独立于共享 client：下载对象不同（CDN 而非 MinerU API），且需隔离代理配置。
    """
    proxy = os.environ.get("MINERU_ZIP_PROXY")
    if proxy:
        try:
            return await _download_via(zip_url, proxy=proxy)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ProxyError):
            logger.warning("MINERU_ZIP_PROXY %s unreachable, falling back to direct download", proxy)
    return await _download_via(zip_url, proxy=None)
