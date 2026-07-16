"""Deterministic summaries for oversized tool output previews."""

from __future__ import annotations

import csv
import io
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from typing import Any, Literal

try:
    from defusedxml import ElementTree as SafeET  # type: ignore[import-not-found]
except ImportError:
    SafeET = None  # Fall back to stdlib; risk is limited (agent-requested output).

import yaml

ToolOutputKind = Literal["json", "csv", "tsv", "yaml", "xml", "code", "text", "unknown"]

_KEY_LIMIT = 12
_SCALAR_LIMIT = 6
_TABLE_SAMPLE_ROWS = 50
_TABLE_COLUMN_LIMIT = 18
_TEXT_HEADER_LIMIT = 16
_TEXT_EXCERPT_CHARS = 420
_CODE_IMPORT_LIMIT = 12
_CODE_SYMBOL_LIMIT = 24
_JSON_SHAPE_MAX_DEPTH = 2
_JSON_STRUCTURE_LIMIT = 24
_JSON_STRUCTURE_DEPTH = 4

# Hard cap on the synopsis input size. Beyond this threshold the full parse
# is skipped and only a raw head/tail sample is emitted. This bounds the
# worst-case memory/CPU when externalized tool output is pathologically large
# (e.g. 50+ MB log dumps) and prevents DoS via XML/YAML entity-expansion.
_MAX_SYNOPSIS_INPUT_BYTES = 5_000_000

_CODE_HINTS = (
    re.compile(r"^\s*(?:from\s+\S+\s+import|import\s+\S+)", re.MULTILINE),
    re.compile(r"^\s*(?:class|def|async\s+def|function|export\s+function)\s+[A-Za-z_]\w*", re.MULTILINE),
    # Require stronger signals for Rust/Java: `use ...;` (trailing semicolon),
    # `fn ...(` (parenthesised), `pub fn ...(`, `public class ...`.  Bare
    # `use <word>` or `fn <word>` misclassifies prose (e.g. "use the following …").
    re.compile(r"^\s*(?:package\s+[A-Za-z_][\w.]*|use\s+[A-Za-z_][\w:]*\s*;|pub\s+fn\s+[A-Za-z_]\w*\s*\(|fn\s+[A-Za-z_]\w*\s*\(|public\s+class\s+[A-Za-z_]\w*)", re.MULTILINE),
)


@dataclass(frozen=True)
class ToolOutputSynopsis:
    """Structured preview data for an oversized tool output."""

    kind: ToolOutputKind
    title: str
    summary: list[str]
    structure: list[str]
    notable_items: list[str]
    sample: str = ""


def build_tool_output_synopsis(content: str, *, tool_name: str = "") -> ToolOutputSynopsis:
    """Return a typed synopsis for *content* without using an LLM."""
    if content == "":
        return ToolOutputSynopsis(
            kind="unknown",
            title="Empty output",
            summary=["The tool returned an empty string."],
            structure=[],
            notable_items=[],
        )

    # Size guard: parsing the full content above the threshold is a DoS risk
    # (XML entity expansion, YAML alias bombs, memory/CPU from raw text).
    # Fall back to a raw head/tail sample to bound the worst case.
    if len(content.encode("utf-8")) > _MAX_SYNOPSIS_INPUT_BYTES:
        return ToolOutputSynopsis(
            kind="unknown",
            title="Oversized output",
            summary=[
                f"The output has {len(content)} characters ({len(content.encode('utf-8')) / 1024 / 1024:.1f} MB). Parsing skipped due to size limit.",
            ],
            structure=[],
            notable_items=[],
            sample=_head_tail_sample(content, _TEXT_EXCERPT_CHARS * 2),
        )

    if _looks_binary(content):
        return ToolOutputSynopsis(
            kind="unknown",
            title="Binary-like output",
            summary=[f"The output has {len(content)} characters and includes non-text control bytes."],
            structure=[],
            notable_items=[],
            sample=_head_tail_sample(content, _TEXT_EXCERPT_CHARS * 2),
        )

    stripped = content.strip()
    json_synopsis = _try_json(content)
    if json_synopsis is not None:
        return json_synopsis

    xml_synopsis = _try_xml(stripped)
    if xml_synopsis is not None:
        return xml_synopsis

    if "\t" in content:
        table = _try_table(content, delimiter="\t", kind="tsv")
        if table is not None:
            return table

    if "," in content:
        table = _try_table(content, delimiter=",", kind="csv")
        if table is not None:
            return table

    yaml_synopsis = _try_yaml(content)
    if yaml_synopsis is not None:
        return yaml_synopsis

    if _looks_code(content):
        return _summarize_code(content)

    return _summarize_text(content, tool_name=tool_name)


