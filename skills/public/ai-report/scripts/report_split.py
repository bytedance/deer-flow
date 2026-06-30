"""ai-report: split a whole report MD into H2 section blocks (新写)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SectionBlock:
    section_order: int
    section_title: str
    source_md: str


def split_report(md: str) -> list[SectionBlock]:
    """Split MD on '## ' boundaries. Each section's source_md contains its H3 sub-tables.

    Content before the first '## ' heading is dropped (H1 is the report title, not a section).
    """
    out: list[SectionBlock] = []
    order = 0
    current_title: str | None = None
    current_body: list[str] = []
    for line in md.splitlines():
        if line.startswith("## "):
            if current_title is not None:
                out.append(SectionBlock(order, current_title, "\n".join(current_body)))
                order += 1
            current_title = line[3:].strip()
            current_body = []
        else:
            current_body.append(line)
    if current_title is not None:
        out.append(SectionBlock(order, current_title, "\n".join(current_body)))
    return out