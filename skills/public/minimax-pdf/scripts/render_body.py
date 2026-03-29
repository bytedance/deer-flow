#!/usr/bin/env python3
"""
render_body.py — Build the inner-page PDF from tokens.json + content.json.

Usage:
    python3 render_body.py --tokens tokens.json --content content.json --out body.pdf

Block types:
    h1 h2 h3           Headings (h1 adds a full-width accent rule below)
    body               Justified prose paragraph
    bullet             Bullet list item (• prefix)
    numbered           Auto-numbered list item (resets when interrupted)
    callout            Highlighted insight box with left accent bar
    table              Data table with accent header + alternating rows
    image              Inline image from file path
    figure             Image with auto-numbered "Figure N:" caption
    code               Monospace code block with accent left border
    math               Display math formula via matplotlib mathtext
    chart              Bar / line / pie chart rendered via matplotlib
    flowchart          Process diagram rendered via matplotlib
    bibliography       Numbered reference list
    divider            Full-width accent rule
    caption            Small muted text (e.g., under a figure)
    pagebreak          Force a new page
    spacer             Vertical whitespace (pt field, default 12)

Exit codes: 0 success, 1 bad args/missing file, 2 missing dep, 3 render error
"""

import argparse
import io
import json
import os
import sys
import importlib.util


# ── Dependency bootstrap ───────────────────────────────────────────────────────
def ensure_deps():
    missing = [p for p in ("reportlab", "pypdf")
               if importlib.util.find_spec(p) is None]
    if missing:
        import subprocess
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install",
             "--break-system-packages", "-q"] + missing
        )


ensure_deps()

from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame,
    Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, Flowable, KeepTogether,
    Preformatted, Image as RLImage,
)
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_JUSTIFY, TA_CENTER
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


# ── Font registration ──────────────────────────────────────────────────────────
def register_fonts(tokens: dict):
    """Register TTF fonts from token font_paths if present."""
    for name, fpath in tokens.get("font_paths", {}).items():
        if os.path.exists(fpath):
            try:
                pdfmetrics.registerFont(TTFont(name, fpath))
            except Exception:
                pass


# ══════════════════════════════════════════════════════════════════════════════
# Custom Flowables
# ══════════════════════════════════════════════════════════════════════════════

class CalloutBox(Flowable):
    """Highlighted insight box: coloured background + 4px left accent bar."""

    def __init__(self, text: str, style, accent: str, bg: str):
        super().__init__()
        self._para   = Paragraph(text, style)
        self._accent = HexColor(accent)
        self._bg     = HexColor(bg)

    def wrap(self, aw, ah):
        self._w = aw
        _, ph = self._para.wrap(aw - 36, ah)
        self._h = ph + 22
        return aw, self._h

    def draw(self):
        c = self.canv
        c.setFillColor(self._bg)
        c.roundRect(0, 0, self._w, self._h, 5, fill=1, stroke=0)
        c.setFillColor(self._accent)
        c.rect(0, 0, 4, self._h, fill=1, stroke=0)
        self._para.drawOn(c, 18, 11)


class BibliographyItem(Flowable):
    """Single hanging-indent bibliography entry rendered as [N] text."""

    LABEL_W = 28

    def __init__(self, ref_id: str, text: str, style, dark: str):
        super().__init__()
        self._id    = ref_id
        self._text  = text
        self._style = style
        self._dark  = HexColor(dark)

    def wrap(self, aw, ah):
        self._w    = aw
        self._para = Paragraph(self._text, self._style)
        _, ph      = self._para.wrap(aw - self.LABEL_W, ah)
        self._h    = ph + 4
        return aw, self._h

    def draw(self):
        c = self.canv
        c.setFillColor(self._dark)
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(0, self._h - 12, f"[{self._id}]")
        self._para.drawOn(c, self.LABEL_W, 2)


# ══════════════════════════════════════════════════════════════════════════════
# Page template (header + footer)
# ══════════════════════════════════════════════════════════════════════════════

