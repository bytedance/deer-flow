# ECharts Knowledge Base Index

> Auto-generated from ECharts Handbook & API docs. Use this index to find relevant knowledge snippets before generating chart code.

## 🎯 Generation Workflow (MUST FOLLOW)

When generating ECharts code, follow this 4-step process:

### Step 1: Identify → Find in Index
Identify chart type (bar/line/pie/scatter/candlestick/etc.) and required features (stack/race/waterfall/etc.)

### Step 2: Read Knowledge Snippets → Syntax Constraints
Read the relevant chart-type, concept, and pattern files from this index. These contain:
- Correct configuration syntax and property names
- Common mistakes to avoid
- Best practices and caveats

### Step 3: Read Example Code → Working Reference
**CRITICAL:** Always read at least 1 matching example's `main.js` from the examples directory:
- Examples are at: `/Users/wuliang/workspace/echarts-examples/<example-name>/main.js`
- Use [examples/INDEX.md](examples/INDEX.md) to find matching examples by chart type
- The example code is the ground truth for correct ECharts syntax

### Step 4: Submit Together → Generate
Submit the knowledge snippets + example code as combined context to generate the final chart. The knowledge provides the rules; the examples provide the proven working patterns.

---

## 📊 Chart Types

| Chart | File | Key Topics |
|-------|------|------------|
| Bar (柱状图) | [chart-types/01-bar.md](chart-types/01-bar.md) | Basic bar, stacked bar, waterfall, bar race, background, borderRadius, barWidth/barGap |
| Line (折线图) | [chart-types/02-line.md](chart-types/02-line.md) | Basic line, stacked line, step line, smooth line, area line, null data handling |
| Pie (饼图) | [chart-types/03-pie.md](chart-types/03-pie.md) | Basic pie, doughnut (ring), rose/nightingale, radius, label positioning |
| Scatter (散点图) | [chart-types/04-scatter.md](chart-types/04-scatter.md) | Basic scatter, symbol customization, symbolSize, SVG path symbols |

---

## 🧠 Core Concepts

| Concept | File | Key Topics |
|---------|------|------------|
| Dataset | [concepts/01-dataset.md](concepts/01-dataset.md) | dataset.source formats, seriesLayoutBy, encode, dimensions, multi-dataset |
| Visual Map | [concepts/02-visual-map.md](concepts/02-visual-map.md) | continuous vs piecewise, inRange/outOfRange, color/size mapping |
| Data Transform | [concepts/03-data-transform.md](concepts/03-data-transform.md) | filter, sort, chain transforms, external transforms (ecStat) |
| Style | [concepts/04-style.md](concepts/04-style.md) | Themes, palette, itemStyle/lineStyle/areaStyle, emphasis, gradients, shadows |
| Event & Action | [concepts/05-event.md](concepts/05-event.md) | Mouse events, component events, dispatchAction, query filters, getZr() |
| Axis | [concepts/06-axis.md](concepts/06-axis.md) | Multi-axis, axisLine, axisTick, axisLabel, offset, dual Y-axis |
| Legend | [concepts/07-legend.md](concepts/07-legend.md) | Layout, scrollable legend, selected state, per-item icon, positioning |
| Chart Size | [concepts/08-chart-size.md](concepts/08-chart-size.md) | Container sizing, CSS vs init params, resize(), dispose() for memory |

---

## 🔧 API Reference

### ECharts Static Methods
| Method | File | Description |
|--------|------|-------------|
| init | [api/01-init-setup.md](api/01-init-setup.md) | Create chart instance with all options |
| connect/disconnect | [api/01-init-setup.md](api/01-init-setup.md) | Link multiple charts for sync |
| dispose/getInstanceByDom | [api/01-init-setup.md](api/01-init-setup.md) | Cleanup and retrieval |
| registerMap | [api/06-registration.md](api/06-registration.md) | Register GeoJSON/SVG maps |
| registerTheme | [api/06-registration.md](api/06-registration.md) | Register custom themes |
| registerLocale | [api/06-registration.md](api/06-registration.md) | Register i18n locale |
| registerCustomSeries | [api/06-registration.md](api/06-registration.md) | Register named custom series (v6) |
| use | [api/06-registration.md](api/06-registration.md) | Tree-shaking component registration |

### Instance Methods
| Method | File | Description |
|--------|------|-------------|
| setOption | [api/02-instance-methods.md](api/02-instance-methods.md) | Set/update chart config and data |
| getOption | [api/02-instance-methods.md](api/02-instance-methods.md) | Get current merged option |
| resize | [api/02-instance-methods.md](api/02-instance-methods.md) | Resize chart (must call manually on container change) |
| getWidth/getHeight/getDom | [api/02-instance-methods.md](api/02-instance-methods.md) | Dimension queries |
| showLoading/hideLoading | [api/02-instance-methods.md](api/02-instance-methods.md) | Loading animation overlay |
| getDataURL | [api/02-instance-methods.md](api/02-instance-methods.md) | Export chart as image (base64) |
| appendData | [api/02-instance-methods.md](api/02-instance-methods.md) | Incremental rendering for large data |
| setTheme | [api/02-instance-methods.md](api/02-instance-methods.md) | Dynamic theme switching (v6) |
| clear/dispose/isDisposed | [api/02-instance-methods.md](api/02-instance-methods.md) | Lifecycle management |

