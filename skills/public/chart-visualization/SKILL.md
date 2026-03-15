---
name: chart-visualization
description: This skill should be used when the user wants to visualize data. It intelligently selects the most suitable chart type from 26 available options, extracts parameters based on detailed specifications, and generates a chart image using a JavaScript script.
dependency:
  nodejs: ">=18.0.0"
---

# Chart Visualization Skill

This skill provides a comprehensive workflow for transforming data into visual charts. It handles chart selection, parameter extraction, and image generation.

## Workflow

To visualize data, follow these steps:

### 1. Intelligent Chart Selection
Analyze the user's data features to determine the most appropriate chart type. Use the following guidelines (and consult `references/` for detailed specs):

- **Time Series**: Use `generate_line_chart` (trends) or `generate_area_chart` (accumulated trends). Use `generate_dual_axes_chart` for two different scales.
- **Comparisons**: Use `generate_bar_chart` (categorical) or `generate_column_chart`. Use `generate_histogram_chart` for frequency distributions.
- **Part-to-Whole**: Use `generate_pie_chart` or `generate_treemap_chart` (hierarchical).
- **Relationships & Flow**: Use `generate_scatter_chart` (correlation), `generate_sankey_chart` (flow), or `generate_venn_chart` (overlap).
- **Maps**: Use `generate_district_map` (regions), `generate_pin_map` (points), or `generate_path_map` (routes).
- **Hierarchies & Trees**: Use `generate_organization_chart` or `generate_mind_map`.
- **Specialized**:
    - `generate_radar_chart`: Multi-dimensional comparison.
    - `generate_funnel_chart`: Process stages.
    - `generate_liquid_chart`: Percentage/Progress.
    - `generate_word_cloud_chart`: Text frequency.
    - `generate_boxplot_chart` or `generate_violin_chart`: Statistical distribution.
    - `generate_network_graph`: Complex node-edge relationships.
    - `generate_fishbone_diagram`: Cause-effect analysis.
    - `generate_flow_diagram`: Process flow.
    - `generate_spreadsheet`: Tabular data or pivot tables for structured data display and cross-tabulation.

### 2. Parameter Extraction
Once a chart type is selected, read the corresponding file in the `references/` directory (e.g., `references/generate_line_chart.md`) to identify the required and optional fields.
Extract the data from the user's input and map it to the expected `args` format.

### 3. Chart Generation
Invoke the `scripts/generate.js` script with a JSON payload.

**Payload Format:**
```json
{
  "tool": "generate_chart_type_name",
  "args": {
    "data": [...],
    "title": "...",
    "theme": "...",
    "style": { ... }
  }
}
```

**Execution Command:**
```bash
node ./scripts/generate.js '<payload_json>'
```

### 4. Result Return
The script will output the URL of the generated chart image.
Return the following to the user:
- The image URL.
- The complete `args` (specification) used for generation.

### 5. Visualization Narrative Design

When creating charts for academic or analytical purposes, design the visualization to tell a story, not just display data:

**Chart Selection by Research Insight**:
- "X is significantly different from Y" → Bar chart with error bars and significance brackets
- "X correlates with Y" → Scatter plot with regression line and CI band
- "Trend changes over time" → Line chart with shaded confidence intervals
- "Distribution differs between groups" → Violin plot or Raincloud plot
- "Multiple factors interact" → Heatmap with hierarchical clustering or interaction plot
- "Part-to-whole composition" → Stacked bar (absolute) or 100% stacked bar (proportional)
- "Flow or process" → Sankey chart or flow diagram
- "Multi-dimensional comparison" → Radar chart or parallel coordinates

**Publication-Quality Standards**:
- Resolution: 300 DPI minimum; 600 DPI for line art
- Fonts: Axis labels ≥ 8pt at final print size
- Colors: Maximum 7 colors; use colorblind-safe palettes (viridis, cividis, Set2)
- Uncertainty: Always show error bars, CI bands, or bootstrapped distributions
- Annotations: Add statistical significance directly on plots (* p<.05, ** p<.01, *** p<.001)
- Export: SVG/PDF for LaTeX/Illustrator, PNG for web

**Caption Requirements** (for academic figures):
- First sentence: What the figure SHOWS (not what it IS)
- Define all abbreviations, statistical tests, and significance thresholds
- Specify n per group and exact p-values for key comparisons
- Example: "Fig. 3. Treatment X reduces tumor volume compared to control.
  (A) Tumor volume over 28 days. Error bars represent SEM (n=12 per group).
  *p < 0.05, **p < 0.01, two-tailed t-test."

**Journal-Specific Formatting**:
- Match target journal column width (single: 85mm, double: 170mm)
- File format: PDF (vector) for line/bar, TIFF/PNG for photos/heatmaps
- Color: Use Okabe-Ito or ColorBrewer palettes for colorblind accessibility
- Font: Arial or Helvetica, minimum 8pt after scaling to print size

**Anti-patterns to avoid**:
- 3D charts (distort perception)
- Dual y-axes (misleading — use faceted/small-multiple plots)
- Rainbow color maps (perceptually non-uniform)
- Truncated y-axis without clear indication
- Bar charts for continuous distributions (use violin/density/box)

## Reference Material
Detailed specifications for each chart type are located in the `references/` directory. Consult these files to ensure the `args` passed to the script match the expected schema.

## License

This `SKILL.md` is provided by [antvis/chart-visualization-skills](https://github.com/antvis/chart-visualization-skills).
Licensed under the [MIT License](https://github.com/antvis/chart-visualization-skills/blob/master/LICENSE).