class BeautifulDoc(BaseDocTemplate):
    def __init__(self, path: str, tokens: dict, **kw):
        self._t = tokens
        super().__init__(path, **kw)
        fr = Frame(
            self.leftMargin, self.bottomMargin,
            self.width, self.height, id="body",
        )
        tmpl = PageTemplate(id="main", frames=fr, onPage=self._decorate)
        self.addPageTemplates([tmpl])

    def _decorate(self, canv, doc):
        t   = self._t
        lm  = doc.leftMargin
        rm  = doc.rightMargin
        pw  = doc.pagesize[0]
        ph  = doc.pagesize[1]
        top = ph - doc.topMargin

        canv.saveState()

        # Header accent rule
        canv.setStrokeColor(HexColor(t["accent"]))
        canv.setLineWidth(1.5)
        canv.line(lm, top + 12, pw - rm, top + 12)

        # Header: title (left) + date (right)
        canv.setFillColor(HexColor(t["muted"]))
        canv.setFont(t["font_body_rl"], t["size_meta"])
        canv.drawString(lm, top + 16, t["title"].upper())
        canv.drawRightString(pw - rm, top + 16, t.get("date", ""))

        # Footer rule
        canv.setStrokeColor(HexColor("#DDDDDD"))
        canv.setLineWidth(0.5)
        canv.line(lm, doc.bottomMargin - 12, pw - rm, doc.bottomMargin - 12)

        # Footer: author (left) + page number (right)
        canv.setFillColor(HexColor(t["muted"]))
        canv.setFont(t["font_body_rl"], t["size_meta"])
        canv.drawString(lm, doc.bottomMargin - 22, t.get("author", ""))
        canv.drawRightString(pw - rm, doc.bottomMargin - 22, str(doc.page))

        canv.restoreState()


# ══════════════════════════════════════════════════════════════════════════════
# Style factory
# ══════════════════════════════════════════════════════════════════════════════

def make_styles(t: dict) -> dict:
    hf  = t["font_display_rl"]
    bf  = t["font_body_rl"]
    bfb = t["font_body_b_rl"]
    dk  = t["body_text"]
    d   = t["dark"]
    mu  = t["muted"]

    return {
        "h1": ParagraphStyle("H1",
            fontName=hf, fontSize=t["size_h1"],
            leading=t["size_h1"] * 1.3,
            textColor=HexColor(d),
            spaceBefore=t["section_gap"], spaceAfter=4,
        ),
        "h2": ParagraphStyle("H2",
            fontName=hf, fontSize=t["size_h2"],
            leading=t["size_h2"] * 1.4,
            textColor=HexColor(d),
            spaceBefore=18, spaceAfter=5,
        ),
        "h3": ParagraphStyle("H3",
            fontName=bfb, fontSize=t["size_h3"],
            leading=t["size_h3"] * 1.5,
            textColor=HexColor(d),
            spaceBefore=12, spaceAfter=3,
        ),
        "body": ParagraphStyle("Body",
            fontName=bf, fontSize=t["size_body"],
            leading=t["line_gap"],
            textColor=HexColor(dk),
            spaceAfter=t["para_gap"], alignment=TA_JUSTIFY,
        ),
        "bullet": ParagraphStyle("Bullet",
            fontName=bf, fontSize=t["size_body"],
            leading=t["line_gap"] - 1,
            textColor=HexColor(dk),
            spaceAfter=4, leftIndent=14,
        ),
        "numbered": ParagraphStyle("Numbered",
            fontName=bf, fontSize=t["size_body"],
            leading=t["line_gap"] - 1,
            textColor=HexColor(dk),
            spaceAfter=4, leftIndent=22, firstLineIndent=-22,
        ),
        "callout": ParagraphStyle("Callout",
            fontName=bfb, fontSize=t["size_body"] + 0.5, leading=16,
            textColor=HexColor(d),
        ),
        "caption": ParagraphStyle("Caption",
            fontName=bf, fontSize=t["size_caption"], leading=13,
            textColor=HexColor(mu), spaceAfter=6,
            alignment=TA_CENTER,
        ),
        "table_header": ParagraphStyle("TblH",
            fontName=bfb, fontSize=9.5, leading=13,
            textColor=HexColor("#FFFFFF"),
        ),
        "table_cell": ParagraphStyle("TblC",
            fontName=bf, fontSize=9.5, leading=13,
            textColor=HexColor(dk),
        ),
        "code": ParagraphStyle("Code",
            fontName="Courier", fontSize=8.5, leading=12.5,
            textColor=HexColor(dk),
        ),
        "code_lang": ParagraphStyle("CodeLang",
            fontName="Courier", fontSize=7, leading=10,
            textColor=HexColor(mu),
        ),
        "bib": ParagraphStyle("Bib",
            fontName=bf, fontSize=9, leading=14,
            textColor=HexColor(dk),
        ),
        "bib_title": ParagraphStyle("BibTitle",
            fontName=hf, fontSize=t["size_h2"],
            leading=t["size_h2"] * 1.4,
            textColor=HexColor(d),
            spaceBefore=t["section_gap"], spaceAfter=8,
        ),
        "math_fallback": ParagraphStyle("MathFb",
            fontName="Courier", fontSize=9, leading=13,
            textColor=HexColor(dk),
        ),
        "eq_label": ParagraphStyle("EqLabel",
            fontName="Helvetica", fontSize=9, leading=12,
            textColor=HexColor(mu),
        ),
    }


