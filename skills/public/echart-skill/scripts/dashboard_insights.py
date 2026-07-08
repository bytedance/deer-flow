"""
Dashboard Insight Cards — Embed analytical insights into dashboards.

This module bridges the Insight Engine with the Dashboard Generator, enabling
rich insight cards to be displayed alongside charts. Each card presents a key
finding (trend, anomaly, ranking, etc.) with severity indicator and optional
drill-down action.

Usage:
    from scripts.dashboard_insights import generate_insight_cards

    # Generate insight cards HTML from an analyzed table
    cards_html = generate_insight_cards("sales", db_path="workspace.duckdb")

    # Inject into dashboard HTML template
    dashboard_html = dashboard_html.replace("{{INSIGHT_CARDS}}", cards_html)
"""

import html as html_mod
import json
import os
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from logging_config import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Insight Card HTML Templates
# ---------------------------------------------------------------------------

# Severity ordering for sorting (lower = more severe)
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}

# Severity → color/icon mapping
SEVERITY_STYLE = {
    "critical": {"color": "#dc2626", "bg": "#fef2f2", "icon": "🔴", "label": "严重"},
    "high":     {"color": "#d97706", "bg": "#fffbeb", "icon": "🟠", "label": "重要"},
    "medium":   {"color": "#2563eb", "bg": "#eff6ff", "icon": "🟡", "label": "中等"},
    "low":      {"color": "#6b7280", "bg": "#f3f4f6", "icon": "⚪", "label": "信息"},
    "info":     {"color": "#6b7280", "bg": "#f3f4f6", "icon": "ℹ️", "label": "信息"},
}

# Insight type → short label + icon
TYPE_META = {
    "trend":        ("📈", "趋势"),
    "anomaly":      ("⚠️", "异常"),
    "seasonality":  ("🔄", "周期"),
    "ranking":      ("🏆", "排名"),
    "correlation":  ("🔗", "相关"),
    "composition":  ("🥧", "构成"),
    "change":       ("📊", "变化"),
    "summary":      ("📋", "概览"),
    "outlier":      ("🔍", "离群"),
    "gap":          ("📉", "差距"),
}

# Card CSS (embedded in dashboard for standalone capability)
INSIGHT_CARD_CSS = """
<style>
.insights-panel {
    grid-column: 1 / -1;
    margin-bottom: 8px;
}
.insights-panel-header {
    display: flex; align-items: center; gap: 8px;
    margin-bottom: 12px; padding-bottom: 8px;
    border-bottom: 2px solid var(--border-color, #e5e7eb);
}
.insights-panel-header h2 {
    font-size: 1.1rem; font-weight: 600; margin: 0;
    display: flex; align-items: center; gap: 6px;
}
.insights-panel-header .insight-count {
    font-size: 0.8rem; color: var(--muted, #6b7280);
    background: var(--card, #f3f4f6); padding: 2px 8px;
    border-radius: 10px;
}
.insights-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: 10px;
}
.insight-card {
    display: flex; flex-direction: column;
    padding: 14px 16px; border-radius: 10px;
    border: 1px solid var(--border-color, #e5e7eb);
    background: var(--bg, #fff);
    cursor: pointer;
    transition: transform 0.15s, box-shadow 0.15s;
    position: relative; overflow: hidden;
}
.insight-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(0,0,0,0.08);
}
.insight-card::before {
    content: ''; position: absolute; left: 0; top: 0; bottom: 0;
    width: 4px;
}
.insight-card.severity-critical::before { background: #dc2626; }
.insight-card.severity-high::before     { background: #d97706; }
.insight-card.severity-medium::before   { background: #2563eb; }
.insight-card.severity-low::before      { background: #9ca3af; }
.insight-card.severity-info::before     { background: #9ca3af; }
.insight-card-header {
    display: flex; align-items: center; gap: 6px;
    margin-bottom: 6px;
}
.insight-card-header .type-badge {
    font-size: 0.7rem; padding: 2px 8px; border-radius: 10px;
    font-weight: 600; text-transform: uppercase;
}
.insight-card-header .severity-badge {
    font-size: 0.65rem; padding: 1px 6px; border-radius: 8px;
    font-weight: 500; margin-left: auto;
}
.insight-card-title {
    font-size: 0.9rem; font-weight: 600; margin: 4px 0;
    line-height: 1.3; color: var(--text, #1a1a2e);
}
.insight-card-desc {
    font-size: 0.8rem; color: var(--muted, #6b7280);
    line-height: 1.4; flex-grow: 1;
}
.insight-card-footer {
    display: flex; gap: 4px; margin-top: 8px; flex-wrap: wrap;
}
.insight-card-footer .tag {
    font-size: 0.65rem; padding: 1px 8px; border-radius: 8px;
    background: var(--card, #f3f4f6); color: var(--muted, #6b7280);
}
.insight-card .metric-value {
    font-size: 1.1rem; font-weight: 700;
    margin-top: 4px;
}
.insight-card .metric-value.up { color: #16a34a; }
.insight-card .metric-value.down { color: #dc2626; }
.insight-card .drill-hint {
    font-size: 0.7rem; color: var(--accent, #3b82f6);
    margin-top: 6px; display: none;
}
.insight-card:hover .drill-hint { display: block; }
</style>
"""


