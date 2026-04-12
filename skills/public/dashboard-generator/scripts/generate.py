"""
Dashboard Generator Script.

Reads a dashboard spec JSON, queries data via DuckDB, and generates a
self-contained interactive HTML dashboard using Apache ECharts.
"""

import argparse
import html
import json
import os
import re
import sys

try:
    import duckdb
except ImportError:
    print("ERROR: duckdb is required. Install with: pip install duckdb")
    sys.exit(1)

try:
    import openpyxl  # noqa: F401
except ImportError:
    print("ERROR: openpyxl is required. Install with: pip install openpyxl")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Security helpers
# ---------------------------------------------------------------------------

_ALLOWED_PATH_PREFIXES = (
    "/mnt/user-data/",
    "/mnt/skills/",
)


def validate_path(file_path: str, context: str = "file path") -> str:
    """Validate that a file path stays within allowed directories."""
    resolved = os.path.realpath(file_path)
    if not any(resolved.startswith(prefix) for prefix in _ALLOWED_PATH_PREFIXES):
        cwd = os.path.realpath(os.getcwd())
        if not resolved.startswith(cwd + os.sep) and resolved != cwd:
            raise ValueError(
                f"Invalid {context}: '{file_path}' resolves to '{resolved}', "
                f"which is outside allowed directories."
            )
    return file_path


def sanitize_identifier(name: str) -> str:
    """Sanitize a string to be a safe SQL identifier (table/view name)."""
    return re.sub(r"[^a-zA-Z0-9_]", "_", name)


def esc(value) -> str:
    """HTML-escape a value for safe embedding in HTML output."""
    return html.escape(str(value), quote=True)


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

    # Register files as views using parameterized queries
    for f in files:
        validate_path(f, "data file")
        ext = os.path.splitext(f)[1].lower()
        base = sanitize_identifier(os.path.splitext(os.path.basename(f))[0])
        if ext == ".csv":
            con.execute(f'CREATE OR REPLACE VIEW "{base}" AS SELECT * FROM read_csv_auto(?)', [f])
        elif ext in (".xlsx", ".xls"):
            con.execute("INSTALL spatial; LOAD spatial;")
            wb = openpyxl.load_workbook(f, read_only=True)
            sheets = wb.sheetnames
            wb.close()
            for sheet in sheets:
                safe_sheet = f"{base}_{sanitize_identifier(sheet)}"
                con.execute(
                    f'CREATE OR REPLACE VIEW "{safe_sheet}" AS SELECT * FROM st_read(?, layer = ?, open_options = [\'HEADERS=FORCE\', \'FIELD_TYPES=AUTO\'])',
                    [f, sheet],
                )

    # NOTE: 'sql' is intentionally a raw DuckDB SQL query written by the Agent.
    # This is by design — the Agent constructs queries based on user instructions
    # and they run inside a sandboxed DuckDB instance.
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
        # NOTE: 'sql' is intentionally raw DuckDB SQL (same as load_data).
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
    label = esc(kpi.get("label", "KPI"))
    fmt = kpi.get("format", "number")
    display = esc(format_kpi_value(value, fmt))
    return f"""<div class="kpi-card" style="background:{theme["kpi_bg"]};border:1px solid {theme["border"]};box-shadow:{theme["shadow"]};border-radius:8px;padding:20px;text-align:center;">
      <div style="color:{theme["text_secondary"]};font-size:14px;margin-bottom:8px;">{label}</div>
      <div style="color:{theme["text"]};font-size:28px;font-weight:700;">{display}</div>
    </div>"""


def build_echarts_option(
    chart_spec: dict,
    data: list[dict],
    theme: dict,
) -> dict:
    """Build an ECharts option dict for a chart spec from the given data."""
    chart_type = chart_spec.get("type", "line")
    x_field = chart_spec.get("x", "")
    y_fields = chart_spec.get("y", [])
    title = chart_spec.get("title", "")

    echarts_type = ECHART_TYPE_MAP.get(chart_type, "line")

    if chart_type in ("pie", "donut"):
        agg: dict[str, float] = {}
        for row in data:
            key = str(row.get(x_field, ""))
            val = 0
            for yf in y_fields:
                v = row.get(yf, 0)
                val += float(v) if v is not None else 0
            agg[key] = agg.get(key, 0) + val

        pie_data = [{"name": k, "value": v} for k, v in agg.items()]
        radius = ["40%", "70%"] if chart_type == "donut" else ["0%", "70%"]
        return {
            "title": {"text": title, "textStyle": {"color": theme["text"]}},
            "tooltip": {"trigger": "item"},
            "color": json.loads(theme["palette"]),
            "series": [
                {
                    "type": "pie",
                    "radius": radius,
                    "data": pie_data,
                    "emphasis": {"itemStyle": {"shadowBlur": 10, "shadowOffsetX": 0, "shadowColor": "rgba(0,0,0,0.5)"}},
                }
            ],
        }

    # Cartesian charts (line, area, bar, column, scatter)
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
        series_list.append(s)

    # bar = horizontal bars (swap axes), column = vertical bars (default)
    if chart_type == "bar":
        return {
            "title": {"text": title, "textStyle": {"color": theme["text"]}},
            "tooltip": {"trigger": "axis"},
            "color": json.loads(theme["palette"]),
            "xAxis": {"type": "value", "axisLabel": {"color": theme["text_secondary"]}},
            "yAxis": {"type": "category", "data": x_values, "axisLabel": {"color": theme["text_secondary"]}},
            "series": series_list,
        }

    return {
        "title": {"text": title, "textStyle": {"color": theme["text"]}},
        "tooltip": {"trigger": "axis"},
        "color": json.loads(theme["palette"]),
        "xAxis": {"type": "category", "data": x_values, "axisLabel": {"color": theme["text_secondary"]}},
        "yAxis": {"type": "value", "axisLabel": {"color": theme["text_secondary"]}},
        "series": series_list,
    }