def render_tool_output_preview(
    content: str,
    *,
    tool_name: str,
    virtual_path: str,
    head_chars: int,
    tail_chars: int,
) -> str:
    """Render a file-backed preview as a typed synopsis plus a raw head/tail sample.

    The synopsis is the primary signal; the raw sample restores the
    inline head/tail bytes that operators used to get from
    preview_head_chars / preview_tail_chars before the synopsis was
    added. For binary-like output the synopsis already carries a raw
    sample; for everything else we slice head_chars from the start and
    tail_chars from the end of *content*.
    """
    total = len(content)
    synopsis = build_tool_output_synopsis(content, tool_name=tool_name)
    head_budget = max(0, head_chars)
    tail_budget = max(0, tail_chars)
    # For text kind, skip excerpts in the synopsis when a raw sample will be
    # appended (avoids duplicating head/tail bytes in both places).
    if synopsis.kind == "text" and head_budget + tail_budget > 0 and len(content) > head_budget + tail_budget:
        synopsis = _summarize_text(content, tool_name=tool_name, include_excerpts=False)
    lines = [
        f"[Full {tool_name} output saved to {virtual_path} ({total} chars, ~{total // 4} tokens).]",
        f"[Preview kind: {synopsis.kind}. This is a structured synopsis, not a raw head/tail truncation.]",
        "",
        f"{synopsis.title}:",
    ]
    lines.extend(f"- {item}" for item in synopsis.summary)

    if synopsis.structure:
        lines.append("")
        lines.append("Structure:")
        lines.extend(f"- {item}" for item in synopsis.structure)

    if synopsis.notable_items:
        lines.append("")
        lines.append("Notable items:")
        lines.extend(f"- {item}" for item in synopsis.notable_items)

    raw_sample = _build_raw_sample(content, head_budget=head_budget, tail_budget=tail_budget, existing=synopsis.sample)
    if raw_sample:
        lines.append("")
        lines.append("Raw sample (head + tail, clipped to head_chars / tail_chars):")
        lines.append(raw_sample)

    lines.append("")
    lines.append("Access:")
    lines.append(f"- Use read_file on {virtual_path} with start_line and end_line to inspect the raw output.")
    return "\n".join(lines)


def _clip(value: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)] + "..."


def _build_raw_sample(content: str, *, head_budget: int, tail_budget: int, existing: str) -> str:
    """Compose the inline head/tail raw sample.

    If the synopsis already provides a sample (binary-like output), use
    it directly. Otherwise slice head_budget bytes from the start and
    tail_budget bytes from the end, snapping to line boundaries so
    previews end on clean line breaks. Avoids duplicate bytes when the
    two slices would overlap.
    """
    if existing:
        return existing
    if head_budget <= 0 and tail_budget <= 0:
        return ""
    if len(content) <= head_budget + tail_budget:
        return content
    parts: list[str] = []
    if head_budget > 0:
        head = content[:head_budget]
        # Snap to the last newline within the budget for clean truncation.
        snap = head.rfind("\n")
        if snap > 0:
            head = head[:snap]
        parts.append(head)
    if tail_budget > 0 and head_budget + tail_budget < len(content):
        tail = content[-tail_budget:]
        # Snap to the first newline within the tail for clean truncation.
        snap = tail.find("\n")
        if snap >= 0 and snap < len(tail) - 1:
            tail = tail[snap + 1 :]
        parts.append(tail)
    if len(parts) == 2:
        return f"{parts[0]}\n...\n{parts[1]}"
    return parts[0]


