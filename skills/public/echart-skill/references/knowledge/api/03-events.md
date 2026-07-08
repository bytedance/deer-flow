# API: Events

> **Source:** `echarts-api-docs/echartsInstance/on.md`, `echarts-api-docs/events/`

## Binding Events

```javascript
// Form 1: No filter
chart.on(eventName, handler);

// Form 2: With query filter
chart.on(eventName, query, handler);

// Form 3: With context
chart.on(eventName, query, handler, context);
```

## Unbinding

```javascript
chart.off('click');           // Remove all 'click' handlers
chart.off('click', handler);  // Remove specific handler
chart.off();                  // Remove ALL handlers
```

## Mouse Events

`'click'`, `'dblclick'`, `'mousedown'`, `'mousemove'`, `'mouseup'`, `'mouseover'`, `'mouseout'`, `'globalout'`, `'contextmenu'`

## Component/Interaction Events

| Event | Trigger | Payload |
|-------|---------|---------|
| `'legendselectchanged'` | Legend item toggle | — |
| `'datazoom'` | Data zoom operation | `{ start, end, startValue?, endValue? }` |
| `'datarangeselected'` | visualMap range change | `{ selected }` |
| `'timelinechanged'` | Timeline index change | `{ currentIndex }` |
| `'timelineplaychanged'` | Timeline play/pause | `{ playState }` |
| `'brush'` | Brush in progress | — |
| `'brushEnd'` | Brush completed (v4.5) | — |
| `'globalCursorTaken'` | Brush/dataZoom cursor activated | — |
| `'graphroam'` | Graph zoom/pan | `{ seriesId, zoom?, dx?, dy? }` |
| `'treeroam'` | Tree zoom/pan | `{ seriesId, zoom?, dx?, dy? }` |
| `'legendscroll'` | Scrollable legend scrolled | `{ scrollDataIndex, legendId }` |
| `'legendinverseselect'` | Legend invert | `{ selected: { name: boolean } }` |
| `'geoselectchanged'` | Geo region select toggle | — |
| `'geoselected'` | Geo region selected | — |
| `'geounselected'` | Geo region unselected | — |
| `'restore'` | Toolbox restore clicked | — |
| `'axisbreakchanged'` | Axis break toggled (v6) | — |

## Query Filters

### String Format
```javascript
chart.on('click', 'series', handler);           // Any series
chart.on('click', 'series.line', handler);       // Line series only
chart.on('click', 'xAxis.category', handler);    // Category X-axis
```

### Object Format
```javascript
chart.on('mouseover', { seriesName: 'Sales' }, handler);
chart.on('click', { seriesIndex: 1, name: 'A' }, handler);
chart.on('click', { dataType: 'node' }, handler);    // Graph node only
chart.on('mouseup', { element: 'my_el' }, handler);  // Custom series element
```

### Available Query Properties
`${mainType}Index`, `${mainType}Name`, `${mainType}Id`, `dataIndex`, `name`, `dataType`, `element`

## Detecting Blank Area Clicks

```javascript
chart.getZr().on('click', function(event) {
  if (!event.target) {
    // Clicked on blank area (no graphic element)
  }
});
```

## Important Notes

- All event names are **lowercase** (not PascalCase like ECharts 2.x)
- `chart.on()` — only fires on graphic elements
- `chart.getZr().on()` — fires everywhere, including blank areas
- `dataIndex` takes priority over `name` when both are in query