def render_echarts_option(
    chart_spec: dict,
    data: list[dict],
    theme: dict,
) -> str:
    """Build an ECharts option JSON string for a chart spec."""
    return json.dumps(build_echarts_option(chart_spec, data, theme))


def render_filter_html(filters: list[dict], data: list[dict], theme: dict) -> str:
    """Render filter controls as HTML."""
    if not filters:
        return ""

    parts = ['<div class="filter-bar" style="display:flex;gap:16px;margin-bottom:20px;flex-wrap:wrap;">']
    for f in filters:
        field = esc(f["field"])
        label = esc(f.get("label", f["field"]))
        ftype = f.get("type", "select")

        if ftype == "select":
            unique_vals = sorted(set(str(row.get(f["field"], "")) for row in data))
            options_html = "<option value=''>All</option>"
            for v in unique_vals:
                safe_v = esc(v)
                options_html += f"<option value='{safe_v}'>{safe_v}</option>"
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
            cid = esc(c.get("id", f"chart-{row_num}"))
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

    option_json = render_echarts_option(chart_spec, data, theme).replace("</script", r"<\/script")
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
    title = esc(chart_spec.get("title", ""))
    limit = chart_spec.get("limit", len(data))

    if not columns and data:
        columns = list(data[0].keys())

    rows_to_show = data[:limit]

    header_cells = "".join(f"<th>{esc(c)}</th>" for c in columns)
    body_rows = ""
    for row in rows_to_show:
        cells = "".join(f"<td>{esc(row.get(c, ''))}</td>" for c in columns)
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
    parts = ['<div class="tab-container">']
    parts.append('<div class="tab-buttons" style="display:flex;gap:8px;margin-bottom:16px;">')
    parts.append(f'<button class="tab-btn active" onclick="switchTab(0)" style="padding:8px 16px;border:1px solid {theme["border"]};border-radius:4px;background:{theme["card_bg"]};color:{theme["text"]};cursor:pointer;">Overview</button>')
    parts.append("</div>")

    parts.append('<div class="tab-panels">')
    parts.append('<div class="tab-panel active" data-tab="0" style="display:grid;grid-template-columns:repeat(12,1fr);gap:16px;">')

    for c in charts:
        cid = esc(c.get("id", "chart"))
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
    title = esc(spec.get("title", "Dashboard"))
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
    raw_data_json = json.dumps(data, default=str, ensure_ascii=False)
    data_json = raw_data_json.replace("</script", r"<\/script")

    # Build chart spec definitions for client-side filtering
    chart_specs_js = "{"
    for c in charts:
        cid = c.get("id", "chart")
        spec = {{
            "type": c.get("type", "line"),
            "x": c.get("x", ""),
            "y": c.get("y", []),
            "title": c.get("title", ""),
            "limit": c.get("limit"),
            "columns": c.get("columns", []),
        }}
        chart_specs_js += f'"{cid}": {json.dumps(spec).replace("</script", r"<\/script")},'
    chart_specs_js += "}"

    theme_palette_json = theme["palette"]

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
// Dashboard data and chart specs
const dashboardData = {data_json};
const chartSpecs = {chart_specs_js};
const themePalette = {theme_palette_json};
const themeColors = {{
  text: {json.dumps(theme["text"])},
  textSecondary: {json.dumps(theme["text_secondary"])}
}};