def _one_line(value: str, limit: int) -> str:
    return _clip(re.sub(r"\s+", " ", value).strip(), limit)


def _head_tail_sample(content: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if len(content) <= limit:
        return content
    half = max(1, limit // 2)
    return f"{content[:half]}\n...\n{content[-half:]}"


def _looks_binary(content: str) -> bool:
    if "\x00" in content:
        return True
    sample = content[:1000]
    controls = sum(1 for char in sample if ord(char) < 32 and char not in "\n\r\t")
    return controls / max(1, len(sample)) > 0.05


def _type_name(value: Any) -> str:
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, bool):
        return "boolean"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return "number"
    return "string"


def _short_value(value: Any) -> str:
    if isinstance(value, str):
        return json.dumps(_clip(value, 80), ensure_ascii=False)
    return _clip(repr(value), 80)


def _json_shape(value: Any, *, depth: int = 0) -> str:
    if depth >= _JSON_SHAPE_MAX_DEPTH:
        return "..."
    if isinstance(value, dict):
        keys = [str(key) for key in list(value.keys())[:_KEY_LIMIT]]
        suffix = f": {', '.join(keys)}" if keys else ""
        return f"object(keys={len(value)}{suffix})"
    if isinstance(value, list):
        samples = ", ".join(_json_shape(item, depth=depth + 1) for item in value[:3])
        suffix = f", first=[{samples}]" if samples else ""
        return f"array(len={len(value)}{suffix})"
    return _type_name(value)


def _json_path(parent: str, key: Any) -> str:
    key_text = str(key)
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key_text):
        return f"{parent}.{key_text}"
    return f"{parent}[{json.dumps(key_text, ensure_ascii=False)}]"


def _json_container_description(value: Any) -> str:
    if isinstance(value, dict):
        keys = [str(key) for key in list(value.keys())[:_KEY_LIMIT]]
        suffix = f"; keys {', '.join(keys)}" if keys else ""
        return f"object keys {len(value)}{suffix}"
    if isinstance(value, list):
        detail = f"array length {len(value)}"
        if value:
            detail += f"; first item {_type_name(value[0])}"
        return detail
    return _type_name(value)


def _json_container_paths(value: Any, *, limit: int = _JSON_STRUCTURE_LIMIT) -> list[str]:
    """Summarize nested JSON container paths.

    Locations are intentionally omitted: an approximate '(line N, byte
    offset M)' anchor based on string search is wrong whenever a key
    string also appears as a value earlier in the document, or when
    the same key occurs at multiple depths. The path itself is already
    useful navigation; the agent uses read_file with start_line from
    its own judgement of where the relevant slice is.
    """
    paths: list[str] = []

    def walk(node: Any, current_path: str, depth: int) -> None:
        if len(paths) >= limit or depth >= _JSON_STRUCTURE_DEPTH:
            return
        if isinstance(node, dict):
            for key, child in list(node.items())[:_KEY_LIMIT]:
                if len(paths) >= limit:
                    break
                next_path = _json_path(current_path, key)
                if isinstance(child, (dict, list)):
                    paths.append(f"{next_path}: {_json_container_description(child)}")
                    walk(child, next_path, depth + 1)
            return
        if isinstance(node, list) and node:
            first = node[0]
            if isinstance(first, (dict, list)):
                walk(first, f"{current_path}[]", depth + 1)

    walk(value, "$", 0)
    return paths


