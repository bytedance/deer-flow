---
description: Build an interactive HTML dashboard with charts, filters, and tables
argument-hint: "<description> [data source]"
---

# /build-dashboard - Build Interactive Dashboards

> If you see unfamiliar placeholders or need to check which tools are connected, see [CONNECTORS.md](../CONNECTORS.md).

Build a self-contained interactive HTML dashboard with charts, filters, tables, and professional styling. Opens directly in a browser -- no server or dependencies required.

## Usage

```
/build-dashboard <description of dashboard> [data source]
```

## Workflow

### 1. Understand the Dashboard Requirements

Determine:

- **Purpose**: Executive overview, operational monitoring, deep-dive analysis, team reporting
- **Audience**: Who will use this dashboard?
- **Key metrics**: What numbers matter most?
- **Dimensions**: What should users be able to filter or slice by?
- **Data source**: Live query, pasted data, CSV file, or sample data

### 2. Gather the Data

**If data warehouse is connected:**
1. Query the necessary data
2. Embed the results as JSON within the HTML file

**If data is pasted or uploaded:**
1. Parse and clean the data
2. Embed as JSON in the dashboard

**If working from a description without data:**
1. Create a realistic sample dataset matching the described schema
2. Note in the dashboard that it uses sample data
3. Provide instructions for swapping in real data

### 3. Design the Dashboard Layout

Follow a standard dashboard layout pattern:

```
┌──────────────────────────────────────────────────┐
│  Dashboard Title                    [Filters ▼]  │
├────────────┬────────────┬────────────┬───────────┤
│  KPI Card  │  KPI Card  │  KPI Card  │ KPI Card  │
├────────────┴────────────┼────────────┴───────────┤
│                         │                        │
│    Primary Chart        │   Secondary Chart      │
│    (largest area)       │                        │
│                         │                        │
├─────────────────────────┴────────────────────────┤
│                                                  │
│    Detail Table (sortable, scrollable)           │
│                                                  │
└──────────────────────────────────────────────────┘
```

**Adapt the layout to the content:**
- 2-4 KPI cards at the top for headline numbers
- 1-3 charts in the middle section for trends and breakdowns
- Optional detail table at the bottom for drill-down data
- Filters in the header or sidebar depending on complexity

### 4. Build the HTML Dashboard

Generate a single self-contained HTML file that includes:

**Structure (HTML):**
- Semantic HTML5 layout
- Responsive grid using CSS Grid or Flexbox
- Filter controls (dropdowns, date pickers, toggles)
- KPI cards with values and labels
- Chart containers
- Data table with sortable headers

**Styling (CSS):**
- Professional color scheme (clean whites, grays, with accent colors for data)
- Card-based layout with subtle shadows
- Consistent typography (system fonts for fast loading)
- Responsive design that works on different screen sizes
- Print-friendly styles

**Interactivity (JavaScript):**
- Chart.js for interactive charts (included via CDN)
- Filter dropdowns that update all charts and tables simultaneously
- Sortable table columns
- Hover tooltips on charts
- Number formatting (commas, currency, percentages)

**Data (embedded JSON):**
- All data embedded directly in the HTML as JavaScript variables
- No external data fetches required
- Dashboard works completely offline

### 5. Implement Chart Types

Use Chart.js for all charts. Common dashboard chart patterns:

- **Line chart**: Time series trends
- **Bar chart**: Category comparisons
- **Doughnut chart**: Composition (when <6 categories)
- **Stacked bar**: Composition over time
- **Mixed (bar + line)**: Volume with rate overlay

### 6. Add Interactivity

**Filters:**
```javascript
// All filters update a central filter state
// Charts and tables re-render when filters change
function applyFilters() {
    const filtered = data.filter(row => matchesFilters(row));
    updateKPIs(filtered);
    updateCharts(filtered);
    updateTable(filtered);
}
```

**Table sorting:**
- Click column headers to sort ascending/descending
- Visual indicator for current sort column and direction

**Tooltips:**
- Charts show detailed values on hover
- KPI cards show comparison to previous period

### 7. Save and Open

1. Save the dashboard as an HTML file with a descriptive name (e.g., `sales_dashboard.html`)
2. Open it in the user's default browser
3. Confirm it renders correctly
4. Provide instructions for updating data or customizing

## Output Template

The generated HTML file follows this structure:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>[Dashboard Title]</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.5.1" integrity="sha384-jb8JQMbMoBUzgWatfe6COACi2ljcDdZQ2OxczGA3bGNeWe+6DChMTBJemed7ZnvJ" crossorigin="anonymous"></script>
    <style>
        /* Professional dashboard CSS */
    </style>
</head>
<body>
    <div class="dashboard">
        <header><!-- Title and filters --></header>
        <section class="kpis"><!-- KPI cards --></section>
        <section class="charts"><!-- Chart containers --></section>
        <section class="details"><!-- Data table --></section>
    </div>
    <script>
        const DATA = [/* embedded JSON data */];
        // Dashboard initialization and interactivity
    </script>
</body>
</html>
```

## Examples

```
/build-dashboard Monthly sales dashboard with revenue trend, top products, and regional breakdown. Data is in the orders table.
```

```
/build-dashboard Here's our support ticket data [pastes CSV]. Build a dashboard showing volume by priority, response time trends, and resolution rates.
```

```
/build-dashboard Create a template executive dashboard for a SaaS company showing MRR, churn, new customers, and NPS. Use sample data.
```

## Tips

- Dashboards are fully self-contained HTML files -- share them with anyone by sending the file
- For real-time dashboards, consider connecting to a BI tool instead. These dashboards are point-in-time snapshots
- Request "dark mode" or "presentation mode" for different styling
- You can request a specific color scheme to match your brand
