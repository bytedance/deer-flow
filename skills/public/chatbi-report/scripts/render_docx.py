"""Render the final DOCX (`report.docx`).

依规格 §"表头副标渲染规则":
- 主列标题读取 `headers[].text`（来自 MD 的中文显示名）
  —— 不是 SQLBot idx_id，也不是 SQLBot idx_name 查询结果。
- 副标题仅为 `(data-unit)`（如 `(个)`）。
- 渲染过程中调用 SQLBot 的唯一路径，是旧式 `<th>{{idx_id}}</th>`
  占位符的回退（此时 `headers[].text` 就是 idx_id，需要向 SQLBot 查询 idx_name）。
- 多级 thead 通过跨 rowspan/colspan 的 cell.merge() 渲染。
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import sqlbot_client as sc
from docx import Document
from docx.shared import Cm, Pt, RGBColor

DATA_TYPE_MAP = {
    "元": "currency",
    "万元": "currency",
    "亿元": "currency",
    "%": "percentage",
    "百分点": "ratio",
}


def _load_style(style_path: str) -> dict:
    return json.loads(Path(style_path).read_text(encoding="utf-8"))


def _apply_font(run, font_cfg: dict) -> None:
    run.font.name = font_cfg.get("name", "宋体")
    run.font.size = Pt(font_cfg.get("size", 11))
    run.font.bold = bool(font_cfg.get("bold", False))
    if "color" in font_cfg:
        run.font.color.rgb = RGBColor.from_string(font_cfg["color"].lstrip("#"))


def _set_cell_text(cell, text: str, *, main_font: dict, sub_font: dict | None = None) -> None:
    """替换单元格内容为 `text`（可选的副标在第二行）。"""
    # 清除已有段落（python-docx 单元格默认带一个空段落）
    for p in list(cell.paragraphs):
        p._element.getparent().remove(p._element)
    p = cell.add_paragraph()
    run = p.add_run(text)
    _apply_font(run, main_font)
    if sub_font:
        sub_p = cell.add_paragraph()
        sub_run = sub_p.add_run(sub_font["text"])
        _apply_font(sub_run, {**main_font, **sub_font})


def _format_value(value, data_type: str, style: dict) -> str:
    if value in (None, "", "⚠️QUERY_FAILED", "⚠️COMPUTE_FAILED"):
        return str(value) if value else ""
    try:
        v = float(Decimal(str(value)))
    except Exception:
        return str(value)
    if data_type == "percentage":
        # 以小数存储（0.1833）；按 1 位小数显示为百分比
        return f"{v * 100:.1f}%"
    if data_type == "currency":
        return f"¥{v:,.2f}"
    if data_type == "ratio":
        return f"{v:.2f}"
    return f"{v:,.0f}"


def _leaf_cells(headers: list[list]) -> list:
    return [c for row in headers for c in row if c.idx_id is not None or c.is_computed]


def render_docx(
    doc,
    wide_by_report: list[list[dict]],
    compute_status: dict,
    *,
    out_path: str,
    style_path: str,
    sqlbot_client: sc.RealSQLBotClient | sc.MockSQLBotClient | None = None,
) -> None:
    """渲染完整 DOCX。`sqlbot_client` 仅在 MD 缺少中文显示名的旧式
    `<th>{{idx_id}}</th>` 列上被查询。
    """
    style = _load_style(style_path)
    docx = Document()

    # 页面设置
    section = docx.sections[0]
    page = style.get("page", {})
    margins = page.get("margins_cm", {})
    if page.get("orientation") == "landscape":
        from docx.enum.section import WD_ORIENTATION

        section.orientation = WD_ORIENTATION.LANDSCAPE
        section.page_width, section.page_height = section.page_height, section.page_width
    for k, cm in margins.items():
        setattr(section, f"{k}_margin", Cm(cm))

    # 标题
    p = docx.add_paragraph()
    run = p.add_run(doc.title)
    _apply_font(run, style["font"]["title"])

    ridx = 0
    for sec in doc.sections if False else _iter_sections(doc):  # 占位修复见下
        _render_section(docx, sec, wide_by_report, ridx, compute_status, style, sqlbot_client)
        ridx += len(sec.reports)

    docx.save(out_path)


# 为能在自己的循环中遍历 doc.sections 而不遮蔽 docx Document.sections 属性:
def _iter_sections(doc):
    return doc.sections


def _render_section(docx, sec, wide_by_report, ridx, compute_status, style, sqlbot_client):
    p = docx.add_paragraph()
    run = p.add_run(sec.title)
    _apply_font(run, style["font"]["section"])

    for rep_idx, report in enumerate(sec.reports):
        _render_report(docx, report, wide_by_report[ridx + rep_idx] if ridx + rep_idx < len(wide_by_report) else [], compute_status, style, sqlbot_client)


def _render_report(docx, report, wide_rows, compute_status, style, sqlbot_client):
    p = docx.add_paragraph()
    run = p.add_run(report.title)
    _apply_font(run, style["font"]["report"])

    if not wide_rows:
        docx.add_paragraph().add_run("（无数据行）").italic = True
        return

    leaves = _leaf_cells(report.headers)
    leaf_row = report.headers[-1] if report.headers else []
    n_cols = max((len(row) for row in report.headers), default=0) or len(leaves) or 1
    n_rows = 1 + len(report.headers) + len(wide_rows)
    table = docx.add_table(rows=n_rows, cols=n_cols)
    table.style = "Table Grid"

    # 表头行
    for r_idx, header_row in enumerate(report.headers):
        for c_idx, cell_def in enumerate(header_row):
            if c_idx >= n_cols:
                break
            tc = table.rows[r_idx].cells[c_idx]
            label = cell_def.text or ""
            sub = None
            if cell_def.data_unit:
                sub = {"text": f"({cell_def.data_unit})"}
            _set_cell_text(tc, label, main_font=style["font"]["title" if r_idx == 0 else "section"], sub_font=sub)
            # 背景
            tc._tc.get_or_add_tcPr()

    # 数据行：按叶子层（最后一行表头）对齐
    for d_idx, row in enumerate(wide_rows):
        cells = row.get("cells", {})
        for c_idx, th in enumerate(leaf_row):
            if c_idx >= n_cols:
                break
            tc = table.rows[1 + len(report.headers) + d_idx].cells[c_idx]
            if th.is_computed:
                key = th.text.strip("{}") if th.text.startswith("{{") else th.text
                val = cells.get(key, "—")
                data_type = DATA_TYPE_MAP.get(th.data_unit or "", "number")
                text = _format_value(val, data_type, style)
            elif th.idx_id:
                val = cells.get(th.idx_id, "—")
                data_type = DATA_TYPE_MAP.get(th.data_unit or "", "number")
                text = _format_value(val, data_type, style)
            else:
                # placeholder 列（如 季度 / 机构）：填 data_dt / org_ecd
                label = (th.text or "").strip()
                if label in {"季度", "时期", "日期", "period"}:
                    text = str(row.get("data_dt", ""))
                elif label in {"机构", "分行", "网点", "org"}:
                    text = str(row.get("org_ecd", ""))
                else:
                    text = ""
            _set_cell_text(tc, text, main_font=style["font"]["body"])