def _scalar_examples(value: Any, *, path: str = "$", limit: int = _SCALAR_LIMIT) -> list[str]:
    examples: list[str] = []

    def walk(node: Any, current: str, depth: int) -> None:
        if len(examples) >= limit or depth >= _JSON_STRUCTURE_DEPTH:
            return
        if isinstance(node, dict):
            for key, child in list(node.items())[:_KEY_LIMIT]:
                walk(child, f"{current}.{key}", depth + 1)
                if len(examples) >= limit:
                    break
            return
        if isinstance(node, list):
            for index, child in enumerate(node[:2]):
                walk(child, f"{current}[{index}]", depth + 1)
                if len(examples) >= limit:
                    break
            return
        examples.append(f"{current}: {_short_value(node)}")

    walk(value, path, 0)
    return examples


def _try_json(content: str) -> ToolOutputSynopsis | None:
    stripped = content.strip()
    if not stripped.startswith(("{", "[")):
        return None
    try:
        decoder = json.JSONDecoder()
        value, end = decoder.raw_decode(stripped)
    except Exception:
        return None

    trailing = len(stripped[end:].strip())
    summary: list[str] = []
    structure: list[str] = [f"shape: {_json_shape(value)}"]
    structure.extend(_json_container_paths(value))
    notable = _scalar_examples(value)
    # NOTE: scalar examples may surface values from anywhere in the parsed
    # structure (not just head/tail bytes). This is expected behaviour — the
    # synopsis is a structural summary, not a confidentiality filter. Operators
    # who relied on the old preview to only expose head/tail snippets should
    # review their tool outputs for sensitive mid-document values.
    if isinstance(value, dict):
        keys = [str(key) for key in value.keys()]
        summary.append(f"JSON object with {len(keys)} top-level keys.")
        summary.append(f"Top-level keys: {', '.join(keys[:_KEY_LIMIT]) or '(none)'}")
    elif isinstance(value, list):
        summary.append(f"JSON array with {len(value)} items.")
        if value:
            structure.append(f"first item type: {_type_name(value[0])}")
    else:
        summary.append(f"JSON {_type_name(value)}.")

    if trailing:
        notable.append(f"Trailing non-JSON characters after first value: {trailing}")

    return ToolOutputSynopsis(
        kind="json",
        title="JSON output",
        summary=summary,
        structure=structure,
        notable_items=notable,
    )


def _try_xml(stripped: str) -> ToolOutputSynopsis | None:
    if not stripped.startswith("<"):
        return None
    if SafeET is None:  # defusedxml not available; skip XML parsing to avoid entity-expansion DoS
        return None
    try:
        root = (SafeET or ET).fromstring(stripped)
    except Exception:
        return None

    child_counts = Counter(child.tag for child in list(root))
    structure = [f"root tag: {root.tag}", f"root attributes: {len(root.attrib)}"]
    structure.extend(f"{tag}: {count}" for tag, count in child_counts.most_common(_KEY_LIMIT))
    return ToolOutputSynopsis(
        kind="xml",
        title="XML output",
        summary=[f"XML document with root tag {root.tag}."],
        structure=structure,
        notable_items=[],
    )


_TABLE_MIN_DATA_ROWS = 5
_TABLE_HEADER_IDENT_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*$")