# ══════════════════════════════════════════════════════════════════════════════
# Shared helpers
# ══════════════════════════════════════════════════════════════════════════════

def _divider(accent: str) -> HRFlowable:
    return HRFlowable(
        width="100%", thickness=1.2,
        color=HexColor(accent),
        spaceBefore=14, spaceAfter=14,
    )


def _image_from_bytes(png_bytes: bytes, usable_w: float,
                      max_frac: float = 0.88) -> RLImage:
    """Create a scaled RLImage from PNG bytes, bounded to max_frac of usable_w."""
    img = RLImage(io.BytesIO(png_bytes))
    max_w = usable_w * max_frac
    if img.drawWidth > max_w:
        scale = max_w / img.drawWidth
        img.drawWidth  = max_w
        img.drawHeight = img.drawHeight * scale
    return img


# ══════════════════════════════════════════════════════════════════════════════
# PNG renderers (matplotlib)
# ══════════════════════════════════════════════════════════════════════════════

def _render_math_png(expr: str, dpi: int = 180) -> bytes | None:
    """
    Render a LaTeX math expression via matplotlib mathtext.
    No LaTeX binary required — uses matplotlib's built-in math parser.
    Supports: fractions (\\frac), integrals (\\int), sums (\\sum),
              Greek letters, sub/superscripts, etc.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig = plt.figure(figsize=(8, 1.2))
        fig.patch.set_facecolor("white")
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_axis_off()
        ax.set_facecolor("white")
        ax.text(0.5, 0.5, f"${expr}$",
                fontsize=16, ha="center", va="center",
                transform=ax.transAxes)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight",
                    facecolor="white", pad_inches=0.1)
        plt.close(fig)
        buf.seek(0)
        return buf.read()
    except Exception:
        return None


def _render_chart_png(item: dict, accent: str, dpi: int = 150) -> bytes | None:
    """
    Render bar / line / pie chart to PNG using matplotlib.

    Required fields:
        chart_type   "bar" | "line" | "pie"  (default "bar")
        labels       list of category strings
        datasets     list of {label?, values: list[number]}

    Optional fields:
        title        chart title
        x_label      X-axis label
        y_label      Y-axis label
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.colors as mcolors
        import colorsys
        import numpy as np

        chart_type = item.get("chart_type", "bar")
        title_text = item.get("title", "")
        labels     = item.get("labels", [])
        datasets   = item.get("datasets", [])

        # Derive a consistent palette from the document accent color
        r, g, b = mcolors.to_rgb(accent)
        h, s, v = colorsys.rgb_to_hsv(r, g, b)
        palette = [
            colorsys.hsv_to_rgb(
                (h + i * 0.13) % 1.0,
                max(0.35, s - i * 0.08),
                min(0.92, v + i * 0.04),
            )
            for i in range(max(len(datasets), 1))
        ]

        fig, ax = plt.subplots(figsize=(7, 3.6), dpi=dpi)
        fig.patch.set_facecolor("white")
        ax.set_facecolor("white")

        if chart_type == "bar":
            x = np.arange(len(labels))
            n = max(len(datasets), 1)
            width = 0.68 / n
            for i, ds in enumerate(datasets):
                offset = (i - (n - 1) / 2) * width
                ax.bar(x + offset, ds.get("values", []), width * 0.88,
                       label=ds.get("label", f"Series {i+1}"),
                       color=palette[i % len(palette)], edgecolor="none")
            ax.set_xticks(x)
            ax.set_xticklabels(labels, fontsize=8.5)
            ax.yaxis.grid(True, alpha=0.25, color="#CCCCCC", linewidth=0.7)
            ax.set_axisbelow(True)
            if item.get("x_label"):
                ax.set_xlabel(item["x_label"], fontsize=8.5)
            if item.get("y_label"):
                ax.set_ylabel(item["y_label"], fontsize=8.5)

        elif chart_type == "line":
            x = np.arange(len(labels))
            for i, ds in enumerate(datasets):
                ax.plot(x, ds.get("values", []), marker="o", markersize=3.5,
                        label=ds.get("label", f"Series {i+1}"),
                        color=palette[i % len(palette)], linewidth=1.8)
            ax.set_xticks(x)
            ax.set_xticklabels(labels, fontsize=8.5)
            ax.yaxis.grid(True, alpha=0.25, color="#CCCCCC", linewidth=0.7)
            ax.set_axisbelow(True)
            if item.get("x_label"):
                ax.set_xlabel(item["x_label"], fontsize=8.5)
            if item.get("y_label"):
                ax.set_ylabel(item["y_label"], fontsize=8.5)

        elif chart_type == "pie":
            vals   = datasets[0].get("values", []) if datasets else []
            colors = [
                colorsys.hsv_to_rgb(
                    (h + i * 0.11) % 1.0,
                    max(0.30, s - i * 0.06),
                    min(0.92, v + i * 0.03),
                )
                for i in range(len(vals))
            ]
            ax.pie(vals, labels=labels, colors=colors,
                   autopct="%1.1f%%", pctdistance=0.82,
                   wedgeprops=dict(edgecolor="white", linewidth=1.4),
                   textprops=dict(fontsize=8.5))

        # Shared styling
        for spine in ax.spines.values():
            spine.set_linewidth(0.5)
            spine.set_color("#CCCCCC")
        ax.tick_params(axis="both", length=0, labelsize=8.5)
        if title_text:
            ax.set_title(title_text, fontsize=10, pad=8,
                         color="#333333", fontweight="bold")
        if len(datasets) > 1 and chart_type != "pie":
            ax.legend(frameon=False, fontsize=8, loc="upper right")

        plt.tight_layout(pad=0.4)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight",
                    facecolor="white", pad_inches=0.06)
        plt.close(fig)
        buf.seek(0)
        return buf.read()
    except Exception:
        return None


