"""Structure-aware markdown chunker (spec §3.2).

Strategy: structure first, size as the backstop —

1. Split on H1/H2 heading boundaries (a ``#`` inside a code fence never
   splits); every block carries its ``heading_path``.
2. Blocks over ``MAX_CHUNK_TOKENS`` are subdivided by paragraph (greedy
   packing); a single paragraph that still overflows is hard-split by token.
3. Blocks under ``MIN_CHUNK_TOKENS`` merge into the previous sibling, but only
   when the merged block stays within the cap — this keeps an oversized
   block's short tail (e.g. a trailing code fence) from re-inflating it.
4. Tables are atomic (spec §6/§7): a GFM pipe table (a ``|…|`` row followed by
   a delimiter row) becomes one ``is_table`` block routed to
   ``_chunk_table_block`` — header repeated per row group, a provenance line on
   multi-block splits, ``card_mode`` markdown / linearized; a residual HTML
   ``<table>`` block is kept whole and never hard-split. A ``|`` inside a code
   fence is never a table.

Target size is 512±256 tokens. Token counting uses tiktoken cl100k_base,
matching the rest of the harness (memory budgeting etc.).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import tiktoken

MAX_CHUNK_TOKENS = 1024
MIN_CHUNK_TOKENS = 100

_HEADING_RE = re.compile(r"^(#{1,2})\s+(\S.*)$")
_FENCE_RE = re.compile(r"^\s*```")
# GFM 管道表：数据/表头行以 `|` 起止；分隔行只含 `| - : 空格`（spec §7.1 双条件）。
_GFM_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
_GFM_DELIM_RE = re.compile(r"^\s*\|[\s:|-]+\|\s*$")

_encoding: tiktoken.Encoding | None = None


def _enc() -> tiktoken.Encoding:
    global _encoding
    if _encoding is None:
        _encoding = tiktoken.get_encoding("cl100k_base")
    return _encoding


def count_tokens(text: str) -> int:
    """cl100k_base token count — the single counting source for chunk sizes."""
    return len(_enc().encode(text))


@dataclass(slots=True)
class Chunk:
    """One chunk per spec §3.2. ``kb_id``/``entities`` are filled downstream:
    ``kb_id`` by the indexing pipeline, ``entities`` by the graph backfill."""

    chunk_id: str
    doc_id: str
    text: str
    heading_path: list[str]
    chunk_index: int
    token_count: int
    kb_id: str = ""
    page: int | None = None  # full.md carries no page markers in Phase 1
    entities: list[str] = field(default_factory=list)


@dataclass(slots=True)
class _Block:
    """Internal split unit: text + heading path + table flag (spec §6/§7).

    ``is_table`` marks an atomic table block — it bypasses paragraph packing and
    hard token splits, routed instead to ``_chunk_table_block`` (GFM) or kept
    whole (residual HTML ``<table>``), so a table is never sliced mid-row/mid-tag.
    """

    path: list[str]
    text: str
    is_table: bool = False


def _split_by_headings(markdown: str) -> list[_Block]:
    """Split into blocks on H1/H2 boundaries, tagging tables atomic (spec §6/§7).

    Preserves the heading-in-text semantics (the heading line stays in its
    block's text; ``path`` carries the H1/H2 hierarchy). Adds table detection: a
    GFM pipe table (a ``|…|`` row + delimiter row) or a residual HTML
    ``<table>…</table>`` becomes one ``is_table`` block, never merged with prose
    nor split here. Code-fence content is never a table.
    """
    blocks: list[_Block] = []
    path: list[str] = []
    h1: str | None = None
    buf: list[str] = []
    in_fence = False
    lines = markdown.splitlines()
    n = len(lines)

    def flush() -> None:
        text = "\n".join(buf).strip()
        if text:
            blocks.append(_Block(path=list(path), text=text))
        buf.clear()

    i = 0
    while i < n:
        line = lines[i]
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            buf.append(line)
            i += 1
            continue
        if not in_fence:
            match = _HEADING_RE.match(line)
            if match:
                flush()
                level = len(match.group(1))
                title = match.group(2).strip()
                if level == 1:
                    h1 = title
                    path = [title]
                else:
                    # An H2 nests under the last H1; with no H1 seen yet (e.g.
                    # Excel sheets emitted as sibling ``## {sheet}``), each H2 is
                    # its own root so paths don't spuriously accumulate a prior
                    # sibling (keeps ``heading_path == [sheet]`` per sheet).
                    path = [h1, title] if h1 else [title]
                buf.append(line)
                i += 1
                continue
            # GFM 管道表：当前行是管道行且次行是分隔行 → 原子表格块（§7.1）。
            if _GFM_ROW_RE.match(line) and i + 1 < n and _GFM_DELIM_RE.match(lines[i + 1]):
                flush()
                table_lines = [line, lines[i + 1]]
                j = i + 2
                while j < n and _GFM_ROW_RE.match(lines[j]):
                    table_lines.append(lines[j])
                    j += 1
                blocks.append(_Block(path=list(path), text="\n".join(table_lines), is_table=True))
                i = j
                continue
            # 残留 HTML <table>…</table> → 原子块（绝不硬切，§7.3）。
            if "<table" in line.lower():
                flush()
                html_lines: list[str] = []
                depth = 0
                j = i
                while j < n:
                    low = lines[j].lower()
                    html_lines.append(lines[j])
                    depth += low.count("<table")
                    depth -= low.count("</table>")
                    if depth <= 0:
                        break
                    j += 1
                blocks.append(_Block(path=list(path), text="\n".join(html_lines).strip(), is_table=True))
                i = j + 1
                continue
        buf.append(line)
        i += 1
    flush()
    return _drop_orphan_headings_before_table(blocks)


def _is_heading_only(text: str) -> bool:
    """True if every non-empty line is an H1/H2 heading (no prose body)."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return bool(lines) and all(_HEADING_RE.match(ln) for ln in lines)


def _drop_orphan_headings_before_table(blocks: list[_Block]) -> list[_Block]:
    """Drop heading-only blocks whose next kept block is a table.

    A heading immediately preceding a table carries no body of its own; its title
    already lives in the table block's path (surfaced as heading_path), so emitting
    it as a separate chunk yields a useless near-empty card — one per Excel sheet
    in the workbook-normalized markdown. Prose headings (next kept block is not a
    table) keep their heading-in-text semantics untouched.
    """
    kept: list[_Block] = []
    next_is_table = False
    for block in reversed(blocks):
        if not block.is_table and _is_heading_only(block.text) and next_is_table:
            continue
        kept.append(block)
        next_is_table = block.is_table
    kept.reverse()
    return kept


def _hard_split_tokens(text: str, max_tokens: int) -> list[str]:
    """Last-resort split for a single paragraph that exceeds the cap."""
    ids = _enc().encode(text)
    return [_enc().decode(ids[i : i + max_tokens]) for i in range(0, len(ids), max_tokens)]


def _pack_paragraphs(text: str, max_tokens: int) -> list[str]:
    """Greedy-pack blank-line-separated paragraphs under the token cap."""
    paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    packs: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if count_tokens(candidate) <= max_tokens:
            current = candidate
            continue
        if current:
            packs.append(current)
        if count_tokens(paragraph) > max_tokens:
            packs.extend(_hard_split_tokens(paragraph, max_tokens))
            current = ""
        else:
            current = paragraph
    if current:
        packs.append(current)
    return packs


def _subdivide_oversized(blocks: list[_Block], max_tokens: int) -> list[_Block]:
    result: list[_Block] = []
    for block in blocks:
        if block.is_table:
            result.append(block)  # tables are atomic; chunk_markdown routes them
            continue
        if count_tokens(block.text) <= max_tokens:
            result.append(block)
            continue
        for pack in _pack_paragraphs(block.text, max_tokens):
            result.append(_Block(path=block.path, text=pack))
    return result


def _merge_small_blocks(blocks: list[_Block], min_tokens: int, max_tokens: int) -> list[_Block]:
    """Merge a <min_tokens block into the previous sibling.

    Skipped when the merge would exceed *max_tokens* — otherwise the short
    tail of a just-subdivided oversized block would re-inflate it. Table blocks
    are never merged (nor merged into): they stay atomic (spec §6/§7).
    """
    merged: list[_Block] = []
    for block in blocks:
        if block.is_table:
            merged.append(block)
            continue
        if merged and not merged[-1].is_table and count_tokens(block.text) < min_tokens:
            prev = merged[-1]
            candidate = f"{prev.text}\n\n{block.text}"
            if count_tokens(candidate) <= max_tokens:
                merged[-1] = _Block(path=prev.path, text=candidate)
                continue
        merged.append(block)
    return merged


def _is_gfm_table_text(text: str) -> bool:
    """True if a block's text is a GFM pipe table (header row + delimiter row)."""
    lines = text.splitlines()
    return len(lines) >= 2 and bool(_GFM_ROW_RE.match(lines[0])) and bool(_GFM_DELIM_RE.match(lines[1]))


def _parse_gfm_table_block(text: str) -> tuple[str, str, list[str]]:
    """Split a pure GFM table block into (header_line, delimiter_line, data_rows)."""
    lines = text.splitlines()
    return lines[0], lines[1], lines[2:]


def _parse_table_columns(header: str) -> list[str]:
    """``| Region | Q1 |`` → ``["Region", "Q1"]``."""
    return [cell.strip() for cell in header.strip().strip("|").split("|")]


def _linearize_row(row: str, columns: list[str]) -> str:
    """``| North | 100 |`` + ``["Region", "Q1"]`` → ``Region: North | Q1: 100`` (linearized card)."""
    cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
    pairs = []
    for idx, col in enumerate(columns):
        value = cells[idx] if idx < len(cells) else ""
        pairs.append(f"{col}: {value}")
    return " | ".join(pairs)


def _chunk_table_block(
    path: list[str],
    header: str,
    delimiter: str,
    rows: list[str],
    max_tokens: int,
    card_mode: str,
) -> list[_Block]:
    """Header-anchored row-group splitting for a GFM table (spec §6/§7).

    - Every group repeats header + delimiter, so each chunk is self-describing.
    - Greedy packing keeps header + a group's rows ≤ *max_tokens*.
    - Multi-block splits prefix a provenance line
      ``表格：{名}（第 {起}-{止} 行 / 共 {N} 行）``.
    - ``card_mode``: ``markdown`` keeps GFM rows; ``linearized`` renders each row
      as ``列名: 值 | 列名: 值`` (narrow-context models).
    - Degenerate: a single row whose header + row exceeds the cap stays whole in
      its own block — a row is never mid-sliced.
    """
    columns = _parse_table_columns(header)
    name = path[-1] if path else "未命名表"
    total = len(rows)
    rendered = [_linearize_row(row, columns) for row in rows] if card_mode == "linearized" else list(rows)
    header_text = f"{header}\n{delimiter}"
    header_tokens = count_tokens(header_text)

    groups: list[list[str]] = []
    current: list[str] = []
    current_tokens = header_tokens
    for row in rendered:
        row_tokens = count_tokens(row)
        if current and current_tokens + row_tokens > max_tokens:
            groups.append(current)
            current = []
            current_tokens = header_tokens
        current.append(row)
        current_tokens += row_tokens
    if current:
        groups.append(current)
    if not groups:  # header-only table
        groups = [[]]

    multi = len(groups) > 1
    blocks: list[_Block] = []
    cursor = 1
    for group in groups:
        body = header_text if not group else header_text + "\n" + "\n".join(group)
        if multi:
            start, end = cursor, cursor + len(group) - 1
            body = f"表格：{name}（第 {start}-{end} 行 / 共 {total} 行）\n\n{body}"
            cursor = end + 1
        blocks.append(_Block(path=list(path), text=body, is_table=True))
    return blocks


def chunk_markdown(
    markdown: str,
    doc_id: str,
    *,
    max_tokens: int = MAX_CHUNK_TOKENS,
    min_tokens: int = MIN_CHUNK_TOKENS,
    card_mode: str = "markdown",
) -> list[Chunk]:
    """Chunk parsed markdown per spec §3.2; returns [] for empty input.

    ``card_mode`` (spec §4/§7) controls table row rendering — ``markdown``
    (default, GFM rows) or ``linearized`` (``列名: 值`` sentences). Non-table
    prose is unaffected.
    """
    blocks = _split_by_headings(markdown)
    blocks = _subdivide_oversized(blocks, max_tokens)
    blocks = _merge_small_blocks(blocks, min_tokens, max_tokens)

    final: list[_Block] = []
    for block in blocks:
        if block.is_table and _is_gfm_table_text(block.text):
            header, delimiter, rows = _parse_gfm_table_block(block.text)
            final.extend(_chunk_table_block(block.path, header, delimiter, rows, max_tokens, card_mode))
        else:
            # Non-table prose, and residual HTML ``<table>`` blocks (is_table but
            # not GFM) — the latter stay atomic, never hard-split (spec §7.3).
            final.append(block)

    return [
        Chunk(
            chunk_id=f"{doc_id}#{index:04d}",
            doc_id=doc_id,
            text=block.text,
            heading_path=block.path,
            chunk_index=index,
            token_count=count_tokens(block.text),
        )
        for index, block in enumerate(final)
    ]