### Events
| Topic | File | Description |
|-------|------|-------------|
| on/off | [api/03-events.md](api/03-events.md) | Event binding and unbinding |
| Mouse events | [api/03-events.md](api/03-events.md) | click, mousemove, mouseover, mouseout, etc. |
| Component events | [api/03-events.md](api/03-events.md) | legendselectchanged, datazoom, brush, etc. |
| Query filters | [api/03-events.md](api/03-events.md) | string and object query formats |

### Actions (dispatchAction)
| Topic | File | Description |
|-------|------|-------------|
| All actions | [api/04-actions.md](api/04-actions.md) | Complete action reference with params |
| Tooltip control | [api/04-actions.md](api/04-actions.md) | showTip, hideTip |
| Highlight/Select | [api/04-actions.md](api/04-actions.md) | highlight, downplay, select, unselect, toggleSelect |
| Legend control | [api/04-actions.md](api/04-actions.md) | legendSelect, legendToggleSelect, legendInverseSelect, etc. |
| DataZoom control | [api/04-actions.md](api/04-actions.md) | dataZoom, takeGlobalCursor |
| Geo/Map control | [api/04-actions.md](api/04-actions.md) | geoSelect, geoUnSelect, geoToggleSelect |
| Axis break | [api/04-actions.md](api/04-actions.md) | toggleAxisBreak, expandAxisBreak, collapseAxisBreak (v6) |

### Coordinate Conversion
| Method | File | Description |
|--------|------|-------------|
| convertToPixel | [api/05-coordinate-utils.md](api/05-coordinate-utils.md) | Data coords → pixel coords (all coordinate systems) |
| convertFromPixel | [api/05-coordinate-utils.md](api/05-coordinate-utils.md) | Pixel coords → data coords |
| containPixel | [api/05-coordinate-utils.md](api/05-coordinate-utils.md) | Check if point is in coordinate system |
| convertToLayout | [api/05-coordinate-utils.md](api/05-coordinate-utils.md) | Calendar/matrix → layout rect (v6) |

---

## 📐 Patterns & Best Practices

| Pattern | File | Key Topics |
|---------|------|------------|
| Canvas vs SVG | [patterns/01-canvas-vs-svg.md](patterns/01-canvas-vs-svg.md) | When to use each renderer, performance characteristics |
| Animation | [patterns/02-animation.md](patterns/02-animation.md) | Entry/update animation, easing, delay, threshold, bar race |
| Rich Text Labels | [patterns/03-rich-text.md](patterns/03-rich-text.md) | rich text formatting, icons, backgrounds, text fragments |
| Dynamic Data | [patterns/04-dynamic-data.md](patterns/04-dynamic-data.md) | Async loading, setInterval updates, showLoading |
| Responsiveness | [patterns/05-responsiveness.md](patterns/05-responsiveness.md) | resize(), ResizeObserver, hidden containers |
| Security | [patterns/06-security.md](patterns/06-security.md) | XSS prevention, encodeHTML, URL validation, ReDoS |
| Accessibility | [patterns/07-accessibility.md](patterns/07-accessibility.md) | ARIA descriptions, decal patterns, screen readers |
| SVG Base Map | [patterns/08-svg-base-map.md](patterns/08-svg-base-map.md) | SVG map registration, interaction, naming elements |
| Drag Interaction | [patterns/09-drag-interaction.md](patterns/09-drag-interaction.md) | graphic component dragging, coordinate conversion |
| Import Strategy | [patterns/10-import-strategy.md](patterns/10-import-strategy.md) | Tree-shaking, CDN, TypeScript, ComposeOption |

---

## 📁 Example Index

See [examples/INDEX.md](examples/INDEX.md) for the complete example catalog organized by chart type.

---

## 🚀 Quick Start Code Templates

### Minimal Bar Chart
```javascript
const chart = echarts.init(document.getElementById('main'));
chart.setOption({
  xAxis: { data: ['A', 'B', 'C'] },
  yAxis: {},
  series: [{ type: 'bar', data: [10, 20, 30] }]
});
```

### Minimal Line Chart
```javascript
const chart = echarts.init(document.getElementById('main'));
chart.setOption({
  xAxis: { data: ['Mon', 'Tue', 'Wed'] },
  yAxis: {},
  series: [{ type: 'line', data: [10, 20, 30] }]
});
```

### On-Demand Import (Tree-Shaking)
```javascript
import * as echarts from 'echarts/core';
import { BarChart, LineChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
echarts.use([GridComponent, TooltipComponent, LegendComponent, BarChart, LineChart, CanvasRenderer]);
```

---

> **Note:** File paths in this index are relative to `references/knowledge/`. Source documentation is in Chinese (zh) and English.
