from __future__ import annotations

from typing import Any


def _escape_cell(value: Any) -> str:
    return str(value).replace("|", "\\|")


def _columns(rows: list[dict[str, Any]]) -> list[str]:
    ordered = ["branch_num", "branch_short_name"]
    seen = set(ordered)
    for row in rows:
        for key in row.get("cells", {}):
            if key not in seen:
                ordered.append(key)
                seen.add(key)
    return ordered


def _render_table(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["_(no data rows)_"]
    cols = _columns(rows)
    lines = [
        "| " + " | ".join(cols) + " |",
        "| " + " | ".join(["---"] * len(cols)) + " |",
    ]
    for row in rows:
        values = []
        for col in cols:
            if col == "branch_num":
                values.append(row.get("branch_num", ""))
            elif col == "branch_short_name":
                values.append(row.get("branch_short_name", ""))
            else:
                values.append(row.get("cells", {}).get(col, ""))
        lines.append("| " + " | ".join(_escape_cell(v) for v in values) + " |")
    return lines


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [f"# {payload['report'].get('report_title') or payload['report']['report_id']}", ""]
    for section in payload.get("sections", []):
        lines.extend([f"## {section['section_title']}", ""])
        for table in section.get("tables", []):
            lines.extend([f"### {table['table_title']}", ""])
            if table.get("description_text"):
                lines.extend([table["description_text"], ""])
            lines.extend(_render_table(table.get("rows", [])))
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"