# ---------------------------------------------------------------------------
# Insight Card Generator
# ---------------------------------------------------------------------------

def generate_insight_cards(
    table: str,
    db_path: str = "workspace.duckdb",
    max_cards: int = 8,
    dimensions: Optional[list[str]] = None,
    date_column: Optional[str] = None,
    include_css: bool = True,
) -> str:
    """Generate HTML insight cards for a dashboard.

    Runs the Insight Engine on the given table and produces rich HTML
    cards suitable for embedding in a dashboard layout.

    Args:
        table: Table name to analyze.
        db_path: Path to DuckDB database.
        max_cards: Maximum number of cards to display.
        dimensions: Category columns to slice by.
        date_column: Date column for time-series analysis.
        include_css: Whether to include <style> block (set False if CSS is
                     already in the dashboard theme).

    Returns:
        HTML string with insight cards wrapped in an insights-panel div.
    """
    from scripts.insight_engine import InsightEngine

    engine = InsightEngine(db_path)

    # Run analysis
    insights = engine.analyze(
        table,
        dimensions=dimensions,
        date_column=date_column,
        top_n=5,
        include_summary=True,
    )

    if not insights:
        return _empty_insights_html()

    return _build_cards_panel(insights, max_cards, include_css)


def generate_insight_cards_from_insights(
    insights: list,
    max_cards: int = 8,
    include_css: bool = True,
) -> str:
    """Generate HTML insight cards from pre-computed Insight objects.

    Use this when you already have insights from a previous analysis call.

    Args:
        insights: List of Insight objects from InsightEngine.analyze().
        max_cards: Maximum number of cards to display.
        include_css: Whether to include <style> block.

    Returns:
        HTML string with insight cards.
    """
    if not insights:
        return _empty_insights_html()

    return _build_cards_panel(insights, max_cards, include_css)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _sort_insights(insights: list) -> list:
    """Sort insights by severity (critical first)."""
    return sorted(insights, key=lambda i: SEVERITY_ORDER.get(
        i.severity.value if i.severity else "info", 99))


def _build_cards_panel(insights: list, max_cards: int, include_css: bool) -> str:
    """Build the complete insight cards panel HTML.

    Shared by generate_insight_cards() and generate_insight_cards_from_insights().
    """
    insights = _sort_insights(insights)
    top_insights = insights[:max_cards]

    cards_html = "\n".join(
        _build_insight_card(ins, i) for i, ins in enumerate(top_insights)
    )

    severity_counts = _count_by_severity(top_insights)
    count_badges = " ".join(
        f'<span class="insight-count">{icon} {count}</span>'
        for icon, count in [("🔴", severity_counts["critical"]),
                           ("🟠", severity_counts["high"]),
                           ("🟡", severity_counts["medium"]),
                           ("⚪", severity_counts["low"] + severity_counts["info"])]
        if count > 0
    )

    panel_html = f"""<div class="insights-panel">
    <div class="insights-panel-header">
        <h2>💡 数据洞察 {count_badges}</h2>
    </div>
    <div class="insights-grid">
{cards_html}
    </div>
</div>"""

    if include_css:
        panel_html = INSIGHT_CARD_CSS + "\n" + panel_html

    return panel_html


