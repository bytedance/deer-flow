"""
Dashboard Generator Script.

Reads a dashboard spec JSON, queries data via DuckDB, and generates a
self-contained interactive HTML dashboard using Apache ECharts.
"""

import argparse
import json
import os
import subprocess
import sys

try:
    import duckdb
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "duckdb", "-q"], check=True)
    import duckdb

try:
    import openpyxl  # noqa: F401
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "openpyxl", "-q"], check=True)

# ---------------------------------------------------------------------------
# Theme definitions
# ---------------------------------------------------------------------------

THEMES: dict[str, dict[str, str]] = {
    "light": {
        "bg": "#ffffff",
        "card_bg": "#ffffff",
        "text": "#333333",
        "text_secondary": "#666666",
        "border": "#e0e0e0",
        "kpi_bg": "#f8f9fa",
        "header_bg": "#ffffff",
        "shadow": "0 2px 8px rgba(0,0,0,0.08)",
        "palette": ('["#5470c6","#91cc75","#fac858","#ee6666","#73c0de","#3ba272","#fc8452","#9a60b4"]'),
    },
    "dark": {
        "bg": "#1a1a2e",
        "card_bg": "#16213e",
        "text": "#e0e0e0",
        "text_secondary": "#a0a0a0",
        "border": "#2a2a4a",
        "kpi_bg": "#0f3460",
        "header_bg": "#16213e",
        "shadow": "0 2px 8px rgba(0,0,0,0.3)",
        "palette": ('["#5470c6","#91cc75","#fac858","#ee6666","#73c0de","#3ba272","#fc8452","#9a60b4"]'),
    },
    "corporate": {
        "bg": "#f0f4f8",
        "card_bg": "#ffffff",
        "text": "#2c3e50",
        "text_secondary": "#5a6c7d",
        "border": "#d0d9e1",
        "kpi_bg": "#e8eef4",
        "header_bg": "#2c3e50",
        "shadow": "0 2px 6px rgba(44,62,80,0.1)",
        "palette": ('["#2980b9","#27ae60","#f39c12","#e74c3c","#8e44ad","#1abc9c","#d35400","#2c3e50"]'),
    },
}

# ---------------------------------------------------------------------------
# ECharts type mapping
# ---------------------------------------------------------------------------

ECHART_TYPE_MAP: dict[str, str] = {
    "line": "line",
    "area": "line",
    "bar": "bar",
    "column": "bar",
    "pie": "pie",
    "donut": "pie",
    "scatter": "scatter",
    "treemap": "treemap",
    "radar": "radar",
    "funnel": "funnel",
}


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------


def load_data(
    con: duckdb.DuckDBPyConnection,
    data_source: dict,
) -> list[dict]:
    """Load data from files using DuckDB and return as list of dicts."""
    files = data_source.get("files", [])
    sql = data_source.get("sql", "")

    if not sql:
        return []

    # Register files as views
    for f in files:
        ext = os.path.splitext(f)[1].lower()
        base = os.path.splitext(os.path.basename(f))[0]
        if ext == ".csv":
            con.execute(f"CREATE OR REPLACE VIEW \"{base}\" AS SELECT * FROM read_csv_auto('{f}')")
        elif ext in (".xlsx", ".xls"):
            con.execute("INSTALL spatial; LOAD spatial;")
            wb = __import__("openpyxl").load_workbook(f, read_only=True)
            sheets = wb.sheetnames
            wb.close()
            for sheet in sheets:
                con.execute(f"CREATE OR REPLACE VIEW \"{sheet}\" AS SELECT * FROM st_read('{f}', layer = '{sheet}', open_options = ['HEADERS=FORCE', 'FIELD_TYPES=AUTO'])")

    result = con.execute(sql)
    columns = [desc[0] for desc in result.description]
    rows = result.fetchall()
    return [dict(zip(columns, row)) for row in rows]


def load_kpi_value(
    con: duckdb.DuckDBPyConnection,
    kpi_spec: dict,
) -> float | int | None:
    """Execute KPI value SQL and return the scalar result."""
    sql = kpi_spec.get("value_sql", "")
    if not sql:
        return None
    try:
        row = con.execute(sql).fetchone()
        return row[0] if row else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# HTML rendering helpers
