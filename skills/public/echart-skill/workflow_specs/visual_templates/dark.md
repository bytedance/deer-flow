# Dark Visual Specification

Use this when the user requests dark mode or a monitoring/command-center dashboard.

## Tone

Formal, low-glare, operations-ready.

## Report Direction

- Dark paper on darker application background.
- Maintain strong contrast for headings and tables.
- Avoid neon-heavy styling.
- Use subtle borders and restrained shadows.
- Keep print output legible; reports may switch to white background in `@media print`.

Suggested palette:

- Page background: `#0b1220`
- Paper: `#111a2c`
- Muted surface: `#172033`
- Text: `#eef2f8`
- Muted text: `#b7c1d3`
- Accent: `#7aa2ff`
- Border: `#26344c`
- Warning: `#fbbf24`
- Critical: `#f87171`

## Dashboard Direction

- Prioritize scanability over decoration.
- Use bright colors only for status, threshold, or alerts.
- Ensure chart labels and grid lines remain readable.
- Keep interactive controls visible but quiet.

## CSS Contract

The Agent may write CSS directly into the generated HTML. Avoid external fonts,
remote images, external stylesheets, and one-note purple/blue gradients.

## Mandatory HTML/CSS Contract

The generated HTML must visibly implement this template. Do not treat this file
as high-level advice.

### Base Layout

- `body` background: `#0b1220`.
- Main paper/shell surface must use `#111a2c`.
- Secondary panels may use `#172033`.
- Text color must be `#eef2f8`; secondary text must use `#b7c1d3`.
- Borders must use `#26344c`.
- Use a restrained system font stack: `Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`.

### Report Requirements

- Use a formal cover/header with title, subtitle, scope, period, generated date, and selected expert mode.
- Use a conclusion-first page immediately after the cover.
- Use chart panels as primary evidence.
- Put detailed tables, SQL, and raw field summaries in appendix.
- In `@media print`, switch to white background, dark text, and remove shadows if needed.

### Dashboard Requirements

- Use compact header, quiet toolbar, stable KPI grid, and scan-friendly chart panels.
- Bright colors are allowed only for status, thresholds, or alerts.
- Avoid neon effects, glowing cards, and decorative gradients.

### Chart Styling

- ECharts backgrounds should be transparent.
- Axis label color: `#b7c1d3`.
- Axis line/grid color: `#26344c`.
- Primary series color: `#7aa2ff`.
- Warning: `#fbbf24`; critical: `#f87171`.

### Fail Conditions

Regenerate if any condition is true:

- HTML looks like browser-default content.
- Report starts with raw data or table summaries instead of conclusions.
- Large tables appear before chart evidence.
- Contrast is weak or chart labels are hard to read.
- Colors do not match this template.
