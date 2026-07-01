"""ai-report: parse MD with H1/H2/H3 + <table> thead/tbody into ReportDoc (新写)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser


@dataclass
class Th:
    text: str = ""
    is_indicator: bool = False
    is_computed: bool = False
    idx_id: str | None = None
    data_unit: str | None = None
    period: str | None = None
    rowspan: int | None = None
    colspan: int | None = None


@dataclass
class ComputedSpec:
    name: str
    prompt: str
    examples: list[dict] = field(default_factory=list)


@dataclass
class OrgContext:
    org_ecd: str
    org_name: str


@dataclass
class Report:
    title: str
    org_contexts: list[OrgContext]
    time_info: list[str]
    headers: list[list[Th]]
    data_rows: list[dict]
    computed_specs: list[ComputedSpec]
    description_prompt: str | None


@dataclass
class Section:
    title: str
    reports: list[Report]


@dataclass
class ReportDoc:
    title: str
    sections: list[Section]
    all_idx_ids: set[str] = field(default_factory=set)


def parse_markdown(md: str) -> ReportDoc:
    """Parse a full multi-section MD into ReportDoc (新写, 借鉴 chatbi-report parse_md 思路)."""
    title, body = _split_title(md)
    sections: list[Section] = []
    all_idx: set[str] = set()
    for section_title, section_body in _split_sections(body):
        reports: list[Report] = []
        for report_title, report_body in _split_reports(section_body):
            rep = _parse_one_report(report_title, report_body)
            reports.append(rep)
            for row in rep.headers:
                for th in row:
                    if th.idx_id:
                        all_idx.add(th.idx_id)
        sections.append(Section(title=section_title, reports=reports))
    return ReportDoc(title=title, sections=sections, all_idx_ids=all_idx)


# ---------- 内部 helpers ---------- #

def _split_title(md: str) -> tuple[str, str]:
    lines = md.splitlines()
    if lines and lines[0].startswith("# "):
        return lines[0][2:].strip(), "\n".join(lines[1:])
    return "", md


def _split_sections(body: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    cur_title, cur_body = "", []
    for line in body.splitlines():
        if line.startswith("## "):
            if cur_title or any(s.strip() for s in cur_body):
                out.append((cur_title, "\n".join(cur_body)))
            cur_title = line[3:].strip()
            cur_body = []
        else:
            cur_body.append(line)
    if cur_title or any(s.strip() for s in cur_body):
        out.append((cur_title, "\n".join(cur_body)))
    return out


def _split_reports(section_body: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    cur_title, cur_body = "", []
    for line in section_body.splitlines():
        if line.startswith("### "):
            if cur_title or any(s.strip() for s in cur_body):
                out.append((cur_title, "\n".join(cur_body)))
            cur_title = line[4:].strip()
            cur_body = []
        else:
            cur_body.append(line)
    if cur_title or any(s.strip() for s in cur_body):
        out.append((cur_title, "\n".join(cur_body)))
    return out


class _TheadCellCollector(HTMLParser):
    """借鉴 chatbi-report: walk thead <tr> → <th>, capture attrs + text."""
    def __init__(self):
        super().__init__()
        self.rows: list[list[dict]] = []
        self._cur_row: list[dict] | None = None
        self._cur_cell: dict | None = None
        self._text_buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "tr":
            self._cur_row = []
        elif tag == "th" and self._cur_row is not None:
            self._cur_cell = {
                "text": "",
                "is_indicator": False,
                # is_computed = formula column (computed at runtime from prompt).
                # data-idx alone means indicator column (lookup idx_id@period) — orthogonal.
                "is_computed": a.get("data-computed") is not None,
                "idx_id": a.get("data-idx"),
                "data_unit": a.get("data-unit"),
                "period": a.get("data-period"),
                "rowspan": int(a["rowspan"]) if a.get("rowspan") else None,
                "colspan": int(a["colspan"]) if a.get("colspan") else None,
            }
            self._text_buf = []
        elif tag == "td" and self._cur_row is not None:
            # 兼容 thead 含 td (不规范) - 跳过
            pass

    def handle_data(self, data):
        if self._cur_cell is not None:
            self._text_buf.append(data)

    def handle_endtag(self, tag):
        if tag == "th" and self._cur_cell is not None:
            self._cur_cell["text"] = "".join(self._text_buf).strip()
            self._cur_row.append(self._cur_cell)
            self._cur_cell = None
        elif tag == "tr" and self._cur_row is not None:
            self.rows.append(self._cur_row)
            self._cur_row = None


def _cell_to_th(cell: dict) -> Th:
    text = cell["text"]
    is_computed = cell["is_computed"] or text.startswith("{{")
    if is_computed and text.startswith("{{"):
        text = text.strip("{}")
    return Th(
        text=text,
        is_indicator=cell["is_indicator"],
        is_computed=is_computed,
        idx_id=cell["idx_id"],
        data_unit=cell["data_unit"],
        period=cell["period"],
        rowspan=cell["rowspan"],
        colspan=cell["colspan"],
    )


def _parse_org_block(body: str) -> list[OrgContext]:
    m = re.search(r"^>\s*机构:\s*org_contexts\s*=\s*(\[.*?\])", body, re.MULTILINE)
    if not m:
        return []
    return [OrgContext(**o) for o in json.loads(m.group(1))]


def _parse_description_block(body: str) -> str | None:
    """Parse optional `> 描述:` block, return prompt string or None.

    Format (same multi-line `>` block as `> 机构:` / `> 时期:`):
        > 描述:
        >   请基于表格数据生成一段经营分析描述...
        >   重点关注:
        >   - 同比变化

    Lines are joined with newlines; sibling blocks (`> 时期:` etc.) terminate
    the block. Block content is passed to _llm_describe as a prompt hint.
    """
    desc_match = re.search(r"^>\s*描述:\s*$", body, re.MULTILINE)
    if not desc_match:
        return None
    lines: list[str] = []
    for raw in body[desc_match.end():].splitlines():
        if not raw:
            continue
        if not raw.startswith(">"):
            break
        if re.match(r"^>\s?\S", raw) and not re.match(r"^>\s{2,}\S", raw):
            break
        line = raw.lstrip("> ").strip()
        if line:
            lines.append(line)
    return "\n".join(lines) if lines else None


def _parse_one_report(report_title: str, body: str) -> Report:
    org_contexts = _parse_org_block(body)
    time_match = re.search(r"^>\s*时期:\s*time_info\s*=\s*(\[.*?\])\s*$", body, re.MULTILINE)
    if not time_match:
        raise ValueError(f"report `{report_title}` missing `> 时期:`; run md_lint first")
    time_info = json.loads(time_match.group(1))
    description_prompt = _parse_description_block(body)

    thead_match = re.search(r"<thead[^>]*>(.*?)</thead>", body, re.DOTALL | re.IGNORECASE)
    if not thead_match:
        raise ValueError(f"report `{report_title}` has no <thead>")
    parser = _TheadCellCollector()
    parser.feed(thead_match.group(1))
    headers_2d = [[_cell_to_th(c) for c in row] for row in parser.rows]

    return Report(
        title=report_title,
        org_contexts=org_contexts,
        time_info=time_info,
        headers=headers_2d,
        data_rows=[],
        computed_specs=[],
        description_prompt=description_prompt,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry: parse MD → dump <stem>.parsed.json (chatbi-report-compatible schema).

    Exit codes:
      0 = success
      2 = MD file not readable / parse error (after re-raise)
    """
    import argparse
    from dataclasses import asdict
    from pathlib import Path

    parser = argparse.ArgumentParser(prog="parse_md")
    parser.add_argument("--md", required=True, help="Path to MD 样张")
    parser.add_argument("--out", required=True, help="Path to write parsed JSON")
    args = parser.parse_args(argv)

    md_path = Path(args.md)
    md = md_path.read_text(encoding="utf-8")
    doc = parse_markdown(md)

    # Build chatbi-report-compatible JSON. Headers are 2-d list of dicts; data_rows
    # is empty (chatbi-report populates it during assemble-wide, not parse).
    payload = {
        "title": doc.title,
        "sections": [
            {
                "title": sec.title,
                "reports": [
                    {
                        "title": rep.title,
                        "org_contexts": [asdict(o) for o in rep.org_contexts],
                        "time_info": list(rep.time_info),
                        "headers": [[asdict(th) for th in row] for row in rep.headers],
                        "data_rows": list(rep.data_rows),
                        "computed_specs": list(rep.computed_specs),
                        "description_prompt": rep.description_prompt,
                    }
                    for rep in sec.reports
                ],
            }
            for sec in doc.sections
        ],
        "all_idx_ids": sorted(doc.all_idx_ids),
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())