def _try_table(content: str, *, delimiter: str, kind: Literal["csv", "tsv"]) -> ToolOutputSynopsis | None:
    sample_text = "\n".join(content.splitlines()[:_TABLE_SAMPLE_ROWS])
    try:
        rows = list(csv.reader(io.StringIO(sample_text), delimiter=delimiter))
    except csv.Error:
        return None

    rows = [row for row in rows if any(cell.strip() for cell in row)]
    if len(rows) < 2 or len(rows[0]) < 2:
        return None

    width = len(rows[0])
    consistent = [row for row in rows[1:11] if len(row) == width]
    # Require >= _TABLE_MIN_DATA_ROWS same-width data rows for both TSV and CSV.
    # TSV sees a lot of false positives (indented bash, ls -l listings, tree
    # dumps). CSV is rarer but prose with a comma in the first line also slips
    # through without this gate.
    if len(consistent) < _TABLE_MIN_DATA_ROWS:
        return None

    # Header row must look like identifiers (no whitespace, no leading ws).
    # Refuses tab-indented bash output, ls -l listings, and tree dumps that
    # happen to be tab-delimited.
    raw_header = rows[0]
    if any(not _TABLE_HEADER_IDENT_RE.match(cell.strip()) for cell in raw_header):
        return None
    if any(cell.startswith((" ", "\t")) for cell in raw_header):
        return None

    columns = [cell.strip() or f"column_{idx + 1}" for idx, cell in enumerate(raw_header)]
    total_nonempty_lines = sum(1 for line in content.splitlines() if line.strip())
    data_rows = max(0, total_nonempty_lines - 1)
    # Render the first data row as a key=value list so quoted cells that
    # contain the delimiter do not get rejoined into a comma-separated
    # string that misleads the model about column count.
    first_data_pairs: list[str] = []
    if len(rows) > 1:
        for col_name, cell in list(zip(columns, rows[1]))[:_TABLE_COLUMN_LIMIT]:
            first_data_pairs.append(f"{col_name}={_clip(cell, 80)}")
    title = "CSV table output" if kind == "csv" else "TSV table output"
    label = kind.upper()
    return ToolOutputSynopsis(
        kind=kind,
        title=title,
        summary=[f"{label} table with {data_rows} data rows and {width} columns."],
        structure=[
            f"columns: {', '.join(columns[:_TABLE_COLUMN_LIMIT])}",
            f"first data row: {' | '.join(first_data_pairs) or '(none)'}",
        ],
        notable_items=[],
    )


_YAML_KEY_LINE_RE = re.compile(r"^\s*[A-Za-z_][A-Za-z0-9_.\-]*:\s*\S.*$")


def _looks_yaml(content: str) -> bool:
    """Heuristic detector for YAML-shaped content.

    Returns True only when the content looks structurally like YAML
    (a document start marker, or multiple nested key/value lines with
    values that are not bare uppercase log prefixes). Plain logs,
    Python tracebacks, and `key: value` lines that consist entirely
    of uppercase tags (which YAML treats as string keys) are refused.
    """
    stripped = content.lstrip()
    if stripped.startswith("---"):
        return True
    if _looks_code(content):
        return False

    key_like = 0
    for line in content.splitlines()[:80]:
        if not _YAML_KEY_LINE_RE.match(line):
            continue
        # Reject log-style lines where the key is an uppercase tag and
        # the value is a free-form message: e.g. "INFO: starting service".
        key = line.split(":", 1)[0].strip()
        if key.isupper() and "_" not in key:
            continue
        key_like += 1
        if key_like >= 3:
            return True
    return False


def _try_yaml(content: str) -> ToolOutputSynopsis | None:
    if not _looks_yaml(content):
        return None
    # Bound the parse size to prevent alias-bomb DoS (yaml.safe_load resolves
    # YAML aliases which can expand exponentially). The heuristic detector
    # already rejects most non-YAML content, but a crafted alias bomb can
    # trivially pass the heuristic.
    if len(content) > 500_000:
        return None
    try:
        value = yaml.safe_load(content)
    except Exception:
        return None
    if not isinstance(value, (dict, list)):
        return None
    # Refuse flat "all values are strings" payloads: that shape is what
    # log lines and Python tracebacks collapse into after safe_load, and
    # it gives the model a misleadingly small "YAML with N keys" summary
    # for outputs that are really free-form text.
    if isinstance(value, dict):
        non_string_children = sum(1 for v in value.values() if not isinstance(v, str))
        if non_string_children == 0 and len(value) > 0:
            return None

    summary: list[str]
    structure: list[str] = []
    if isinstance(value, dict):
        keys = [str(key) for key in value.keys()]
        summary = [f"YAML object with {len(keys)} top-level keys.", f"Top-level keys: {', '.join(keys[:_KEY_LIMIT])}"]
        for key, child in list(value.items())[:_KEY_LIMIT]:
            structure.append(f"{key}: {_type_name(child)}")
    else:
        summary = [f"YAML array with {len(value)} items."]
        if value:
            structure.append(f"first item type: {_type_name(value[0])}")

    return ToolOutputSynopsis(
        kind="yaml",
        title="YAML output",
        summary=summary,
        structure=structure,
        notable_items=[],
    )