def _build_insight_card(insight, index: int) -> str:
    """Build a single insight card HTML element.

    Args:
        insight: An Insight dataclass from insight_engine.
        index: Zero-based card index (used for JS interaction).

    Returns:
        HTML string for the card <div>.
    """
    sev = insight.severity.value if insight.severity else "info"
    style = SEVERITY_STYLE.get(sev, SEVERITY_STYLE["info"])
    type_meta = TYPE_META.get(
        insight.type.value if insight.type else "summary",
        ("📋", "概览"),
    )

    title = html_mod.escape(insight.title or "")
    desc_text = insight.description or ""
    if len(desc_text) > 150:
        desc = html_mod.escape(desc_text[:150].rsplit(" ", 1)[0]) + "…"
    else:
        desc = html_mod.escape(desc_text)

    # Build type badge
    type_badge = f'<span class="type-badge" style="background:{style["bg"]};color:{style["color"]}">{type_meta[0]} {type_meta[1]}</span>'
    severity_badge = f'<span class="severity-badge" style="background:{style["bg"]};color:{style["color"]}">{style["icon"]} {style["label"]}</span>'

    # Metric value if available
    metric_html = ""
    evidence = insight.evidence or {}
    if "change_pct" in evidence:
        val = evidence["change_pct"]
        direction = "up" if val > 0 else "down"
        metric_html = f'<div class="metric-value {direction}">{val:+.1f}%</div>'
    elif "yoy_change_pct" in evidence:
        val = evidence["yoy_change_pct"]
        direction = "up" if val > 0 else "down"
        metric_html = f'<div class="metric-value {direction}">{val:+.1f}%</div>'
    elif "value" in evidence:
        metric_html = f'<div class="metric-value">{html_mod.escape(str(evidence["value"]))}</div>'

    # Build footer tags: related columns + chart suggestion
    footer_spans = []
    if insight.related_columns:
        footer_spans.extend(
            f'<span class="tag">{html_mod.escape(c)}</span>'
            for c in insight.related_columns[:4]
        )
    if insight.suggested_chart:
        footer_spans.append(
            f'<span class="tag" style="background:var(--accent,#3b82f6);color:#fff">'
            f'📈 {html_mod.escape(insight.suggested_chart)}</span>'
        )
    tags_html = ""
    if footer_spans:
        tags_html = f'<div class="insight-card-footer">{"".join(footer_spans)}</div>'

    drill_hint = '<div class="drill-hint">🔍 点击深入分析 →</div>'

    # Serialize insight data for JS consumption — use data-attribute to avoid
    # XSS/HTML-injection risk from unescaped JSON in onclick attributes.
    insight_json = json.dumps(insight.to_dict(), ensure_ascii=False)
    insight_data_attr = html_mod.escape(insight_json)

    return f"""<div class="insight-card severity-{sev}" data-insight-id="{index}" data-insight="{insight_data_attr}" onclick="dashboard.focusInsight(this)">
    <div class="insight-card-header">
        {type_badge}
        {severity_badge}
    </div>
    <div class="insight-card-title">{title}</div>
    <div class="insight-card-desc">{desc}</div>
    {metric_html}
    {tags_html}
    {drill_hint}
</div>"""


def _empty_insights_html() -> str:
    """HTML for when no insights are available."""
    return """<div class="insights-panel">
    <div class="insights-panel-header">
        <h2>💡 数据洞察</h2>
    </div>
    <div style="padding: 24px; text-align: center; color: var(--muted, #6b7280);">
        📭 暂无显著洞察发现。导入更多数据或添加日期列以启用趋势分析。
    </div>
</div>"""


def _count_by_severity(insights: list) -> dict[str, int]:
    """Count insights by severity level."""
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    for ins in insights:
        sev = ins.severity.value if ins.severity else "info"
        counts[sev] = counts.get(sev, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    """CLI for insight card generation — useful for testing and scripting."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Dashboard Insight Cards — Generate insight cards HTML",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/dashboard_insights.py sales
  python scripts/dashboard_insights.py orders --db workspace.duckdb --max 6 --dimensions region,channel
  python scripts/dashboard_insights.py sales --json  # Output raw insight data as JSON
        """,
    )
    parser.add_argument("table", help="Table name to analyze")
    parser.add_argument("--db", default="workspace.duckdb", help="Database path")
    parser.add_argument("--max", type=int, default=8, help="Max insight cards")
    parser.add_argument("--dimensions", "-d", help="Comma-separated dimensions")
    parser.add_argument("--date-column", help="Date column for time-series analysis")
    parser.add_argument("--json", action="store_true", help="Output raw insight data as JSON")
    parser.add_argument("--output", "-o", help="Write HTML to file")

    args = parser.parse_args()

    dims = args.dimensions.split(",") if args.dimensions else None

    if args.json:
        from scripts.insight_engine import InsightEngine
        engine = InsightEngine(args.db)
        insights = engine.analyze(args.table, dimensions=dims, date_column=args.date_column)
        data = [i.to_dict() for i in insights]
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        html = generate_insight_cards(
            args.table,
            db_path=args.db,
            max_cards=args.max,
            dimensions=dims,
            date_column=args.date_column,
            include_css=True,
        )
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>Insights</title></head>"
                        f"<body style='font-family:system-ui;max-width:900px;margin:2rem auto'>{html}</body></html>")
            print(f"✅ Insight cards written to: {args.output}")
        else:
            print(html)


if __name__ == "__main__":
    main()