// Build an ECharts option from a chart spec + data
function buildOption(spec, data) {{
  const chartType = spec.type || 'line';
  const xField = spec.x || '';
  const yFields = spec.y || [];
  const title = spec.title || '';
  const typeMap = {{line:'line',area:'line',bar:'bar',column:'bar',pie:'pie',donut:'pie',scatter:'scatter',treemap:'treemap',radar:'radar',funnel:'funnel'}};
  const echartsType = typeMap[chartType] || 'line';

  if (chartType === 'pie' || chartType === 'donut') {{
    const agg = {{}};
    data.forEach(row => {{
      const key = String(row[xField] || '');
      let val = 0;
      yFields.forEach(yf => {{ const v = row[yf]; val += v != null ? Number(v) : 0; }});
      agg[key] = (agg[key] || 0) + val;
    }});
    const pieData = Object.entries(agg).map(([k,v]) => ({{name:k,value:v}}));
    const radius = chartType === 'donut' ? ['40%','70%'] : ['0%','70%'];
    return {{
      title: {{text: title, textStyle: {{color: themeColors.text}}}},
      tooltip: {{trigger: 'item'}},
      color: themePalette,
      series: [{{type: 'pie', radius: radius, data: pieData,
        emphasis: {{itemStyle: {{shadowBlur: 10, shadowOffsetX: 0, shadowColor: 'rgba(0,0,0,0.5)'}}}}}}]
    }};
  }}

  // Cartesian charts
  const xValues = [];
  const seen = new Set();
  data.forEach(row => {{
    const xv = String(row[xField] || '');
    if (!seen.has(xv)) {{ xValues.push(xv); seen.add(xv); }}
  }});

  const series = yFields.map(yf => {{
    const yVals = xValues.map(xv => {{
      const matched = data.find(r => String(r[xField] || '') === xv);
      const v = matched ? matched[yf] : 0;
      return v != null ? Number(v) : 0;
    }});
    const s = {{name: yf, type: echartsType, data: yVals}};
    if (chartType === 'area') s.areaStyle = {{}};
    return s;
  }});

  // bar = horizontal (swap axes), column = vertical (default)
  if (chartType === 'bar') {{
    return {{
      title: {{text: title, textStyle: {{color: themeColors.text}}}},
      tooltip: {{trigger: 'axis'}},
      color: themePalette,
      xAxis: {{type: 'value', axisLabel: {{color: themeColors.textSecondary}}}},
      yAxis: {{type: 'category', data: xValues, axisLabel: {{color: themeColors.textSecondary}}}},
      series: series
    }};
  }}

  return {{
    title: {{text: title, textStyle: {{color: themeColors.text}}}},
    tooltip: {{trigger: 'axis'}},
    color: themePalette,
    xAxis: {{type: 'category', data: xValues, axisLabel: {{color: themeColors.textSecondary}}}},
    yAxis: {{type: 'value', axisLabel: {{color: themeColors.textSecondary}}}},
    series: series
  }};
}}

// Update a table card with filtered data
function updateTableCard(chartId, spec, data) {{
  const container = document.getElementById(chartId);
  if (!container) return;
  const columns = spec.columns && spec.columns.length > 0 ? spec.columns : (data.length > 0 ? Object.keys(data[0]) : []);
  const limit = spec.limit || data.length;
  const rows = data.slice(0, limit);
  const tbody = container.querySelector('tbody');
  if (tbody) {{
    tbody.innerHTML = rows.map(row => '<tr>' + columns.map(c => '<td>' + (row[c] != null ? row[c] : '') + '</td>').join('') + '</tr>').join('');
  }}
}}

// Initialize all ECharts instances
function initCharts() {{
  Object.keys(chartSpecs).forEach(chartId => {{
    const dom = document.getElementById(chartId + '-chart');
    if (!dom) return;
    const chart = echarts.init(dom);
    const option = buildOption(chartSpecs[chartId], dashboardData);
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

  // Rebuild each chart with filtered data
  Object.keys(chartSpecs).forEach(chartId => {{
    const spec = chartSpecs[chartId];
    if (spec.type === 'table') {{
      updateTableCard(chartId, spec, filtered);
      return;
    }}
    const dom = document.getElementById(chartId + '-chart');
    if (!dom) return;
    const chart = echarts.getInstanceByDom(dom);
    if (chart) {{
      chart.setOption(buildOption(spec, filtered), true);
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

    # Validate paths
    spec_path = validate_path(args.spec_file, "spec file")
    output_path = validate_path(args.output_file, "output file")

    # Load spec
    with open(spec_path, encoding="utf-8") as f:
        spec = json.load(f)

    theme_name = args.theme or spec.get("theme", "light")

    # Load data
    con = duckdb.connect()

    if args.data_file:
        validate_path(args.data_file, "data file")
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
    html_output = generate_html(spec, data, theme_name, kpi_values)

    # Write output
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_output)

    print(f"Dashboard generated: {output_path}")
    print(f"  Theme: {theme_name}")
    print(f"  Data rows: {len(data)}")
    print(f"  Charts: {len(spec.get('charts', []))}")
    print(f"  KPIs: {len(spec.get('kpis', []))}")


if __name__ == "__main__":
    main()
