"""Parse a chatbi-report MD sample into the ReportDoc AST.

- `headers` 是二维结构（外层 = thead 行，内层 = 该行单元格）以支持
  rowspan/colspan 的多级表头。
- `Th.is_indicator` 优先由 `data-idx` HTML 属性推导，`{{}}` 占位符正则
  作为旧式 MD 的回退。
- 旧式 `<th>{{BAS_0263}}</th>`（无 data-idx，但 `{{}}` 匹配 idx_id 正则）
  仍被识别为 is_indicator=True（render_docx 在此对 idx_name 进行 SQLBot 回退查询）。
- 类目标签单元格（多级 thead 父级，无 data-idx，无 {{}}）以
  is_indicator=False、is_computed=False、idx_id=None 输出 —— 不报错。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

IDX_ID_PATTERN = re.compile(r"^[A-Z]+_\d+$")
COMPUTED_NAME_PATTERN = re.compile(r"^\{\{([^{}!]+)\}\}$")
OLD_PLACEHOLDER_PATTERN = re.compile(r"^\{\{([A-Z]+_\d+)\}\}$")


@dataclass
class Th:
    text: str
    is_indicator: bool
    is_computed: bool
    idx_id: str | None = None
    data_unit: str | None = None
    rowspan: int | None = None
    colspan: int | None = None

    def to_dict(self) -> dict:
        d: dict[str, Any] = {
            "text": self.text,
            "is_indicator": self.is_indicator,
            "is_computed": self.is_computed,
        }
        if self.idx_id is not None:
            d["idx_id"] = self.idx_id
        if self.data_unit is not None:
            d["data_unit"] = self.data_unit
        if self.rowspan is not None:
            d["rowspan"] = self.rowspan
        if self.colspan is not None:
            d["colspan"] = self.colspan
        return d


@dataclass
class ComputedSpec:
    name: str
    prompt: str                          # 原始 "name = expr" 文本
    examples: list[dict] = field(default_factory=list)   # [{"inputs": {...}, "expected": "0.1833"}]


@dataclass
class OrgContext:
    branch_num: str
    branch_short_name: str


@dataclass
class Report:
    title: str
    org_context: OrgContext
    time_info: list[str]
    headers: list[list[Th]]                # 二维：外层 = thead 行索引
    data_rows: list[dict] = field(default_factory=list)
    computed_specs: list[ComputedSpec] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "org_context": {"branch_num": self.org_context.branch_num,
                            "branch_short_name": self.org_context.branch_short_name},
            "time_info": list(self.time_info),
            "headers": [[c.to_dict() for c in row] for row in self.headers],
            "data_rows": list(self.data_rows),
            "computed_specs": [
                {"name": s.name, "prompt": s.prompt, "examples": s.examples}
                for s in self.computed_specs
            ],
        }


@dataclass
class Section:
    title: str
    reports: list[Report]

    def to_dict(self) -> dict:
        return {"title": self.title, "reports": [r.to_dict() for r in self.reports]}


@dataclass
class ReportDoc:
    title: str
    sections: list[Section]
    all_idx_ids: set[str] = field(default_factory=set)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "sections": [s.to_dict() for s in self.sections],
            "all_idx_ids": sorted(self.all_idx_ids),
        }


# ---------- 公开 API ---------- #

def parse_file(path: str) -> ReportDoc:
    return parse_markdown(Path(path).read_text(encoding="utf-8"))


def parse_markdown(md: str) -> ReportDoc:
    title, body = _split_title(md)
    sections_raw = _split_sections(body)
    sections: list[Section] = []
    all_idx: set[str] = set()
    for section_title, section_body in sections_raw:
        reports: list[Report] = []
        for report_title, report_body in _split_reports(section_body):
            rep = _parse_one_report(report_title, report_body)
            reports.append(rep)
            for row in rep.headers:
                for cell in row:
                    if cell.idx_id:
                        all_idx.add(cell.idx_id)
        sections.append(Section(title=section_title, reports=reports))
    return ReportDoc(title=title, sections=sections, all_idx_ids=all_idx)


def parse_report(md: str, section_idx: int = 0, report_idx: int = 0) -> Report:
    """便捷接口：按索引解析特定报表。供测试和 compute.py 使用。"""
    doc = parse_markdown(md)
    return doc.sections[section_idx].reports[report_idx]


# ---------- 内部 ---------- #

def _split_title(md: str) -> tuple[str, str]:
    lines = md.splitlines()
    if lines and lines[0].startswith("# "):
        return lines[0][2:].strip(), "\n".join(lines[1:])
    return "", md


def _split_sections(body: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    cur_title = ""
    cur_body: list[str] = []
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
    cur_title = ""
    cur_body: list[str] = []
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
    """从 <thead>...</thead> 片段中按行收集 list[list[dict]]。"""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[dict]] = []
        self._current_row: list[dict] | None = None
        self._current_cell: dict | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag == "tr":
            self._current_row = []
        elif tag == "th" and self._current_row is not None:
            self._current_cell = {
                "data-idx": a.get("data-idx"),
                "data-unit": a.get("data-unit"),
                "rowspan": int(a["rowspan"]) if a.get("rowspan") else None,
                "colspan": int(a["colspan"]) if a.get("colspan") else None,
                "text": "",
            }
        elif tag == "td" and self._current_row is not None:
            self._current_cell = {
                "data-idx": None, "data-unit": None,
                "rowspan": None, "colspan": None, "text": "",
            }

    def handle_endtag(self, tag: str) -> None:
        if tag in ("th", "td") and self._current_cell is not None and self._current_row is not None:
            self._current_row.append(self._current_cell)
            self._current_cell = None
        elif tag == "tr" and self._current_row is not None:
            self.rows.append(self._current_row)
            self._current_row = None

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            self._current_cell["text"] += data


def _parse_one_report(report_title: str, body: str) -> Report:
    org_match = re.search(r"^>\s*机构:\s*branch_num=([^;]+);\s*branch_short_name=(.+)$",
                          body, re.MULTILINE)
    time_match = re.search(r"^>\s*时期:\s*time_info\s*=\s*(\[.*?\])\s*$", body, re.MULTILINE)
    if not org_match or not time_match:
        raise ValueError(f"report `{report_title}` missing `> 机构:` or `> 时期:`; run md_lint first")
    org = OrgContext(branch_num=org_match.group(1).strip(),
                     branch_short_name=org_match.group(2).strip())
    time_info = json.loads(time_match.group(1))

    thead_match = re.search(r"<thead[^>]*>(.*?)</thead>", body, re.DOTALL | re.IGNORECASE)
    if not thead_match:
        raise ValueError(f"report `{report_title}` has no <thead>")
    parser = _TheadCellCollector()
    parser.feed(thead_match.group(1))
    headers_2d: list[list[Th]] = []
    for row in parser.rows:
        headers_2d.append([_cell_to_th(c) for c in row])

    tbody_match = re.search(r"<tbody[^>]*>(.*?)</tbody>", body, re.DOTALL | re.IGNORECASE)
    data_rows: list[dict] = []
    if tbody_match:
        for line_match in re.finditer(r"<tr[^>]*>(.*?)</tr>", tbody_match.group(1),
                                       re.DOTALL | re.IGNORECASE):
            tds = re.findall(r"<td[^>]*>(.*?)</td>", line_match.group(1), re.DOTALL | re.IGNORECASE)
            tds = [re.sub(r"<[^>]+>", "", t).strip() for t in tds]
            if tds:
                data_rows.append({"data_dt": tds[0], "raw_cells": tds[1:]})

    computed_specs = _parse_compute_block(body)
    header_computed_names = {
        c.text.strip("{}") for row in headers_2d for c in row if c.is_computed
    }
    computed_specs = [s for s in computed_specs if s.name in header_computed_names]

    return Report(
        title=report_title,
        org_context=org,
        time_info=time_info,
        headers=headers_2d,
        data_rows=data_rows,
        computed_specs=computed_specs,
    )


def _cell_to_th(cell: dict) -> Th:
    text = (cell.get("text") or "").strip()
    data_idx = cell.get("data-idx")
    data_unit = cell.get("data-unit")
    rowspan = cell.get("rowspan")
    colspan = cell.get("colspan")

    comp_match = COMPUTED_NAME_PATTERN.match(text)
    old_match = OLD_PLACEHOLDER_PATTERN.match(text)

    if old_match:
        # 旧式占位符：仍为 is_indicator；idx_id 与 text 均取自 {{}}（剥离大括号）
        return Th(text=old_match.group(1), is_indicator=True, is_computed=False,
                  idx_id=old_match.group(1),
                  data_unit=data_unit, rowspan=rowspan, colspan=colspan)
    if comp_match:
        return Th(text=text, is_indicator=False, is_computed=True,
                  data_unit=data_unit, rowspan=rowspan, colspan=colspan)
    if data_idx and IDX_ID_PATTERN.match(data_idx):
        return Th(text=text, is_indicator=True, is_computed=False,
                  idx_id=data_idx, data_unit=data_unit,
                  rowspan=rowspan, colspan=colspan)
    # 既无 data-idx 也无 {{}} 也无公式匹配 —— 类目标签单元格或占位
    return Th(text=text, is_indicator=False, is_computed=False,
              data_unit=data_unit, rowspan=rowspan, colspan=colspan)


def _parse_compute_block(body: str) -> list[ComputedSpec]:
    """解析 `> 计算:` 与可选 `.示例:` 行。"""
    out: list[ComputedSpec] = []
    compute_match = re.search(r"^>\s*计算:\n(.*?)(?=^>[^ \n]|\Z)", body, re.MULTILINE | re.DOTALL)
    if not compute_match:
        return out
    by_name: dict[str, ComputedSpec] = {}
    for raw in compute_match.group(1).splitlines():
        line = raw.lstrip("> ").strip()
        if not line:
            continue
        if ".示例:" in line:
            head, _, tail = line.partition(".示例:")
            name = head.strip()
            ex = _parse_example(tail.strip())
            if name in by_name and ex is not None:
                by_name[name].examples.append(ex)
            continue
        if "=" not in line:
            continue
        name, expr = (s.strip() for s in line.split("=", 1))
        by_name[name] = ComputedSpec(name=name, prompt=f"{name} = {expr}")
    return list(by_name.values())


def _parse_example(tail: str) -> dict | None:
    """将 `BAS_0263[current=1420, yoy_same=1200] -> 0.1833` 解析为 dict。"""
    m = re.match(r"^([A-Z]+_\d+)\s*\[(.*?)\]\s*->\s*(\S+)$", tail)
    if not m:
        return None
    inputs_str = m.group(2)
    inputs: dict[str, str] = {}
    for kv in re.findall(r"(\w+)\s*=\s*([^,]+)", inputs_str):
        inputs[kv[0].strip()] = kv[1].strip()
    return {"inputs": inputs, "expected": m.group(3)}