# ---------------------------------------------------------------------------


def format_kpi_value(value: float | int | None, fmt: str) -> str:
    """Format a KPI value based on the format type."""
    if value is None:
        return "N/A"
    if fmt == "currency":
        return f"${value:,.2f}"
    if fmt == "percent":
        return f"{value:.1f}%"
    # number
    if isinstance(value, float):
        return f"{value:,.1f}"
    return f"{value:,}"


def render_kpi_card(kpi: dict, value: float | int | None, theme: dict) -> str:
    """Render a single KPI card as HTML."""
    label = kpi.get("label", "KPI")
    fmt = kpi.get("format", "number")
    display = format_kpi_value(value, fmt)
    return f"""<div class="kpi-card" style="background:{theme["kpi_bg"]};border:1px solid {theme["border"]};box-shadow:{theme["shadow"]};border-radius:8px;padding:20px;text-align:center;">
      <div style="color:{theme["text_secondary"]};font-size:14px;margin-bottom:8px;">{label}</div>
      <div style="color:{theme["text"]};font-size:28px;font-weight:700;">{display}</div>
    </div>"""


def render_echarts_option(
    chart_spec: dict,
    data: list[dict],
    theme: dict,
) -> str:
    """Build an ECharts option JSON string for a chart spec."""
    chart_type = chart_spec.get("type", "line")
    x_field = chart_spec.get("x", "")
    y_fields = chart_spec.get("y", [])
    title = chart_spec.get("title", "")

    echarts_type = ECHART_TYPE_MAP.get(chart_type, "line")

    if chart_type in ("pie", "donut"):
        # Aggregate data by x field
        agg: dict[str, float] = {}
        for row in data:
            key = str(row.get(x_field, ""))
            val = 0
            for yf in y_fields:
                v = row.get(yf, 0)
                val += float(v) if v is not None else 0
            agg[key] = agg.get(key, 0) + val

        pie_data = [{"name": k, "value": v} for k, v in agg.items()]
        radius = '["40%","70%"]' if chart_type == "donut" else '"70%"'
        return json.dumps(
            {
                "title": {"text": title, "textStyle": {"color": theme["text"]}},
                "tooltip": {"trigger": "item"},
                "color": json.loads(theme["palette"]),
                "series": [
                    {
                        "type": "pie",
                        "radius": json.loads(radius),
                        "data": pie_data,
                        "emphasis": {"itemStyle": {"shadowBlur": 10, "shadowOffsetX": 0, "shadowColor": "rgba(0,0,0,0.5)"}},
                    }
                ],
            }
        )

    # Cartesian charts (line, area, bar, column, scatter)
    # Collect unique x values
    x_values: list[str] = []
    seen_x: set[str] = set()
    for row in data:
        xv = str(row.get(x_field, ""))
        if xv not in seen_x:
            x_values.append(xv)
            seen_x.add(xv)

    series_list = []
    for yf in y_fields:
        y_values = []
        for xv in x_values:
            matched = [r for r in data if str(r.get(x_field, "")) == xv]
            if matched:
                y_values.append(matched[0].get(yf, 0))
            else:
                y_values.append(0)

        s: dict = {
            "name": yf,
            "type": echarts_type,
            "data": [float(v) if v is not None else 0 for v in y_values],
        }
        if chart_type == "area":
            s["areaStyle"] = {}
        if chart_type == "bar":
            s["type"] = "bar"
            s["orient"] = "horizontal" if chart_type == "bar" else None
        series_list.append(s)

    option: dict = {
        "title": {"text": title, "textStyle": {"color": theme["text"]}},
        "tooltip": {"trigger": "axis"},
        "color": json.loads(theme["palette"]),
        "xAxis": {"type": "category", "data": x_values, "axisLabel": {"color": theme["text_secondary"]}},
        "yAxis": {"type": "value", "axisLabel": {"color": theme["text_secondary"]}},
        "series": series_list,
    }

    return json.dumps(option)


