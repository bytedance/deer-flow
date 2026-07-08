# Pattern: Canvas vs SVG Renderer

> **Source:** `echarts-docs/handbook/zh/best-practices/canvas-vs-svg.md`

## How to Choose

```javascript
// Canvas (default)
echarts.init(dom, null, { renderer: 'canvas' });

// SVG
echarts.init(dom, null, { renderer: 'svg' });
```

## Decision Matrix

| Scenario | Recommended | Reason |
|----------|-------------|--------|
| Large data (1000+ points), many interactions | **Canvas** | Better performance for large datasets |
| Many chart instances on one page | **SVG** | Lower memory per instance |
| Mobile / low-end devices (many charts) | **SVG** | Less memory pressure |
| Need crisp rendering at browser zoom | **SVG** | Vector, no pixelation |
| Glow/trail effects, blended heatmaps | **Canvas** | Required for some effects |
| Moderate data, good hardware | Either | No meaningful difference |

## Renderer-Specific Notes

### Canvas
- Default renderer
- Better for large data (scatter, lines with many points)
- Required for: glowing trail effects (`series-lines.effect`), blended heatmaps
- Dirty rectangle rendering available (`useDirtyRect: true` in init opts)

### SVG
- Rebuilt with virtual DOM in v5.3 — 2-10x (sometimes 10x+) performance improvement
- Sharper on browser zoom (no pixelation)
- Lower memory for many instances (mobile scenarios)
- Required for SSR (`ssr: true` in init opts)
- Use `renderToSVGString()` to get SVG string output

## On-Demand Import

Full import (`import * as echarts from 'echarts'`) includes both renderers. For tree-shaking:

```javascript
// Canvas only
import { CanvasRenderer } from 'echarts/renderers';
echarts.use([CanvasRenderer]);

// SVG only
import { SVGRenderer } from 'echarts/renderers';
echarts.use([SVGRenderer]);

// Both
import { CanvasRenderer, SVGRenderer } from 'echarts/renderers';
echarts.use([CanvasRenderer, SVGRenderer]);
```

## TL;DR
- **Default to Canvas** for most cases
- **Switch to SVG** if: memory issues, many instances, mobile, browser zoom, SSR
- **Test both** in performance-sensitive scenarios
