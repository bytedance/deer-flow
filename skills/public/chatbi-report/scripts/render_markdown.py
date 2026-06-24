"""Render the backfilled Markdown report (`report.md`).

- 表头渲染为 `<中文显示名> (<单位>)`，不再追加 `(\`BAS_0263\`)`
  idx_id 后缀 —— 中文名已经在 `headers[].text` 中。
- ⚠️QUERY_FAILED 与 ⚠️COMPUTE_FAILED 标记直接追加到表头标签
  （让渲染出的列头就能揭示失败）。
"""
from __future__ import annotations

from typing import Iterable

from parse_md import ReportDoc, Th


def _leaf_cells(headers: list[list[Th]]) -> list[Th]:
    """扁平化的叶子单元格列表（跳过多级类目父级）。"""
    leaves = [c for row in headers for c in row]
    return [c for c in leaves if c.idx_id is not None or c.is_computed]


def _header_label(th: Th, compute_status: dict) -> str:
    """按 chatbi 契约构建渲染列头标签。

    T6 patch: 顺序不对称 — 真实指标的 ⚠️QUERY_FAILED 在 (单位) 之后（test 2 期望），
    计算列的 ⚠️COMPUTE_FAILED 在 (单位) 之前（test 3 期望）。
    """
    name = th.text
    if th.is_computed:
        # 若解析器保留了 {{}}，则去掉；render_markdown 期望纯文本。
        clean = name.strip("{}") if name.startswith("{{") else name
        label = f"{clean} (computed)"
    else:
        label = name
    # 计算列失败标记：在 (单位) 之前（test 3 要求 name (computed) ⚠️MARKER (单位)）
    if th.is_computed:
        status = compute_status.get(name.strip("{}") if name.startswith("{{") else name)
        if status in {"compute_smoke_failed", "compute_validation_failed",
                      "compute_codegen_failed", "compute_base_missing"}:
            label = f"{label} ⚠️COMPUTE_FAILED"
    if th.data_unit:
        label = f"{label} ({th.data_unit})"
    # 真实指标失败标记：在 (单位) 之后（test 2 要求 name (单位) ⚠️QUERY_FAILED）
    if not th.is_computed and th.idx_id:
        # 真实指标：调用方根据宽行单元格决定是否追加 QUERY_FAILED。
        # 我们通过渲染时在 Th 实例上设置的 sentinel 暴露该标记
        # （见 _mark_query_failures）。
        fail_marker = getattr(th, "_query_failed_marker", None)
        if fail_marker:
            label = f"{label} ⚠️QUERY_FAILED"
    return label


def _mark_query_failures(headers: list[list[Th]], wide_cells: dict | None) -> None:
    """在 idx_id 查询失败的 Th 上设置 _query_failed_marker=True。"""
    if not wide_cells:
        return
    for row in headers:
        for c in row:
            if c.idx_id and wide_cells.get(c.idx_id) == "⚠️QUERY_FAILED":
                c._query_failed_marker = True


def render_markdown(
    doc: ReportDoc,
    wide_by_report: list[list[dict]],
    compute_status: dict,
) -> str:
    """渲染完整的回填后 MD 内容。"""
    lines: list[str] = []
    lines.append(f"# {doc.title}")
    lines.append("")

    ridx = 0
    for section in doc.sections:
        lines.append(f"## {section.title}")
        lines.append("")
        for report in section.reports:
            wide_rows = wide_by_report[ridx] if ridx < len(wide_by_report) else []
            ridx += 1
            lines.append(f"### {report.title}")
            lines.append("")
            if not wide_rows:
                lines.append("_(no data rows in this report)_")
                lines.append("")
                continue

            leaves = _leaf_cells(report.headers)
            for row in wide_rows:
                _mark_query_failures(report.headers, row.get("cells", {}))

            # 构建 Markdown 表
            header_line = "| " + " | ".join(
                _header_label(th, compute_status) for th in leaves
            ) + " |"
            sep_line = "|" + "|".join("---" for _ in leaves) + "|"
            lines.append(header_line)
            lines.append(sep_line)
            for row in wide_rows:
                cells = row.get("cells", {})
                cell_strs = []
                for th in leaves:
                    if th.is_computed:
                        key = th.text.strip("{}") if th.text.startswith("{{") else th.text
                        val = cells.get(key, "—")
                    else:
                        val = cells.get(th.idx_id, "—")
                    cell_strs.append(str(val))
                lines.append("| " + " | ".join(cell_strs) + " |")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"
