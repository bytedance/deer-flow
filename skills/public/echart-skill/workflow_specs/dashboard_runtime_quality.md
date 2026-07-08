# Dashboard Runtime Quality Gate

Use this file after `workflow_specs/dashboard_workflow.md` whenever generating
or repairing a dashboard HTML file.

This file exists because visually acceptable dashboard HTML can still fail at
runtime when opened from `file://`: invalid global JS, runtime CDN loaders,
missing map registration, chart data/coordinate mismatches, or PDF export
incompatibility. Treat this as a blocking quality gate, not optional advice.

## Non-Negotiable Runtime Rules

1. The dashboard must be a standalone single HTML file.
2. No runtime dependency may be loaded from a URL.
3. No dependency may be fetched dynamically after page load.
4. All libraries must be embedded before the chart bootstrap script.
5. The final HTML must pass `python scripts/validate_chart.py <output.html>`.
6. Browser automation is optional only; the required quality gate must work
   without opening a browser.
7. A file that contains `echarts.init` but does not contain an inlined
   `assets/echarts/echarts.min.js` library is invalid even if it has no
   `<script src>` tag.
8. ECharts graphic constructors such as
   `new echarts.graphic.LinearGradient(...)` must be syntactically closed
   before the surrounding option object is closed.

## Library Embedding Order

Embed scripts in this order:

1. `assets/echarts/echarts.min.js`
2. Required local map file, such as `assets/echarts/china.js`
3. `assets/dashboard/html2canvas.min.js`
4. `assets/dashboard/jspdf.umd.min.js`
5. `assets/dashboard/dashboard.js` or equivalent `DashboardController`
6. The chart bootstrap script that creates chart instances
7. The global control wiring script, if not already in the controller

Do not place chart bootstrap code before ECharts or map registration.

The generated HTML must embed the actual local ECharts library, not a CDN and
not a placeholder. This is a hard rule for charts, reports, and dashboards:

```html
<!-- Wrong: file:// output becomes network-dependent and unstable. -->
<script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>

<!-- Right: read assets/echarts/echarts.min.js and inline the full content. -->
<script>
/* full local ECharts library content */
</script>
```

Chart option strings must be valid JavaScript. If an ECharts label needs a line
break, write an escaped newline:

```js
label: { formatter: "{b}\n{d}%" }
```

Do not split a quoted string over two physical lines:

```js
// Wrong: this creates a SyntaxError and prevents initCharts from being defined.
label: { formatter: "{b}
{d}%" }
```

Gradient constructors must also be balanced. The following pattern is invalid
and blocks every chart initialized after it:

```js
// Wrong: missing ")" before closing the option object.
areaStyle: {
  color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
    { offset: 0, color: "rgba(56,239,125,0.3)" },
    { offset: 1, color: "rgba(56,239,125,0)" }
  ] }
}

// Right.
areaStyle: {
  color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
    { offset: 0, color: "rgba(56,239,125,0.3)" },
    { offset: 1, color: "rgba(56,239,125,0)" }
  ])
}
```

## Forbidden Patterns

These patterns are blocking failures:

- `<script src="https://...">`
- `<link href="https://...">`
- `script.src = "https://..."`
- `fetch("https://...")` for map JSON or chart data
- `document.head.innerHTML += "<script src=..."`
- `<iframe>`, `<frame>`, `<object>`, or `<embed>`
- `window.open(...)`
- `document.location.href = ...`
- `window.location = ...`
- `location.href = ...`
- `document.createElement("iframe")`
- chart bootstrap scripts before the inlined ECharts library
- `echarts.init` without the full local `assets/echarts/echarts.min.js`
  content inlined earlier in the file
- unclosed `new echarts.graphic.LinearGradient(...)` or
  `new echarts.graphic.RadialGradient(...)`
- raw line breaks inside JavaScript string literals, especially ECharts
  formatter strings
- any `file://` value in generated business script, tag `src`, tag `href`, or
  tag `data`
- `var window.dashboardCharts = []`
- `var window = window || {}`
- `var document = document || {}`
- `echarts.registerMap("china", chinaGeoJSON)` unless `chinaGeoJSON` is
  explicitly defined in the same script
- `color-mix(...)`, `oklch(...)`, `oklab(...)`, `lab(...)`, or `lch(...)` in
  dashboard CSS when PDF export uses html2canvas

Use plain assignments for globals:

```js
window.dashboardCharts = [];
window.dashboard = new DashboardController({ charts: window.dashboardCharts });
```

## Map Rules

When using a China map:

