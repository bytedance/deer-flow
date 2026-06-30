"""ai-report MD lint: per-section error reporting (新写, 借鉴 chatbi-report 检查项)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

VALID_UNITS = {"元", "万元", "亿元", "%"}


@dataclass
class LintIssue:
    section_index: int
    report_index: int
    code: str
    message: str


@dataclass
class LintReport:
    errors: list[LintIssue] = field(default_factory=list)
    warnings: list[LintIssue] = field(default_factory=list)
    by_section: dict[str, list[LintIssue]] = field(default_factory=dict)

    def add(self, issue: LintIssue) -> None:
        (self.errors if issue.code.startswith(("missing_", "invalid_")) else self.warnings).append(issue)
        key = f"s{issue.section_index}_r{issue.report_index}"
        self.by_section.setdefault(key, []).append(issue)


def lint_markdown(md: str) -> LintReport:
    """Lint a multi-section MD; per-section error attribution."""
    rep = LintReport()
    _, body = _split_title(md)
    for s_idx, (s_title, s_body) in enumerate(_split_sections(body)):
        for r_idx, (r_title, r_body) in enumerate(_split_reports(s_body)):
            _lint_one_report(s_idx, r_idx, r_title, r_body, rep)
    return rep


def _split_title(md: str) -> tuple[str, str]:
    lines = md.splitlines()
    if lines and lines[0].startswith("# "):
        return lines[0][2:].strip(), "\n".join(lines[1:])
    return "", md


def _split_sections(body: str) -> list[tuple[str, str]]:
    out, cur_title, cur_body = [], "", []
    for line in body.splitlines():
        if line.startswith("## "):
            if cur_title or any(s.strip() for s in cur_body):
                out.append((cur_title, "\n".join(cur_body)))
            cur_title, cur_body = line[3:].strip(), []
        else:
            cur_body.append(line)
    if cur_title or any(s.strip() for s in cur_body):
        out.append((cur_title, "\n".join(cur_body)))
    return out


def _split_reports(section_body: str) -> list[tuple[str, str]]:
    out, cur_title, cur_body = [], "", []
    for line in section_body.splitlines():
        if line.startswith("### "):
            if cur_title or any(s.strip() for s in cur_body):
                out.append((cur_title, "\n".join(cur_body)))
            cur_title, cur_body = line[4:].strip(), []
        else:
            cur_body.append(line)
    if cur_title or any(s.strip() for s in cur_body):
        out.append((cur_title, "\n".join(cur_body)))
    return out


def _lint_one_report(s_idx: int, r_idx: int, title: str, body: str, rep: LintReport) -> None:
    if not re.search(r"^>\s*时期:\s*time_info\s*=", body, re.MULTILINE):
        rep.add(LintIssue(s_idx, r_idx, "missing_time_info", f"report `{title}` missing `> 时期:`"))
    if not re.search(r"<thead[^>]*>", body, re.IGNORECASE):
        rep.add(LintIssue(s_idx, r_idx, "missing_thead", f"report `{title}` missing <thead>"))
    for m in re.finditer(r'<th[^>]*data-unit="([^"]+)"', body):
        unit = m.group(1)
        if unit not in VALID_UNITS:
            rep.add(LintIssue(s_idx, r_idx, "invalid_data_unit",
                              f"report `{title}` has invalid data-unit `{unit}`; valid: {VALID_UNITS}"))
    for m in re.finditer(r'<th[^>]*/?>', body):
        tag = m.group(0)
        if "data-idx=" not in tag and "data-computed" not in tag and "{{" not in tag:
            rep.add(LintIssue(s_idx, r_idx, "th_missing_idx",
                              f"report `{title}` has <th> without data-idx"))