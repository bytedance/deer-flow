# Pattern: Import Strategy (Full vs Tree-Shaking)

> **Source:** `echarts-docs/handbook/zh/basics/import.md`, `echarts-docs/handbook/zh/basics/download.md`

## Three Import Strategies

| Strategy | Bundle Size | Use Case |
|----------|-------------|----------|
| CDN / Full npm import | ~1MB (gzipped ~300KB) | Quick prototyping, demos, simple pages |
| Tree-shaking (on-demand) | Minimal (only what you use) | Production web apps |
| Online custom builder | Smaller than full | When not using a bundler |

## Strategy 1: CDN

```html
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<script>
  var chart = echarts.init(document.getElementById('main'));
  chart.setOption({ /* ... */ });
</script>
```

## Strategy 2: Full npm Import

```javascript
import * as echarts from 'echarts';
// Everything included — ~1MB
```

## Strategy 3: Tree-Shaking (Recommended for Production)

```javascript
import * as echarts from 'echarts/core';
import { BarChart, LineChart, PieChart, ScatterChart } from 'echarts/charts';
import {
  TitleComponent, TooltipComponent, GridComponent, LegendComponent,
  DatasetComponent, TransformComponent, ToolboxComponent,
  DataZoomComponent, VisualMapComponent, MarkLineComponent,
  MarkPointComponent, AriaComponent
} from 'echarts/components';
import { LabelLayout, UniversalTransition } from 'echarts/features';
import { CanvasRenderer } from 'echarts/renderers';

// MUST register before init
echarts.use([
  TitleComponent, TooltipComponent, GridComponent, LegendComponent,
  DatasetComponent, TransformComponent, ToolboxComponent,
  DataZoomComponent, VisualMapComponent, MarkLineComponent,
  MarkPointComponent, AriaComponent,
  BarChart, LineChart, PieChart, ScatterChart,
  LabelLayout, UniversalTransition,
  CanvasRenderer
]);

// Now init
const chart = echarts.init(document.getElementById('main'));
```

## Import Paths Reference

| Import Path | Suffix Convention | Examples |
|-------------|-------------------|----------|
| `echarts/charts` | `Chart` | `BarChart`, `LineChart`, `PieChart`, `ScatterChart`, `EffectScatterChart`, `CandlestickChart`, `RadarChart`, `GaugeChart`, `FunnelChart`, `SankeyChart`, `TreemapChart`, `SunburstChart`, `BoxplotChart`, `ParallelChart`, `TreeChart`, `GraphChart`, `MapChart`, `CustomChart`, `HeatmapChart`, `PictorialBarChart`, `ThemeRiverChart` |
| `echarts/components` | `Component` | `GridComponent`, `TooltipComponent`, `LegendComponent`, `TitleComponent`, `DatasetComponent`, `TransformComponent`, `DataZoomComponent`, `VisualMapComponent`, `ToolboxComponent`, `AriaComponent`, `MarkLineComponent`, `MarkPointComponent`, `MarkAreaComponent`, `GeoComponent`, `CalendarComponent`, `TimelineComponent`, `GraphicComponent`, `SingleAxisComponent`, `ParallelComponent`, `PolarComponent`, `BrushComponent` |
| `echarts/features` | — | `LabelLayout`, `UniversalTransition` |
| `echarts/renderers` | `Renderer` | `CanvasRenderer`, `SVGRenderer` |

## TypeScript with ComposeOption

```typescript
import type { BarSeriesOption, LineSeriesOption } from 'echarts/charts';
import type {
  TitleComponentOption, TooltipComponentOption,
  GridComponentOption, DatasetComponentOption
} from 'echarts/components';
import type { ComposeOption } from 'echarts/core';

// ComposeOption gives strict type checking
type ECOption = ComposeOption<
  | BarSeriesOption
  | LineSeriesOption
  | TitleComponentOption
  | TooltipComponentOption
  | GridComponentOption
  | DatasetComponentOption
>;

const option: ECOption = {
  // TypeScript will validate this against the composed types
};
```

## Critical Rules

1. **A renderer is MANDATORY** — without `CanvasRenderer` or `SVGRenderer`, nothing renders
2. **Call `echarts.use()` BEFORE `echarts.init()`**
3. **Omitted components silently fail** — e.g., `title.show: true` with no `TitleComponent` has no effect
4. **`AriaComponent` must be explicitly imported** (not included by default since v5)
5. Since v5.5.0, ESM is the default module format