1. Inline `assets/echarts/china.js`.
2. Let that file call `echarts.registerMap("china", ...)`.
3. Do not fetch GeoJSON from `geo.datav.aliyun.com` or any CDN.
4. Use `geo` + `effectScatter` for city-level sales/volume bubbles.
5. Coordinate keys must match the actual data values.
   - If data has `北京市`, the coordinate map must contain `北京市`.
   - Aliases like `北京` are useful, but not enough by themselves.
6. If coordinates are missing for many cities, show a visible data-gap note and
   use the ranked bar fallback described in
   `workflow_specs/dashboard_modules/city_sales_map.md`.

## PDF Export Rules

PDF export must not be only a button label. It must execute.

Required runtime behavior:

1. `html2canvas` and `jsPDF`/`jspdf.jsPDF` are available from inlined scripts.
2. `exportDashboard()` first attempts canvas-based PDF export.
3. It catches export errors and falls back to `window.print()`.
4. It shows a toast or visible message when falling back.
5. It avoids CSS that html2canvas cannot parse.
6. It passes `ignoreElements` to html2canvas so toast/temporary overlay nodes do
   not leak into the exported PDF.
7. It must not call `new jsPDF(...)` directly unless `jsPDF` was resolved from
   `window.jspdf.jsPDF` or `window.jsPDF` in the same function.

Recommended resolver:

```js
const JsPDF = window.jspdf && window.jspdf.jsPDF ? window.jspdf.jsPDF : window.jsPDF;
if (!JsPDF) {
  window.print();
  return;
}
const pdf = new JsPDF("l", "mm", "a4");
```

Supported CSS color forms for dashboard export:

- hex: `#ffffff`
- rgb: `rgb(255, 255, 255)`
- rgba: `rgba(255, 255, 255, 0.94)`
- named colors only when necessary

Avoid modern CSS color functions in dashboard templates because html2canvas may
throw before producing a canvas.

## Theme Switch Rules

Theme switching must update the page, not only the charts.

Required theme updates:

- `document.documentElement[data-theme]`
- `document.body[data-theme]`
- `.dashboard-container[data-theme]`
- CSS tokens for page, surface, line, text, buttons, cards, charts, diagnostics,
  toolbar, header, and toast
- ECharts instances, recreated or refreshed with the selected theme

## Chart Bootstrap Rules

1. Initialize `window.dashboardCharts = []` exactly once before creating charts.
2. Dispose old chart instances before rebuilding after theme changes.
3. Push every ECharts instance into `window.dashboardCharts`.
4. Create `window.dashboard` after the controller is defined.
5. Keep `downloadChart(id, name)` available on the controller or globally.
6. Use dual axes for mixed bar/line charts when metrics have different units or
   orders of magnitude.

## Required Browser-Free Static Gate

`scripts/validate_chart.py` is the required gate because the skill may not have
browser automation available.

The validator must check:

- HTML tag structure for forbidden `src`, `href`, `data`, `iframe`, `object`,
  `embed`, and `file://` references
- custom inline script syntax with `node --check` when Node is available
- runtime external loaders in custom scripts
- runtime navigation or self-load patterns in custom scripts
- unresolved template placeholders
- ECharts initialization and `setOption`
- actual inlined ECharts library before chart initialization
- balanced `echarts.graphic.LinearGradient(...)` and
  `echarts.graphic.RadialGradient(...)` constructor calls
- chart type and non-empty data
- dashboard controller, CSS markers, PDF export dependencies, and
  `downloadChart`
- PDF-incompatible CSS color functions
- map registration when `geo`, `map`, or `effectScatter` is used

The validator must distinguish vendor libraries from Agent-authored business
scripts. For example, `jsPDF` may contain internal helper code that is not used
by the dashboard; generated business scripts must still be free of self-load,
location navigation, and iframe creation.

## Optional Browser Smoke Test

When browser automation is available, it is useful but not required. Open the
generated HTML with `file://` and check:

- no `pageerror`
- no console error
- `typeof window.echarts === "object"`
- `window.dashboardCharts.length` equals the expected chart count
- every chart card has a rendered canvas
- city map card has a canvas when geography is triggered
- `Array.from(document.scripts).filter(s => s.src)` is empty
- HTML does not contain `var window.`, `chinaGeoJSON`, `color-mix(`, or runtime
  CDN/fetch code
- PDF export triggers a `.pdf` download or falls back to `window.print()` with a
  visible warning
- `downloadChart()` exists and can produce an image URL

## Failure Response

If any rule fails, do not return the dashboard as complete.

Regenerate or repair the HTML first, then rerun:

```bash
python scripts/validate_chart.py <output.html>
```

For dashboard outputs, also run a real browser smoke test where possible.
If validation reports an external ECharts CDN, missing inlined ECharts library,
or an unclosed ECharts graphic constructor, repair those first because they
usually prevent all charts from rendering.
