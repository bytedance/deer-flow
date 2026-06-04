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

import yaml

ToolOutputKind = Literal["json", "csv", "tsv", "yaml", "xml", "code", "text", "unknown"]

_KEY_LIMIT = 12
_SCALAR_LIMIT = 6
_TABLE_SAMPLE_ROWS = 50
_TABLE_COLUMN_LIMIT = 18
_TABLE_FIRST_ROW_CHARS = 220
_TEXT_HEADER_LIMIT = 16
_TEXT_EXCERPT_CHARS = 420
_CODE_IMPORT_LIMIT = 12
_CODE_SYMBOL_LIMIT = 24
_JSON_STRUCTURE_LIMIT = 24
_JSON_STRUCTURE_DEPTH = 4

_CODE_HINTS = (
    re.compile(r"^\s*(?:from\s+\S+\s+import|import\s+\S+)", re.MULTILINE),
    re.compile(r"^\s*(?:class|def|async\s+def|function|export\s+function)\s+[A-Za-z_]\w*", re.MULTILINE),
    re.compile(r"^\s*(?:package|use|pub\s+fn|fn|public\s+class)\s+[A-Za-z_]\w*", re.MULTILINE),
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
    json_synopsis = _try_json(stripped)
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
    """Render a file-backed preview as a typed synopsis plus access hint."""
    total = len(content)
    synopsis = build_tool_output_synopsis(content, tool_name=tool_name)
    sample_budget = max(0, head_chars) + max(0, tail_chars)
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

    sample = synopsis.sample
    if sample:
        lines.append("")
        lines.append("Sample:")
        lines.append(_clip(sample, sample_budget) if sample_budget else sample)

    lines.append("")
    lines.append("Access:")
    lines.append(f"- Use read_file on {virtual_path} with start_line and end_line to inspect the raw output.")
    lines.append("- Start near the line hints above when present; byte offsets are approximate anchors into the saved file.")
    return "\n".join(lines)


def _clip(value: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)] + "..."


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
    if depth >= 2:
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


def _json_path_location(content: str, key_parts: list[Any]) -> str:
    """Return an approximate source location for a JSON object path."""
    if not key_parts:
        return ""

    search_from = 0
    pos = -1
    for key in key_parts:
        quoted = json.dumps(str(key), ensure_ascii=False)
        pos = content.find(quoted, search_from)
        if pos < 0:
            return ""
        search_from = pos + len(quoted)

    line = content.count("\n", 0, pos) + 1
    byte_offset = len(content[:pos].encode("utf-8"))
    return f" (line {line}, byte offset {byte_offset})"


def _json_container_paths(content: str, value: Any, *, limit: int = _JSON_STRUCTURE_LIMIT) -> list[str]:
    """Summarize nested JSON container paths with approximate locations."""
    paths: list[str] = []

    def walk(node: Any, current_path: str, key_parts: list[Any], depth: int) -> None:
        if len(paths) >= limit or depth >= _JSON_STRUCTURE_DEPTH:
            return
        if isinstance(node, dict):
            for key, child in list(node.items())[:_KEY_LIMIT]:
                if len(paths) >= limit:
                    break
                next_parts = [*key_parts, key]
                next_path = _json_path(current_path, key)
                if isinstance(child, (dict, list)):
                    paths.append(
                        f"{next_path}: {_json_container_description(child)}"
                        f"{_json_path_location(content, next_parts)}"
                    )
                    walk(child, next_path, next_parts, depth + 1)
            return
        if isinstance(node, list) and node:
            first = node[0]
            if isinstance(first, (dict, list)):
                walk(first, f"{current_path}[]", key_parts, depth + 1)

    walk(value, "$", [], 0)
    return paths


def _scalar_examples(value: Any, *, path: str = "$", limit: int = _SCALAR_LIMIT) -> list[str]:
    examples: list[str] = []

    def walk(node: Any, current: str) -> None:
        if len(examples) >= limit:
            return
        if isinstance(node, dict):
            for key, child in list(node.items())[:_KEY_LIMIT]:
                walk(child, f"{current}.{key}")
                if len(examples) >= limit:
                    break
            return
        if isinstance(node, list):
            for index, child in enumerate(node[:2]):
                walk(child, f"{current}[{index}]")
                if len(examples) >= limit:
                    break
            return
        examples.append(f"{current}: {_short_value(node)}")

    walk(value, path)
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
    structure.extend(_json_container_paths(content, value))
    notable = _scalar_examples(value)
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
    try:
        root = ET.fromstring(stripped)
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
    if any(len(row) != width for row in rows[1:10]):
        return None

    columns = [cell.strip() or f"column_{idx + 1}" for idx, cell in enumerate(rows[0])]
    total_nonempty_lines = sum(1 for line in content.splitlines() if line.strip())
    data_rows = max(0, total_nonempty_lines - 1)
    first_data = delimiter.join(rows[1]) if len(rows) > 1 else ""
    title = "CSV table output" if kind == "csv" else "TSV table output"
    label = kind.upper()
    return ToolOutputSynopsis(
        kind=kind,
        title=title,
        summary=[f"{label} table with {data_rows} data rows and {width} columns."],
        structure=[
            f"columns: {', '.join(columns[:_TABLE_COLUMN_LIMIT])}",
            f"first data row: {_one_line(first_data, _TABLE_FIRST_ROW_CHARS) or '(none)'}",
        ],
        notable_items=[],
    )


def _looks_yaml(content: str) -> bool:
    stripped = content.lstrip()
    if stripped.startswith("---"):
        return True
    if _looks_code(content):
        return False
    key_like = 0
    for line in content.splitlines()[:80]:
        if re.match(r"^\s*[A-Za-z0-9_.-]+:\s*(?:.+)?$", line):
            key_like += 1
            if key_like >= 2:
                return True
    return False


def _try_yaml(content: str) -> ToolOutputSynopsis | None:
    if not _looks_yaml(content):
        return None
    try:
        value = yaml.safe_load(content)
    except Exception:
        return None
    if not isinstance(value, (dict, list)):
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


def _summarize_text(content: str, *, tool_name: str = "") -> ToolOutputSynopsis:
    lines = content.splitlines()
    normalized = re.sub(r"\s+", " ", content).strip()
    headers: list[str] = []
    seen: set[str] = set()
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if not (
            re.match(r"^#{1,6}\s+", stripped)
            or re.match(r"^[A-Z0-9][A-Z0-9\s:_-]{6,}$", stripped)
        ):
            continue
        header = _one_line(stripped, 160)
        if header in seen:
            continue
        seen.add(header)
        headers.append(header)
        if len(headers) >= _TEXT_HEADER_LIMIT:
            break

    opener = _one_line(content[:_TEXT_EXCERPT_CHARS], _TEXT_EXCERPT_CHARS)
    closer = _one_line(content[-_TEXT_EXCERPT_CHARS:], _TEXT_EXCERPT_CHARS)
    word_count = len(normalized.split()) if normalized else 0
    tool_hint = f" from {tool_name}" if tool_name else ""
    return ToolOutputSynopsis(
        kind="text",
        title="Text output",
        summary=[
            f"Text output{tool_hint} with {len(content)} characters, {word_count} words, and {len(lines)} lines.",
            f"Detected section headers: {' | '.join(headers) if headers else 'none detected'}.",
            f"Opening excerpt: {opener or '(empty)'}",
            f"Closing excerpt: {closer or '(empty)'}",
        ],
        structure=[],
        notable_items=[],
    )