def _looks_code(content: str) -> bool:
    return any(pattern.search(content) for pattern in _CODE_HINTS)


def _summarize_code(content: str) -> ToolOutputSynopsis:
    imports: list[str] = []
    symbols: list[str] = []
    lines = content.splitlines()
    for line in lines:
        stripped = line.strip()
        import_match = re.match(r"^(?:from\s+(\S+)\s+import|import\s+(\S+))", stripped)
        if import_match:
            imports.append(_one_line(import_match.group(1) or import_match.group(2) or "", 160))
            continue
        symbol_match = re.match(
            r"^(class|def|async\s+def|function|export\s+function|pub\s+fn|fn)\s+([A-Za-z_]\w*)",
            stripped,
        )
        if symbol_match:
            symbols.append(_one_line(f"{symbol_match.group(1)} {symbol_match.group(2)}", 180))

    structure = [f"line count: {len(lines)}"]
    if imports:
        structure.append(f"imports: {', '.join(imports[:_CODE_IMPORT_LIMIT])}")

    return ToolOutputSynopsis(
        kind="code",
        title="Code-like output",
        summary=[f"Code-like text with {len(lines)} lines."],
        structure=structure,
        notable_items=symbols[:_CODE_SYMBOL_LIMIT],
    )


def _summarize_text(content: str, *, tool_name: str = "", include_excerpts: bool = True) -> ToolOutputSynopsis:
    lines = content.splitlines()
    normalized = re.sub(r"\s+", " ", content).strip()
    headers: list[str] = []
    seen: set[str] = set()
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if not (re.match(r"^#{1,6}\s+", stripped) or re.match(r"^[A-Z0-9][A-Z0-9\s:_-]{6,}$", stripped)):
            continue
        header = _one_line(stripped, 160)
        if header in seen:
            continue
        seen.add(header)
        headers.append(header)
        if len(headers) >= _TEXT_HEADER_LIMIT:
            break

    tool_hint = f" from {tool_name}" if tool_name else ""
    summary_lines = [
        f"Text output{tool_hint} with {len(content)} characters, {len(normalized.split()) if normalized else 0} words, and {len(lines)} lines.",
        f"Detected section headers: {' | '.join(headers) if headers else 'none detected'}.",
    ]
    # Include opening/closing excerpts only when no raw head/tail sample will
    # be appended by render_tool_output_preview (avoids duplicating the same
    # head/tail bytes in both the synopsis summary and the raw sample).
    if include_excerpts:
        opener = _one_line(content[:_TEXT_EXCERPT_CHARS], _TEXT_EXCERPT_CHARS)
        if len(content) <= _TEXT_EXCERPT_CHARS:
            closer = ""
        else:
            close_start = max(_TEXT_EXCERPT_CHARS, len(content) - _TEXT_EXCERPT_CHARS)
            closer = _one_line(content[close_start:], _TEXT_EXCERPT_CHARS) if close_start < len(content) else ""
        summary_lines.append(f"Opening excerpt: {opener or '(empty)'}")
        if closer:
            summary_lines.append(f"Closing excerpt: {closer}")
    return ToolOutputSynopsis(
        kind="text",
        title="Text output",
        summary=summary_lines,
        structure=[],
        notable_items=[],
    )