def render_filter_html(filters: list[dict], data: list[dict], theme: dict) -> str:
    """Render filter controls as HTML."""
    if not filters:
        return ""

    parts = ['<div class="filter-bar" style="display:flex;gap:16px;margin-bottom:20px;flex-wrap:wrap;">']
    for f in filters:
        field = f["field"]
        label = f.get("label", field)
        ftype = f.get("type", "select")

        if ftype == "select":
            unique_vals = sorted(set(str(row.get(field, "")) for row in data))
            options_html = "<option value=''>All</option>"
            for v in unique_vals:
                options_html += f"<option value='{v}'>{v}</option>"
            parts.append(
                f"<div style='display:flex;align-items:center;gap:8px;'>"
                f"<label style='color:{theme['text_secondary']};font-size:13px;'>{label}:</label>"
                f"<select data-filter-field='{field}' onchange='applyFilters()' "
                f"style='padding:6px 12px;border:1px solid {theme['border']};"
                f"border-radius:4px;background:{theme['card_bg']};color:{theme['text']};'>"
                f"{options_html}</select></div>"
            )
        elif ftype == "date_range":
            parts.append(
                f"<div style='display:flex;align-items:center;gap:8px;'>"
                f"<label style='color:{theme['text_secondary']};font-size:13px;'>{label}:</label>"
                f"<input type='date' data-filter-field='{field}' data-filter-role='start' "
                f"onchange='applyFilters()' style='padding:6px 12px;border:1px solid {theme['border']};"
                f"border-radius:4px;background:{theme['card_bg']};color:{theme['text']};'>"
                f"<span style='color:{theme['text_secondary']}'>-</span>"
                f"<input type='date' data-filter-field='{field}' data-filter-role='end' "
                f"onchange='applyFilters()' style='padding:6px 12px;border:1px solid {theme['border']};"
                f"border-radius:4px;background:{theme['card_bg']};color:{theme['text']};'>"
                f"</div>"
            )

    parts.append("</div>")
    return "\n".join(parts)


def render_chart_grid_html(
    charts: list[dict],
    data: list[dict],
    theme: dict,
    layout: str,
) -> str:
    """Render the chart grid area as HTML."""
    if layout == "tabs":
        return _render_tabs_layout(charts, data, theme)

    # Grid layout (default)
    parts = ['<div class="chart-grid" style="display:grid;grid-template-columns:repeat(12,1fr);gap:16px;">']

    # Group charts by row
    rows: dict[int, list[dict]] = {}
    for c in charts:
        pos = c.get("position", {"row": 1, "col": 1, "width": 12})
        row_num = pos.get("row", 1)
        rows.setdefault(row_num, []).append(c)

    for row_num in sorted(rows.keys()):
        for c in rows[row_num]:
            cid = c.get("id", f"chart-{row_num}")
            pos = c.get("position", {"row": 1, "col": 1, "width": 12})
            width = min(pos.get("width", 12), 12)
            chart_html = _render_chart_card(cid, c, data, theme, width)
            parts.append(chart_html)

    parts.append("</div>")
    return "\n".join(parts)


def _render_chart_card(
    cid: str,
    chart_spec: dict,
    data: list[dict],
    theme: dict,
    width: int,
) -> str:
    """Render a single chart card."""
    chart_type = chart_spec.get("type", "line")

    if chart_type == "table":
        return _render_table_card(cid, chart_spec, data, theme, width)

    option_json = render_echarts_option(chart_spec, data, theme)
    height = chart_spec.get("height", 400)

    return (
        f'<div id="{cid}" class="chart-card" '
        f'style="grid-column:span {width};background:{theme["card_bg"]};'
        f"border:1px solid {theme['border']};box-shadow:{theme['shadow']};"
        f'border-radius:8px;padding:16px;">'
        f'<div id="{cid}-chart" style="width:100%;height:{height}px;"></div>'
        f"</div>\n"
        f'<script data-chart-id="{cid}" type="application/json">{option_json}</script>\n'
    )


