# API: Registration Methods

> **Source:** `echarts-api-docs/echarts/`

## echarts.registerMap(mapName, opt)

Register a map for `geo` component or `map` series.

### Form 1: GeoJSON
```javascript
echarts.registerMap('my_map', {
  geoJSON: {
    type: 'FeatureCollection',
    features: [{
      type: 'Feature',
      properties: { name: 'Region A', cp: [120, 30] },  // cp = label center position
      geometry: { type: 'Polygon', coordinates: [...] }
    }]
  },
  specialAreas: {
    Alaska: { left: -131, top: 25, width: 15 },    // Adjust position for isolated areas
    Hawaii: { left: -110, top: 28, width: 5 }
  }
});

// Usage:
option = {
  geo: { map: 'my_map' }
  // OR
  series: [{ type: 'map', map: 'my_map' }]
};
```

### Form 2: SVG (v5.1+)
```javascript
echarts.registerMap('svg_map', { svg: svgString });
// SVG elements with 'name' attribute become interactive regions
```

### Form 3: Legacy positional args
```javascript
echarts.registerMap('my_map', geoJSON, specialAreas);
```

**Important:** With tree-shaking, must import `MapChart` or `GeoComponent` first.

---

## echarts.registerTheme(themeName, theme) — v6.0

```javascript
echarts.registerTheme('myTheme', {
  backgroundColor: '#f4f4f4',
  color: ['#c23531', '#2f4554', '#61a0a8'],
  // ... full theme config
});
echarts.init(dom, 'myTheme');
```

---

## echarts.registerLocale(locale, localeCfg) — v5.0

```javascript
echarts.registerLocale('FR', {
  time: { month: ['Janvier', 'Février', ...], /* ... */ },
  toolbox: { saveAsImage: { title: 'Sauvegarder' }, /* ... */ }
  // ... full locale config (see echarts/src/i18n/langEN.ts for format)
});
echarts.init(dom, null, { locale: 'FR' });
```

Built-in locales: `'ZH'` (Chinese), `'EN'` (English).

---

## echarts.registerCustomSeries(type, renderItem) — v6.0

Register a reusable named custom series:

```javascript
const renderItem = (params, api) => {
  return {
    type: 'circle',
    shape: {
      cx: api.coord([api.value(0), api.value(1)])[0],
      cy: api.coord([api.value(0), api.value(1)])[1],
      r: api.value(2) * (params.itemPayload.scale || 1)
    },
    style: { fill: api.visual('color') }
  };
};
echarts.registerCustomSeries('bubble', renderItem);

// Usage: series.type is still 'custom', renderItem is the registered name string
option = {
  series: {
    type: 'custom',
    renderItem: 'bubble',
    itemPayload: { scale: 2 },
    data: [[11, 22, 20], [33, 44, 40]]
  }
};
```

Official custom series: [github.com/apache/echarts-custom-series](https://github.com/apache/echarts-custom-series)

---

## echarts.use(components) — v5.0.1

Tree-shaking (on-demand import):

```javascript
import * as echarts from 'echarts/core';
import { BarChart, LineChart } from 'echarts/charts';
import {
  GridComponent, TooltipComponent, LegendComponent,
  TitleComponent, DatasetComponent, TransformComponent,
  DataZoomComponent, VisualMapComponent, ToolboxComponent,
  AriaComponent
} from 'echarts/components';
import { LabelLayout, UniversalTransition } from 'echarts/features';
import { CanvasRenderer } from 'echarts/renderers';

echarts.use([
  TitleComponent, TooltipComponent, GridComponent, LegendComponent,
  DatasetComponent, TransformComponent, DataZoomComponent,
  VisualMapComponent, ToolboxComponent, AriaComponent,
  BarChart, LineChart,
  LabelLayout, UniversalTransition,
  CanvasRenderer
]);
// Must call use() BEFORE echarts.init()
```

### Naming Convention
- Charts: `echarts/charts`, suffix `Chart` (e.g., `BarChart`, `LineChart`)
- Components: `echarts/components`, suffix `Component` (e.g., `GridComponent`, `TooltipComponent`)
- Features: `echarts/features` (e.g., `LabelLayout`, `UniversalTransition`)
- Renderers: `echarts/renderers` (e.g., `CanvasRenderer`, `SVGRenderer`)

**A renderer is mandatory** — choose at least `CanvasRenderer` or `SVGRenderer`.

---

## echarts.getMap(mapName)

Retrieve registered map data:

```javascript
var mapData = echarts.getMap('my_map');
// Returns: { geoJSON: {...}, specialAreas: {...} }
// SVG maps are NOT returned by this method
```