def _render_flowchart_png(item: dict, accent: str, dark: str,
                           muted: str, dpi: int = 130) -> bytes | None:
    """
    Render a top-to-bottom flowchart using matplotlib patches and arrows.

    Node schema:  {id, label, shape?}
        shape: "rect" (default) | "diamond" | "oval" | "parallelogram"

    Edge schema:  {from, to, label?}
        Forward edges (to a later node) draw straight arrows.
        Back edges (to an earlier node) draw a curved arc to the right.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatch
        from matplotlib.patches import FancyBboxPatch
        import matplotlib.colors as mcolors

        nodes_list = item.get("nodes", [])
        edges      = item.get("edges", [])
        if not nodes_list:
            return None

        nodes = {n["id"]: n for n in nodes_list}
        order = {n["id"]: i for i, n in enumerate(nodes_list)}

        n_nodes = len(nodes_list)
        BOX_W   = 4.2
        BOX_H   = 0.58
        STEP_Y  = 1.25
        CX      = 5.0

        fig_h = max(3.5, n_nodes * STEP_Y + 0.8)
        fig, ax = plt.subplots(figsize=(6, fig_h), dpi=dpi)
        fig.patch.set_facecolor("white")
        ax.set_facecolor("white")
        ax.set_xlim(0, 10)
        ax.set_ylim(-0.6, n_nodes * STEP_Y + 0.2)
        ax.invert_yaxis()
        ax.axis("off")

        acc_rgb   = mcolors.to_rgb(accent)
        dark_rgb  = mcolors.to_rgb(dark)
        muted_rgb = mcolors.to_rgb(muted)

        # Node positions (cx, cy) — preserves input order
        pos = {nid: (CX, i * STEP_Y) for nid, i in order.items()}

        # ── Draw edges (behind nodes) ──────────────────────────────────────────
        for edge in edges:
            src, dst = edge.get("from"), edge.get("to")
            if src not in pos or dst not in pos:
                continue
            x1, y1 = pos[src]
            x2, y2 = pos[dst]
            lbl = edge.get("label", "")

            src_shape = nodes.get(src, {}).get("shape", "rect")
            dst_shape = nodes.get(dst, {}).get("shape", "rect")
            dy_src = BOX_H * (0.80 if src_shape == "diamond" else 0.50)
            dy_dst = BOX_H * (0.80 if dst_shape == "diamond" else 0.50)

            y_start = y1 + dy_src
            y_end   = y2 - dy_dst

            # Forward edge: straight; back-edge: curved arc
            conn = "arc3,rad=0.0" if y_end > y_start + 0.01 else "arc3,rad=0.42"

            ax.annotate("",
                xy=(x2, y_end), xytext=(x1, y_start),
                arrowprops=dict(
                    arrowstyle="-|>", color=muted_rgb,
                    lw=1.0, mutation_scale=10,
                    connectionstyle=conn,
                ),
            )
            if lbl:
                mid_x = (x1 + x2) / 2 + 0.28
                mid_y = (y_start + y_end) / 2
                ax.text(mid_x, mid_y, lbl, fontsize=7.5,
                        color=muted_rgb, ha="left", va="center")

        # ── Draw nodes (in front of edges) ────────────────────────────────────
        for nid, (cx, cy) in pos.items():
            node  = nodes[nid]
            shape = node.get("shape", "rect")
            label = node.get("label", nid)
            left  = cx - BOX_W / 2
            bot   = cy - BOX_H / 2

            if shape in ("oval", "terminal"):
                el = mpatch.Ellipse(
                    (cx, cy), BOX_W * 0.78, BOX_H * 1.15,
                    facecolor=acc_rgb, edgecolor=acc_rgb, linewidth=0,
                )
                ax.add_patch(el)
                ax.text(cx, cy, label, ha="center", va="center",
                        fontsize=8.5, fontweight="bold", color="white")

            elif shape == "diamond":
                d = BOX_W * 0.44
                diamond = plt.Polygon(
                    [(cx, cy - d * 0.72), (cx + d, cy),
                     (cx, cy + d * 0.72), (cx - d, cy)],
                    facecolor="#FFFCF0",
                    edgecolor=accent, linewidth=1.2,
                )
                ax.add_patch(diamond)
                ax.text(cx, cy, label, ha="center", va="center",
                        fontsize=8, color=dark_rgb)

            elif shape == "parallelogram":
                skew = 0.30
                para = plt.Polygon(
                    [(left + skew, bot), (left + BOX_W + skew, bot),
                     (left + BOX_W, bot + BOX_H), (left, bot + BOX_H)],
                    facecolor="white",
                    edgecolor=accent, linewidth=1.2,
                )
                ax.add_patch(para)
                ax.text(cx, cy, label, ha="center", va="center",
                        fontsize=8.5, color=dark_rgb)

            else:   # rect (default)
                rect = FancyBboxPatch(
                    (left, bot), BOX_W, BOX_H,
                    boxstyle="round,pad=0.04",
                    facecolor="white",
                    edgecolor=accent, linewidth=1.2,
                )
                ax.add_patch(rect)
                ax.text(cx, cy, label, ha="center", va="center",
                        fontsize=8.5, color=dark_rgb)

        plt.tight_layout(pad=0.2)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight",
                    facecolor="white", pad_inches=0.08)
        plt.close(fig)
        buf.seek(0)
        return buf.read()
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════════════
# Block renderers
#
# All functions share the same signature:
#   _add_XXX(story: list, item: dict, ctx: dict)
#
# ctx keys:
#   tokens    dict    design tokens from palette.py
#   styles    dict    ParagraphStyle objects from make_styles()
#   usable_w  float   usable page width in points
#   acc       str     accent hex color
#   acc_lt    str     light accent hex color
#   mu        str     muted hex color
#   dark      str     dark hex color
#   figure_n  int     auto-incrementing figure counter (mutable)
#   numbered_n int    auto-incrementing list counter (mutable)
# ══════════════════════════════════════════════════════════════════════════════

def _add_heading(story: list, item: dict, ctx: dict, level: int):
    key  = f"h{level}"
    para = Paragraph(item["text"], ctx["styles"][key])
    if level == 1:
        story.append(KeepTogether([para, _divider(ctx["acc"])]))
    else:
        story.append(para)


def _add_body(story: list, item: dict, ctx: dict):
    story.append(Paragraph(item["text"], ctx["styles"]["body"]))


def _add_bullet(story: list, item: dict, ctx: dict):
    story.append(Paragraph(
        f"\u2022\u2002{item['text']}", ctx["styles"]["bullet"]
    ))


def _add_numbered(story: list, item: dict, ctx: dict):
    ctx["numbered_n"] += 1
    story.append(Paragraph(
        f"{ctx['numbered_n']}.\u2002{item['text']}",
        ctx["styles"]["numbered"],
    ))


def _add_callout(story: list, item: dict, ctx: dict):
    story.append(Spacer(1, 8))
    story.append(CalloutBox(
        item["text"], ctx["styles"]["callout"], ctx["acc"], ctx["acc_lt"]
    ))
    story.append(Spacer(1, 8))


def _add_table(story: list, item: dict, ctx: dict):
    t        = ctx["tokens"]
    styles   = ctx["styles"]
    usable_w = ctx["usable_w"]
    acc      = ctx["acc"]
    acc_lt   = ctx["acc_lt"]

    headers = [Paragraph(h, styles["table_header"]) for h in item["headers"]]
    rows    = [
        [Paragraph(str(c), styles["table_cell"]) for c in row]
        for row in item.get("rows", [])
    ]
    n_cols = len(item["headers"])

    # Optional col_widths as fractions summing to 1.0
    if "col_widths" in item and len(item["col_widths"]) == n_cols:
        col_w = [usable_w * f for f in item["col_widths"]]
    else:
        col_w = [usable_w / n_cols] * n_cols

    tbl = Table([headers] + rows, colWidths=col_w)
    tbl.setStyle(TableStyle([
        ("BACKGROUND",     (0, 0), (-1,  0), HexColor(acc)),
        ("TEXTCOLOR",      (0, 0), (-1,  0), HexColor("#FFFFFF")),
        ("FONTNAME",       (0, 0), (-1,  0), t["font_body_b_rl"]),
        ("FONTSIZE",       (0, 0), (-1,  0), 9.5),
        ("TOPPADDING",     (0, 0), (-1,  0), 7),
        ("BOTTOMPADDING",  (0, 0), (-1,  0), 7),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [HexColor("#FFFFFF"), HexColor(acc_lt)]),
        ("FONTNAME",       (0, 1), (-1, -1), t["font_body_rl"]),
        ("FONTSIZE",       (0, 1), (-1, -1), 9.5),
        ("TOPPADDING",     (0, 1), (-1, -1), 6),
        ("BOTTOMPADDING",  (0, 1), (-1, -1), 6),
        ("LEFTPADDING",    (0, 0), (-1, -1), 10),
        ("RIGHTPADDING",   (0, 0), (-1, -1), 10),
        ("BOX",            (0, 0), (-1, -1), 0.5, HexColor("#CCCCCC")),
        ("LINEBELOW",      (0, 0), (-1,  0), 1.2, HexColor(acc)),
        ("TEXTCOLOR",      (0, 1), (-1, -1), HexColor(t["body_text"])),
        ("VALIGN",         (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(tbl)
    if item.get("caption"):
        story.append(Spacer(1, 4))
        story.append(Paragraph(item["caption"], styles["caption"]))
    story.append(Spacer(1, 12))


def _add_image(story: list, item: dict, ctx: dict):
    path = str(item.get("path", item.get("src", "")))
    if not os.path.exists(path):
        story.append(Paragraph(
            f"[Image not found: {path}]", ctx["styles"]["caption"]
        ))
        return
    try:
        img = RLImage(path)
        uw  = ctx["usable_w"]
        if img.drawWidth > uw:
            scale = uw / img.drawWidth
            img.drawWidth  = uw
            img.drawHeight = img.drawHeight * scale
        story.append(img)
    except Exception as e:
        story.append(Paragraph(f"[Image error: {e}]", ctx["styles"]["caption"]))
        return
    if item.get("caption"):
        story.append(Spacer(1, 4))
        story.append(Paragraph(item["caption"], ctx["styles"]["caption"]))
    story.append(Spacer(1, 8))


def _add_figure(story: list, item: dict, ctx: dict):
    """Like image but auto-numbers the caption as 'Figure N: ...'."""
    ctx["figure_n"] += 1
    raw_cap = item.get("caption", "")
    caption = f"Figure {ctx['figure_n']}: {raw_cap}" if raw_cap \
              else f"Figure {ctx['figure_n']}"
    _add_image(story, {**item, "caption": caption}, ctx)


def _add_code(story: list, item: dict, ctx: dict):
    acc    = ctx["acc"]
    acc_lt = ctx["acc_lt"]
    mu     = ctx["mu"]
    uw     = ctx["usable_w"]
    lang   = item.get("language", "")

    pre = Preformatted(item.get("text", ""), ctx["styles"]["code"])
    tbl = Table([[pre]], colWidths=[uw])
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), HexColor(acc_lt)),
        ("LINEBEFORE",    (0, 0), ( 0, -1), 3,   HexColor(acc)),
        ("BOX",           (0, 0), (-1, -1), 0.5, HexColor(mu)),
        ("LEFTPADDING",   (0, 0), (-1, -1), 14),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(Spacer(1, 6))
    if lang:
        story.append(Paragraph(lang.upper(), ctx["styles"]["code_lang"]))
    story.append(tbl)
    story.append(Spacer(1, 6))


def _add_math(story: list, item: dict, ctx: dict):
    """
    Display math block.

    Fields:
        text     LaTeX math expression (without enclosing $)
        label    optional equation label, e.g. "(1)" — displayed right-aligned
        caption  optional caption below the formula

    Example:
        {"type": "math", "text": "E = mc^2", "label": "(1)"}
        {"type": "math", "text": "\\\\int_0^\\\\infty e^{-x^2}\\\\,dx = \\\\frac{\\\\sqrt{\\\\pi}}{2}"}
    """
    acc    = ctx["acc"]
    acc_lt = ctx["acc_lt"]
    uw     = ctx["usable_w"]
    expr   = item.get("text", "").strip()
    label  = item.get("label", "").strip()

    png = _render_math_png(expr)

    if png is None:
        # Graceful text fallback if matplotlib unavailable
        story.append(Spacer(1, 6))
        pre = Preformatted(f"  {expr}", ctx["styles"]["math_fallback"])
        tbl = Table([[pre]], colWidths=[uw])
        tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), HexColor(acc_lt)),
            ("LEFTPADDING",   (0, 0), (-1, -1), 14),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 14),
            ("TOPPADDING",    (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(tbl)
        story.append(Spacer(1, 6))
        return

    img = _image_from_bytes(png, uw, max_frac=0.72)
    story.append(Spacer(1, 10))

    if label:
        label_w   = 44
        formula_w = uw - label_w
        lbl_para  = Paragraph(label, ctx["styles"]["eq_label"])
        row_tbl   = Table([[img, lbl_para]], colWidths=[formula_w, label_w])
        row_tbl.setStyle(TableStyle([
            ("ALIGN",  (0, 0), (0, 0), "CENTER"),
            ("ALIGN",  (1, 0), (1, 0), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story.append(row_tbl)
    else:
        row_tbl = Table([[img]], colWidths=[uw])
        row_tbl.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ]))
        story.append(row_tbl)

    if item.get("caption"):
        story.append(Spacer(1, 4))
        story.append(Paragraph(item["caption"], ctx["styles"]["caption"]))
    story.append(Spacer(1, 10))


def _add_chart(story: list, item: dict, ctx: dict):
    """
    Render a chart (bar / line / pie) via matplotlib.

    Fields:
        chart_type  "bar" | "line" | "pie"  (default "bar")
        title       chart title
        labels      list of category strings
        datasets    list of {label?, values: list[number]}
        x_label     X-axis label (bar/line)
        y_label     Y-axis label (bar/line)
        caption     caption text below chart
        figure      bool (default true) — prefix caption with "Figure N:"
    """
    uw  = ctx["usable_w"]
    png = _render_chart_png(item, ctx["acc"])

    if png is None:
        story.append(Paragraph(
            "[Chart: install matplotlib to render — pip install matplotlib]",
            ctx["styles"]["caption"],
        ))
        return

    img = _image_from_bytes(png, uw, max_frac=0.95)
    story.append(Spacer(1, 8))
    row_tbl = Table([[img]], colWidths=[uw])
    row_tbl.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER")]))
    story.append(row_tbl)

    raw_cap = item.get("caption", "")
    use_fig = item.get("figure", True)
    if raw_cap or use_fig:
        ctx["figure_n"] += 1
        prefix  = f"Figure {ctx['figure_n']}: " if use_fig else ""
        story.append(Spacer(1, 4))
        story.append(Paragraph(prefix + raw_cap, ctx["styles"]["caption"]))
    story.append(Spacer(1, 10))


def _add_flowchart(story: list, item: dict, ctx: dict):
    """
    Render a flowchart via matplotlib.

    Fields:
        nodes   list of {id, label, shape?}
                  shape: "rect" (default) | "diamond" | "oval" | "parallelogram"
        edges   list of {from, to, label?}
        caption caption below the diagram
        figure  bool (default true) — prefix caption with "Figure N:"
    """
    uw  = ctx["usable_w"]
    png = _render_flowchart_png(item, ctx["acc"], ctx["dark"], ctx["mu"])

    if png is None:
        story.append(Paragraph(
            "[Flowchart: install matplotlib to render — pip install matplotlib]",
            ctx["styles"]["caption"],
        ))
        return

    img = _image_from_bytes(png, uw, max_frac=0.78)
    story.append(Spacer(1, 8))
    row_tbl = Table([[img]], colWidths=[uw])
    row_tbl.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER")]))
    story.append(row_tbl)

    raw_cap = item.get("caption", "")
    use_fig = item.get("figure", True)
    if raw_cap or use_fig:
        ctx["figure_n"] += 1
        prefix  = f"Figure {ctx['figure_n']}: " if use_fig else ""
        story.append(Spacer(1, 4))
        story.append(Paragraph(prefix + raw_cap, ctx["styles"]["caption"]))
    story.append(Spacer(1, 10))


def _add_bibliography(story: list, item: dict, ctx: dict):
    """
    Numbered reference list with hanging indent.

    Fields:
        title   section heading (default "References"); set "" to suppress
        items   list of {id, text}

    Example:
        {"type": "bibliography",
         "items": [
           {"id": "1", "text": "Smith, J. (2023). Title. Journal, 10(2), 1–15."},
           {"id": "2", "text": "Doe, A. (2022). Another title. Publisher."}
         ]}
    """
    heading = item.get("title", "References")
    if heading:
        story.append(KeepTogether([
            Paragraph(heading, ctx["styles"]["bib_title"]),
            _divider(ctx["acc"]),
        ]))

    for ref in item.get("items", []):
        story.append(Spacer(1, 4))
        story.append(BibliographyItem(
            str(ref.get("id", "")),
            ref.get("text", ""),
            ctx["styles"]["bib"],
            ctx["dark"],
        ))


# ══════════════════════════════════════════════════════════════════════════════
# Story builder
# ══════════════════════════════════════════════════════════════════════════════

# Block types that break a numbered list sequence
_RESETS_NUMBERED = frozenset({
    "h1", "h2", "h3", "body", "bullet", "callout", "table",
    "image", "figure", "code", "math", "chart", "flowchart",
    "bibliography", "divider", "caption", "pagebreak", "spacer",
})


def build_story(content: list, tokens: dict, styles: dict) -> list:
    usable_w = A4[0] - tokens["margin_left"] - tokens["margin_right"]

    ctx: dict = {
        "tokens":     tokens,
        "styles":     styles,
        "usable_w":   usable_w,
        "acc":        tokens["accent"],
        "acc_lt":     tokens["accent_lt"],
        "mu":         tokens["muted"],
        "dark":       tokens["dark"],
        "figure_n":   0,
        "numbered_n": 0,
    }

    story: list = []

    for item in content:
        kind = item.get("type", "body")

        if kind in _RESETS_NUMBERED:
            ctx["numbered_n"] = 0

        if   kind == "h1":           _add_heading(story, item, ctx, 1)
        elif kind == "h2":           _add_heading(story, item, ctx, 2)
        elif kind == "h3":           _add_heading(story, item, ctx, 3)
        elif kind == "body":         _add_body(story, item, ctx)
        elif kind == "bullet":       _add_bullet(story, item, ctx)
        elif kind == "numbered":     _add_numbered(story, item, ctx)
        elif kind == "callout":      _add_callout(story, item, ctx)
        elif kind == "table":        _add_table(story, item, ctx)
        elif kind == "image":        _add_image(story, item, ctx)
        elif kind == "figure":       _add_figure(story, item, ctx)
        elif kind == "code":         _add_code(story, item, ctx)
        elif kind == "math":         _add_math(story, item, ctx)
        elif kind == "chart":        _add_chart(story, item, ctx)
        elif kind == "flowchart":    _add_flowchart(story, item, ctx)
        elif kind == "bibliography": _add_bibliography(story, item, ctx)
        elif kind == "divider":      story.append(_divider(ctx["acc"]))
        elif kind == "caption":
            story.append(Paragraph(item["text"], styles["caption"]))
        elif kind == "pagebreak":    story.append(PageBreak())
        elif kind == "spacer":       story.append(Spacer(1, item.get("pt", 12)))

    return story


# ══════════════════════════════════════════════════════════════════════════════
# Main build
# ══════════════════════════════════════════════════════════════════════════════

def build(tokens: dict, content: list, out_path: str) -> dict:
    register_fonts(tokens)
    styles = make_styles(tokens)

    doc = BeautifulDoc(
        out_path, tokens,
        pagesize=A4,
        leftMargin=tokens["margin_left"],
        rightMargin=tokens["margin_right"],
        topMargin=tokens["margin_top"],
        bottomMargin=tokens["margin_bottom"],
    )
    doc.build(build_story(content, tokens, styles))

    size = os.path.getsize(out_path)
    return {"status": "ok", "out": out_path, "size_kb": size // 1024}


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Render body PDF from tokens.json + content.json"
    )
    parser.add_argument("--tokens",  default="tokens.json")
    parser.add_argument("--content", default="content.json")
    parser.add_argument("--out",     default="body.pdf")
    args = parser.parse_args()

    for fpath in (args.tokens, args.content):
        if not os.path.exists(fpath):
            print(
                json.dumps({"status": "error",
                            "error": f"File not found: {fpath}"}),
                file=sys.stderr,
            )
            sys.exit(1)

    with open(args.tokens,  encoding="utf-8") as f:
        tokens = json.load(f)
    with open(args.content, encoding="utf-8") as f:
        content = json.load(f)

    try:
        result = build(tokens, content, args.out)
        print(json.dumps(result))
    except Exception as e:
        import traceback
        print(
            json.dumps({
                "status": "error",
                "error": str(e),
                "trace": traceback.format_exc(),
            }),
            file=sys.stderr,
        )
        sys.exit(3)


if __name__ == "__main__":
    main()