def _render_table_card(
    cid: str,
    chart_spec: dict,
    data: list[dict],
    theme: dict,
    width: int,
) -> str:
    """Render a data table card."""
    columns = chart_spec.get("columns", [])
    title = chart_spec.get("title", "")
    limit = chart_spec.get("limit", len(data))

    if not columns and data:
        columns = list(data[0].keys())

    rows_to_show = data[:limit]

    header_cells = "".join(f"<th>{c}</th>" for c in columns)
    body_rows = ""
    for row in rows_to_show:
        cells = "".join(f"<td>{row.get(c, '')}</td>" for c in columns)
        body_rows += f"<tr>{cells}</tr>"

    return (
        f'<div id="{cid}" class="chart-card" '
        f'style="grid-column:span {width};background:{theme["card_bg"]};'
        f"border:1px solid {theme['border']};box-shadow:{theme['shadow']};"
        f'border-radius:8px;padding:16px;overflow-x:auto;">'
        f'<h3 style="color:{theme["text"]};margin:0 0 12px 0;font-size:16px;">{title}</h3>'
        f'<table style="width:100%;border-collapse:collapse;font-size:14px;">'
        f'<thead><tr style="border-bottom:2px solid {theme["border"]};">{header_cells}</tr></thead>'
        f"<tbody>{body_rows}</tbody>"
        f"</table></div>"
    )


def _render_tabs_layout(
    charts: list[dict],
    data: list[dict],
    theme: dict,
) -> str:
    """Render tabs layout HTML (fallback to grid if no tabs defined)."""
    # Default: render all charts in a single tab
    parts = ['<div class="tab-container">']
    parts.append('<div class="tab-buttons" style="display:flex;gap:8px;margin-bottom:16px;">')
    parts.append(f'<button class="tab-btn active" onclick="switchTab(0)" style="padding:8px 16px;border:1px solid {theme["border"]};border-radius:4px;background:{theme["card_bg"]};color:{theme["text"]};cursor:pointer;">Overview</button>')
    parts.append("</div>")

    parts.append('<div class="tab-panels">')
    parts.append('<div class="tab-panel active" data-tab="0" style="display:grid;grid-template-columns:repeat(12,1fr);gap:16px;">')

    for c in charts:
        cid = c.get("id", "chart")
        pos = c.get("position", {"row": 1, "col": 1, "width": 6})
        width = min(pos.get("width", 6), 12)
        parts.append(_render_chart_card(cid, c, data, theme, width))

    parts.append("</div>")
    parts.append("</div></div>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Full HTML generation
# ---------------------------------------------------------------------------

ECHARTS_CDN = "https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"


def generate_html(
    spec: dict,
    data: list[dict],
    theme_name: str,
    kpi_values: dict[str, float | int | None],
) -> str:
    """Generate the complete dashboard HTML string."""
    theme = THEMES.get(theme_name, THEMES["light"])
    title = spec.get("title", "Dashboard")
    layout = spec.get("layout", "grid")
    charts = spec.get("charts", [])
    kpis = spec.get("kpis", [])
    filters = spec.get("filters", [])

    # Render sections
    kpi_html = ""
    if kpis:
        kpi_cards = []
        for kpi in kpis:
            val = kpi_values.get(kpi.get("label", ""), None)
            kpi_cards.append(render_kpi_card(kpi, val, theme))
        kpi_html = f'<div class="kpi-row" style="display:grid;grid-template-columns:repeat({len(kpis)},1fr);gap:16px;margin-bottom:24px;">' + "\n".join(kpi_cards) + "</div>"

    filter_html = render_filter_html(filters, data, theme)
    charts_html = render_chart_grid_html(charts, data, theme, layout)
    data_json = json.dumps(data, default=str, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="auto">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    background: {theme["bg"]};
    color: {theme["text"]};
    padding: 24px;
    max-width: 1400px;
    margin: 0 auto;
  }}
  .dashboard-header {{
    margin-bottom: 24px;
    padding-bottom: 16px;
    border-bottom: 2px solid {theme["border"]};
  }}
  .dashboard-header h1 {{
    font-size: 28px;
    font-weight: 700;
    color: {theme["text"]};
  }}
  @media (max-width: 768px) {{
    .kpi-row {{ grid-template-columns: repeat(2, 1fr) !important; }}
    .chart-grid {{ grid-template-columns: repeat(6, 1fr) !important; }}
    .chart-card {{ grid-column: span 6 !important; }}
  }}
</style>
</head>
<body>
<div class="dashboard-header">
  <h1>{title}</h1>
</div>
{filter_html}
{kpi_html}
{charts_html}
<script src="{ECHARTS_CDN}"></script>
<script>
// Dashboard data and initialization
const dashboardData = {data_json};

