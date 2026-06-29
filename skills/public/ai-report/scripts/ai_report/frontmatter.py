"""Parse table.md files with YAML frontmatter into ai-report design dicts.

A single table.md describes one table within one section of one report. Multiple
table.md files (one per table) collectively define one report; merge them with
`merge_table_designs` before calling `import_design_json`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


_REQUIRED_KEYS: tuple[str, ...] = (
    "report_id",
    "report_name",
    "report_title",
    "section_key",
    "section_title",
    "section_order",
    "table_id",
    "table_title",
    "table_order",
)


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Return (frontmatter_dict, body_text).

    An empty frontmatter or no leading `---` returns ({}, text). A leading `---`
    without a closing `---` raises ValueError so silent truncation does not pass.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            fm_text = "\n".join(lines[1:i])
            body = "\n".join(lines[i + 1 :])
            data = yaml.safe_load(fm_text) or {}
            if not isinstance(data, dict):
                raise ValueError(f"Frontmatter must be a YAML mapping, got {type(data).__name__}")
            return data, body
    raise ValueError("Unterminated YAML frontmatter (missing closing `---`)")


def parse_table_md(path: str | Path) -> dict[str, Any]:
    """Parse a single table.md file into a partial design dict.

    Required frontmatter keys (design spec §10): report_id, report_name,
    report_title, section_key, section_title, section_order, table_id,
    table_title, table_order.

    The returned dict is a slice of the shape accepted by `import_design_json`
    and covers one report / one section / one table. `section_id` is derived
    from `section_key` so multiple tables in the same section share it.
    """
    text = Path(path).read_text(encoding="utf-8")
    fm, _body = _split_frontmatter(text)
    missing = [k for k in _REQUIRED_KEYS if k not in fm]
    if missing:
        raise ValueError(f"Missing required frontmatter keys in {path}: {missing}")

    section_key = str(fm["section_key"])
    return {
        "report": {
            "report_id": str(fm["report_id"]),
            "report_name": str(fm["report_name"]),
            "report_title": str(fm["report_title"]),
        },
        "sections": [
            {
                "section_id": section_key,
                "section_key": section_key,
                "section_title": str(fm["section_title"]),
                "section_order": int(fm["section_order"]),
            }
        ],
        "tables": [
            {
                "table_id": str(fm["table_id"]),
                "section_id": section_key,
                "table_title": str(fm["table_title"]),
                "table_order": int(fm["table_order"]),
            }
        ],
    }


def parse_table_md_dir(dir_path: str | Path) -> list[dict[str, Any]]:
    """Parse every `*.md` file directly under `dir_path`.

    Returns one partial design per file. Non-md files and files in subdirectories
    are ignored. Callers must call `merge_table_designs` to combine them.
    """
    root = Path(dir_path)
    if not root.is_dir():
        raise ValueError(f"Not a directory: {root}")
    partials: list[dict[str, Any]] = []
    for md_path in sorted(root.glob("*.md")):
        if not md_path.is_file():
            continue
        partials.append(parse_table_md(md_path))
    if not partials:
        raise ValueError(f"No `*.md` table files found in {root}")
    return partials


def merge_table_designs(*partials: dict[str, Any]) -> dict[str, Any]:
    """Merge multiple partial designs into one full design for `import_design_json`.

    All partials must share one report_id. Sections are deduplicated by
    section_key; tables are concatenated in input order.
    """
    if not partials:
        raise ValueError("At least one partial design required")
    report_ids = {p["report"]["report_id"] for p in partials}
    if len(report_ids) != 1:
        raise ValueError(
            f"All partials must share one report_id, got {sorted(report_ids)}"
        )

    report = dict(partials[0]["report"])
    sections_by_key: dict[str, dict[str, Any]] = {}
    tables: list[dict[str, Any]] = []
    for p in partials:
        for s in p.get("sections", []):
            sections_by_key.setdefault(s["section_key"], s)
        tables.extend(p.get("tables", []))
    return {
        "report": report,
        "sections": list(sections_by_key.values()),
        "tables": tables,
    }