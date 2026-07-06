"""Validate a chatbi-report MD sample against the spec's lint rules.

- Real-indicator columns are identified by the `data-idx` HTML attribute.
- Old-style `<th data-unit="...">{{BAS_0263}}</th>` (no `data-idx` but
  `{{}}` matches the idx_id regex) is accepted with a WARN; this format
  is retired — use `data-idx` attribute instead.
- Computed columns are `{{虚拟名}}` text only; an additional ERROR
  fires if such a column ALSO carries `data-idx`.
- Optional `> 描述:` blocks must use multi-line prompt format; lint warns
  if the block is present but empty or inline.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path


# 已识别的展示单位（其他值是 WARN 而非 ERROR）
RECOGNIZED_UNITS = {"元", "万元", "亿元", "%", "百分点", "个", "次"}
IDX_ID_PATTERN = re.compile(r"^[A-Z]+_\d+$")
COMPUTED_NAME_PATTERN = re.compile(r"^\{\{([^{}!]+)\}\}$")   # {{name}}，无内层花括号
OLD_PLACEHOLDER_PATTERN = re.compile(r"^\{\{([A-Z]+_\d+)\}\}$")
# data-period 格式：YYYY 或 YYYY-{Q1..Q4 | H1..H2 | M1..M12}（语法约束，不校验值范围）
PERIOD_PATTERN = re.compile(r"^\d{4}(-[QHM]\d)?$")


@dataclass
class LintError:
    code: str               # "F1", "F19", "CHATBI-DATAIDX", 等
    message: str
    location: str = ""      # "section 'X' > report 'Y'" 或 "<table> in report Z"


@dataclass
class LintWarning:
    code: str
    message: str
    location: str = ""


@dataclass
class LintReport:
    errors: list[LintError] = field(default_factory=list)
    warnings: list[LintWarning] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


class _TableCellCollector(HTMLParser):
    """从一个 table 中按行收集 `<th>` 属性字典 + 单元格文本。"""

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
                "tag": "th",
                "data-idx": a.get("data-idx"),
                "data-unit": a.get("data-unit"),
                "data-period": a.get("data-period"),
                "rowspan": a.get("rowspan"),
                "colspan": a.get("colspan"),
                "text": "",
            }
        elif tag == "td" and self._current_row is not None:
            self._current_cell = {"tag": "td", "text": ""}

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


# ---------- 公开 API ---------- #

def lint_file(path: str) -> LintReport:
    md = Path(path).read_text(encoding="utf-8")
    return lint_markdown(md)


def lint_markdown(md: str) -> LintReport:
    report = LintReport()
    if not md.lstrip().startswith("#"):
        report.errors.append(LintError("F1", "document must start with a `# <title>` line"))

    title_line, body = _split_title(md)
    sections = _split_sections(body)
    if not sections:
        report.errors.append(LintError("F1", "document has no `## 章节:` sections"))
        return report

    for section_title, section_body in sections:
        if not section_body.strip():
            report.errors.append(
                LintError("F1", f"section `{section_title}` has no content", location=section_title)
            )
            continue
        reports = _split_reports(section_body)
        if not reports:
            report.errors.append(
                LintError("F1", f"section `{section_title}` has no `### 报表:` blocks", location=section_title)
            )
            continue
        for report_title, report_body in reports:
            _lint_one_report(report_title, report_body, report, location=section_title)
    return report


# ---------- 内部 ---------- #

def _split_title(md: str) -> tuple[str, str]:
    lines = md.splitlines()
    title = ""
    i = 0
    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip()
        i = 1
    return title, "\n".join(lines[i:])


def _split_sections(body: str) -> list[tuple[str, str]]:
    chunks: list[tuple[str, str]] = []
    current_title = ""
    current_body: list[str] = []
    for line in body.splitlines():
        if line.startswith("## "):
            if current_title:
                chunks.append((current_title, "\n".join(current_body)))
            current_title = line[3:].strip()
            current_body = []
        else:
            current_body.append(line)
    if current_title:
        chunks.append((current_title, "\n".join(current_body)))
    return chunks


def _split_reports(section_body: str) -> list[tuple[str, str]]:
    chunks: list[tuple[str, str]] = []
    current_title = ""
    current_body: list[str] = []
    for line in section_body.splitlines():
        if line.startswith("### "):
            if current_title:
                chunks.append((current_title, "\n".join(current_body)))
            current_title = line[4:].strip()
            current_body = []
        else:
            current_body.append(line)
    if current_title:
        chunks.append((current_title, "\n".join(current_body)))
    return chunks


def _lint_one_report(report_title: str, body: str, report: LintReport, *, location: str) -> None:
    loc = f"{location} > 报表 `{report_title}`"
    time_match = re.search(r"^>\s*时期:\s*(.+)$", body, re.MULTILINE)

    _lint_org_block(body, report, location=loc)
    _lint_description_block(body, report, location=loc)

    if not time_match:
        report.errors.append(LintError("F19", "missing `> 时期:` block", location=loc))
    else:
        _lint_time_block(time_match.group(1), report, location=loc)

    compute_left, compute_right_idxs = _lint_compute_block(body, report, location=loc)

    tables = re.findall(r"<table[^>]*>.*?</table>", body, re.DOTALL | re.IGNORECASE)
    if not tables:
        report.errors.append(LintError("F1", "report has no `<table>` block", location=loc))
        return
    for t in tables:
        _lint_table(t, compute_left, compute_right_idxs, report, location=loc)


def _lint_org_block(body: str, report: LintReport, *, location: str) -> None:
    """校验 `> 机构:` 块：必须多行；每行必须有 branch_num= 与 branch_short_name=；branch_num 唯一。"""
    org_match = re.search(r"^>\s*机构:(.*)$", body, re.MULTILINE)
    if not org_match:
        report.errors.append(LintError("F19", "missing `> 机构:` block", location=location))
        return
    first_line_rest = org_match.group(1).strip()
    if first_line_rest != "":
        report.errors.append(LintError(
            "F1",
            "`> 机构:` must use multi-line format: "
            "`> 机构:` followed by indented `branch_num=X; branch_short_name=Y` lines",
            location=location,
        ))
        return

    start = org_match.end()
    entries: list[str] = []
    seen_nums: set[str] = set()
    for line in body[start:].splitlines():
        if not line:
            continue
        if not line.startswith(">"):
            break
        # 兄弟块（`> 时期:` 等）跳出：仅 0/1 空格缩进的 `> <非空>` 即视为新块
        if re.match(r"^>\s?\S", line) and not re.match(r"^>\s{2,}\S", line):
            break
        stripped = line.lstrip("> ").rstrip()
        if stripped:
            entries.append(stripped)

    if not entries:
        report.errors.append(LintError("F19", "`> 机构:` block is empty", location=location))
        return

    for entry in entries:
        if "branch_num=" not in entry or "branch_short_name=" not in entry:
            report.errors.append(LintError(
                "F1",
                f"`> 机构:` entry must contain both `branch_num=` and `branch_short_name=`: {entry!r}",
                location=location,
            ))
            continue
        m = re.match(r"^branch_num=([^;]+);", entry)
        if m:
            bn = m.group(1).strip()
            if bn in seen_nums:
                report.errors.append(LintError(
                    "F1",
                    f"duplicate branch_num={bn!r} in `> 机构:` block",
                    location=location,
                ))
            seen_nums.add(bn)


def _lint_description_block(body: str, report: LintReport, *, location: str) -> None:
    desc_match = re.search(r"^>\s*描述:(.*)$", body, re.MULTILINE)
    if not desc_match:
        return
    first_line_rest = desc_match.group(1).strip()
    if first_line_rest:
        report.warnings.append(LintWarning(
            "CHATBI-DESC-1",
            "`> 描述:` should use multi-line format: `> 描述:` followed by indented prompt lines",
            location=location,
        ))
        return

    start = desc_match.end()
    entries: list[str] = []
    for line in body[start:].splitlines():
        if not line:
            continue
        if not line.startswith(">"):
            break
        if re.match(r"^>\s?\S", line) and not re.match(r"^>\s{2,}\S", line):
            break
        stripped = line.lstrip("> ").strip()
        if stripped:
            entries.append(stripped)
    if not entries:
        report.warnings.append(LintWarning(
            "CHATBI-DESC-1",
            "`> 描述:` block is empty; no report description will be generated",
            location=location,
        ))
def _lint_time_block(line: str, report: LintReport, *, location: str) -> None:
    m = re.search(r"time_info\s*=\s*(\[.*?\])", line)
    if not m:
        report.errors.append(
            LintError("F1", "`> 时期:` block must contain `time_info=[...]` (JSON array)",
                      location=location)
        )
        return
    try:
        parsed = json.loads(m.group(1))
    except json.JSONDecodeError:
        report.errors.append(
            LintError("F1", "`> 时期:` time_info= must be a valid JSON array", location=location)
        )
        return
    if not isinstance(parsed, list) or not all(isinstance(x, str) for x in parsed):
        report.errors.append(
            LintError("F1", "`> 时期:` time_info= must be an array of strings", location=location)
        )


def _lint_compute_block(body: str, report: LintReport, *, location: str) -> tuple[set[str], set[str]]:
    """返回（左侧计算名集合，右侧引用的 idx_id 集合）。"""
    left_names: set[str] = set()
    referenced_idx: set[str] = set()
    # 行级扫描：找到 `> 计算:` 行后，吸收其后所有以 `>` 起头且至少缩进两格的行；
    # 遇到下一个顶格的 `> <label>:` 块（机构/时期/计算 等）或空行/非 `>` 行即停止。
    lines = body.splitlines()
    i = 0
    in_compute = False
    compute_lines: list[str] = []
    while i < len(lines):
        line = lines[i]
        if not in_compute:
            if re.match(r"^>\s*计算:\s*$", line):
                in_compute = True
            i += 1
            continue
        # 在 compute 块内部
        if not line.startswith(">"):
            break
        # 顶格 `> 字符` —— `>` 后跟 0/1 空格 + 非空 = 兄弟块（如 `> 机构:`）
        if re.match(r"^>\s?\S", line) and not re.match(r"^>\s{2,}\S", line):
            break
        compute_lines.append(line)
        i += 1

    for raw in compute_lines:
        line = raw.lstrip("> ").strip()
        if not line:
            continue
        if ".示例:" in line:
            continue
        if "=" not in line:
            report.errors.append(
                LintError("F1", f"`> 计算:` line missing `=`: {line!r}", location=location)
            )
            continue
        name_part, expr_part = line.split("=", 1)
        name_part = name_part.strip()
        expr_part = expr_part.strip()
        if not (1 <= len(name_part) <= 200 and 1 <= len(expr_part) <= 200):
            report.errors.append(
                LintError("F1", f"`> 计算:` line must be 1-200 chars on each side: {line!r}",
                          location=location)
            )
            continue
        left_names.add(name_part)
        for tok in re.findall(r"[A-Z][A-Z0-9_]*", expr_part):
            referenced_idx.add(tok)
    return left_names, referenced_idx


def _lint_table(
    table_md: str,
    compute_left: set[str],
    compute_right_idxs: set[str],
    report: LintReport,
    *,
    location: str,
) -> None:
    if "<thead" not in table_md.lower():
        report.errors.append(LintError("F1", "<table> missing <thead>", location=location))
    if "<tbody" not in table_md.lower():
        report.errors.append(LintError("F1", "<table> missing <tbody>", location=location))

    if re.search(r"^\s*\|", table_md, re.MULTILINE):
        report.warnings.append(LintWarning("STYLE", "use HTML <table>, not markdown pipe tables", location=location))

    parser = _TableCellCollector()
    try:
        parser.feed(table_md)
    except Exception as e:
        report.errors.append(LintError("F1", f"HTML parse error: {e}", location=location))
        return

    real_idx_ids_in_table: set[str] = set()
    computed_names_in_table: set[str] = set()
    leaves = [c for row in parser.rows for c in row if c.get("tag") == "th"]
    for cell in leaves:
        text = (cell.get("text") or "").strip()
        data_idx = cell.get("data-idx")
        data_unit = cell.get("data-unit")
        comp_match = COMPUTED_NAME_PATTERN.match(text)
        old_match = OLD_PLACEHOLDER_PATTERN.match(text)

        # Old-style placeholder is a subset of computed-name shape; check it FIRST
        # so `{{BAS_0263}}` falls to the WARN backward-compat branch, not orphan ERROR.
        if old_match:
            report.warnings.append(LintWarning(
                "CHATBI-OLD-PLACEHOLDER",
                f"old-style placeholder `{{{{{old_match.group(1)}}}}}` without data-idx; "
                f"this format is retired; use data-idx attribute instead",
                location=location,
            ))
            real_idx_ids_in_table.add(old_match.group(1))
            continue

        if comp_match:
            computed_names_in_table.add(comp_match.group(1))
            if data_idx:
                report.errors.append(LintError(
                    "CHATBI-COMPUTED-WITH-IDX",
                    f"computed column `{{{{{comp_match.group(1)}}}}}` must NOT carry data-idx "
                    f"(found data-idx={data_idx!r})",
                    location=location,
                ))
            continue

        if data_idx:
            if not IDX_ID_PATTERN.match(data_idx):
                report.errors.append(LintError(
                    "CHATBI-DATAIDX-FORMAT",
                    f"data-idx={data_idx!r} does not match `^[A-Z]+_\\d+$`",
                    location=location,
                ))
            else:
                real_idx_ids_in_table.add(data_idx)
            continue

        if not data_idx and not text:
            continue

        # colspan 或 rowspan > 1 的父级表头：天然没有 data-idx，不视作"真指标缺 data-idx"
        colspan_str = cell.get("colspan")
        rowspan_str = cell.get("rowspan")
        is_group_header = (
            (colspan_str and colspan_str.isdigit() and int(colspan_str) > 1)
            or (rowspan_str and rowspan_str.isdigit() and int(rowspan_str) > 1)
        )

        is_parent_label = not data_unit
        if not is_parent_label and not is_group_header:
            report.errors.append(LintError(
                "CHATBI-DATAIDX-MISSING",
                f"real-indicator <th> with text {text!r} is missing `data-idx` attribute",
                location=location,
            ))

        if data_unit and data_unit not in RECOGNIZED_UNITS:
            report.warnings.append(LintWarning(
                "CHATBI-DATAUNIT-CUSTOM",
                f"data-unit={data_unit!r} is not in the standard set; treated as a custom unit string",
                location=location,
            ))

    orphan = computed_names_in_table - compute_left
    for name in sorted(orphan):
        report.errors.append(LintError(
            "CHATBI-COMPUTED-ORPHAN",
            f"computed column `{{{{{name}}}}}` not declared in `> 计算:` block",
            location=location,
        ))

    unknown_refs = compute_right_idxs - real_idx_ids_in_table
    for idx in sorted(unknown_refs):
        report.errors.append(LintError(
            "CHATBI-COMPUTE-UNKNOWN-IDX",
            f"`> 计算:` references idx_id={idx!r} which is not in the header data-idx set",
            location=location,
        ))

    # data-period 多期校验：同 idx 多次出现 → 必填 + 唯一
    per_idx_cells: dict[str, list[dict]] = {}
    for cell in leaves:
        di = cell.get("data-idx")
        if not di or not IDX_ID_PATTERN.match(di):
            continue
        per_idx_cells.setdefault(di, []).append(cell)
    for idx, cells in per_idx_cells.items():
        if len(cells) <= 1:
            continue
        periods = [c.get("data-period") for c in cells]
        if any(p is None for p in periods):
            report.errors.append(LintError(
                "CHATBI-PERIOD-MISSING",
                f"data-idx={idx!r} appears {len(cells)} times across thead; each <th> must carry data-period",
                location=location,
            ))
        non_null = [p for p in periods if p is not None]
        if len(non_null) != len(set(non_null)):
            seen: set[str] = set()
            for p in non_null:
                if p in seen:
                    report.errors.append(LintError(
                        "CHATBI-PERIOD-DUPLICATE",
                        f"data-idx={idx!r} has duplicate data-period={p!r}",
                        location=location,
                    ))
                seen.add(p)

    # data-period 格式 + 孤立检查（计算列 {{name}} 也允许带 data-period）
    for cell in leaves:
        p = cell.get("data-period")
        if p is None:
            continue
        if not PERIOD_PATTERN.match(p):
            report.errors.append(LintError(
                "CHATBI-PERIOD-FORMAT",
                f"data-period={p!r} does not match `^\\d{{4}}(-[QHM]\\d)?$`",
                location=location,
            ))
        di = cell.get("data-idx")
        text = (cell.get("text") or "").strip()
        is_computed = bool(COMPUTED_NAME_PATTERN.match(text))
        if not is_computed and (not di or not IDX_ID_PATTERN.match(di)):
            report.errors.append(LintError(
                "CHATBI-PERIOD-ORPHAN",
                f"data-period={p!r} on <th> without valid data-idx (orphaned)",
                location=location,
            ))

    if len(computed_names_in_table) != len(set(computed_names_in_table)):
        report.warnings.append(LintWarning(
            "CHATBI-COMPUTED-DUP",
            "same computed column name appears multiple times across thead branches; consider unique names",
            location=location,
        ))


# ---------- CLI ---------- #

def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) != 1:
        print("usage: md_lint.py <path-to-md>", file=sys.stderr)
        return 2
    rep = lint_file(argv[0])
    for e in rep.errors:
        print(f"ERROR {e.code}: {e.message}  [{e.location}]", file=sys.stderr)
    for w in rep.warnings:
        print(f"WARN  {w.code}: {w.message}  [{w.location}]", file=sys.stderr)
    if rep.ok:
        print(f"OK: 0 errors, {len(rep.warnings)} warning(s)")
        return 0
    print(f"FAIL: {len(rep.errors)} error(s), {len(rep.warnings)} warning(s)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