// Initialize all ECharts instances
function initCharts() {{
  document.querySelectorAll('script[data-chart-id]').forEach(el => {{
    const chartId = el.getAttribute('data-chart-id');
    const dom = document.getElementById(chartId + '-chart');
    if (!dom) return;
    const chart = echarts.init(dom);
    const option = JSON.parse(el.textContent);
    chart.setOption(option);
    window.addEventListener('resize', () => chart.resize());
  }});
}}

// Filter logic
function applyFilters() {{
  const filters = document.querySelectorAll('[data-filter-field]');
  const conditions = {{}};
  filters.forEach(f => {{
    const field = f.getAttribute('data-filter-field');
    const role = f.getAttribute('data-filter-role');
    if (role === 'start' || role === 'end') {{
      if (!conditions[field]) conditions[field] = {{}};
      conditions[field][role] = f.value;
    }} else {{
      conditions[field] = f.value;
    }}
  }});

  const filtered = dashboardData.filter(row => {{
    for (const [field, val] of Object.entries(conditions)) {{
      if (typeof val === 'object') {{
        const cellDate = new Date(row[field]);
        if (val.start && cellDate < new Date(val.start)) return false;
        if (val.end && cellDate > new Date(val.end)) return false;
      }} else if (val) {{
        if (String(row[field]) !== val) return false;
      }}
    }}
    return true;
  }});

  // Update charts with filtered data
  document.querySelectorAll('script[data-chart-id]').forEach(el => {{
    const chartId = el.getAttribute('data-chart-id');
    const dom = document.getElementById(chartId + '-chart');
    if (!dom) return;
    const chart = echarts.getInstanceByDom(dom);
    if (chart) {{
      // Note: For advanced filtering, re-generate the chart option server-side
      chart.showLoading({{ text: 'Filter applied — re-generate dashboard for updated data' }});
      setTimeout(() => chart.hideLoading(), 2000);
    }}
  }});
}}

// Tab switching
function switchTab(idx) {{
  document.querySelectorAll('.tab-btn').forEach((b, i) => {{
    b.classList.toggle('active', i === idx);
  }});
  document.querySelectorAll('.tab-panel').forEach((p, i) => {{
    p.style.display = i === idx ? 'grid' : 'none';
  }});
}}

// Boot
document.addEventListener('DOMContentLoaded', initCharts);
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate an interactive HTML dashboard from a spec file")
    parser.add_argument(
        "--spec-file",
        required=True,
        help="Path to the dashboard spec JSON file",
    )
    parser.add_argument(
        "--output-file",
        required=True,
        help="Path to output HTML file",
    )
    parser.add_argument(
        "--data-file",
        default=None,
        help="Pre-processed data JSON (alternative to SQL in spec)",
    )
    parser.add_argument(
        "--theme",
        default=None,
        choices=["light", "dark", "corporate"],
        help="Override theme (default: use spec value or 'light')",
    )

    args = parser.parse_args()

    # Load spec
    with open(args.spec_file, encoding="utf-8") as f:
        spec = json.load(f)

    theme_name = args.theme or spec.get("theme", "light")

    # Load data
    con = duckdb.connect()

    if args.data_file:
        with open(args.data_file, encoding="utf-8") as f:
            data = json.load(f)
    else:
        data_source = spec.get("data_source", {})
        if data_source:
            data = load_data(con, data_source)
        else:
            data = []

    # Load KPI values
    kpi_values: dict[str, float | int | None] = {}
    for kpi in spec.get("kpis", []):
        label = kpi.get("label", "")
        kpi_values[label] = load_kpi_value(con, kpi)

    con.close()

    # Generate HTML
    html = generate_html(spec, data, theme_name, kpi_values)

    # Write output
    os.makedirs(os.path.dirname(args.output_file) or ".", exist_ok=True)
    with open(args.output_file, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Dashboard generated: {args.output_file}")
    print(f"  Theme: {theme_name}")
    print(f"  Data rows: {len(data)}")
    print(f"  Charts: {len(spec.get('charts', []))}")
    print(f"  KPIs: {len(spec.get('kpis', []))}")


if __name__ == "__main__":
    main()
