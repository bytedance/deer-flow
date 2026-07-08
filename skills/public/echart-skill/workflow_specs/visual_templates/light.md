# Light Visual Specification

Use this as the default visual direction for Agent-authored reports and dashboards.

## Tone

Formal, enterprise, executive-review ready.

## Report Direction

- Paper-like canvas centered on a muted application background.
- Header should feel like a PDF cover: title, subtitle, date, scope, and optional confidence/assumption note.
- Use numbered sections.
- Use compact tables with strong header rows.
- Use conclusion cards only for material findings.
- Print styles should remove app background and shadows.

Suggested palette:

- Page background: `#e9edf5`
- Paper: `#ffffff`
- Text: `#172033`
- Muted text: `#667085`
- Accent: `#1f5eff`
- Border: `#d8dee9`
- Warning: `#b45309`
- Critical: `#c81e1e`

## Dashboard Direction

- Restrained header and toolbar.
- KPI cards should be compact and comparable.
- Charts should use consistent spacing and axis styling.
- Use blue as accent, not as the entire palette.
- Use green/yellow/red only for semantic status.

## CSS Contract

The Agent may write CSS directly into the generated HTML. Avoid external fonts,
remote images, external stylesheets, and generic decorative gradients.

## Mandatory HTML/CSS Contract

The generated HTML must visibly implement this template. Do not treat this file
as high-level advice.

### Base Layout

- `body` background: `#e9edf5`.
- Main report paper or dashboard shell must use `#ffffff`, a max-width suited to the artifact, and clear margins.
- Reports should use a paper width around `1040px-1180px`; dashboards may use full-width constrained content.
- Use a restrained system font stack: `Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`.
- Text color must be `#172033`; secondary text must use `#667085`.

### Report Requirements

- Use a PDF-like cover/header with title, subtitle, scope, period, generated date, and selected expert mode.
- Use a one-page executive summary immediately after the cover.
- Use numbered sections with clear hierarchy.
- Main evidence must be chart panels, not raw tables.
- Tables belong in appendix unless they are small comparison tables under a chart.
- Include print CSS with white page background and no decorative shadows.

### Dashboard Requirements

- Header contains title, scope, refresh/status, and compact toolbar.
- KPI cards must align in a stable grid and use comparable typography.
- Chart panels must have consistent padding, title, subtitle/insight, and fixed min-height.
- Insight cards must contain numbers and interpretation, not generic labels.

### Chart Styling

- ECharts backgrounds should be transparent.
- Axis label color: `#667085`.
- Axis line/grid color: `#d8dee9`.
- Primary series color: `#1f5eff`.
- Use semantic colors only for status: success green, warning amber, critical red.

### Fail Conditions

Regenerate if any condition is true:

- HTML looks like browser-default content.
- Large raw tables appear before conclusions or charts.
- Report starts with data description instead of conclusions.
- Sections have no visual hierarchy.
- Colors do not match this template.
