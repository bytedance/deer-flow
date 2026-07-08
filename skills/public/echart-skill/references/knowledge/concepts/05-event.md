# Event & Action 事件与行为

> **Source:** `echarts-docs/handbook/zh/concepts/event.md`

## Event Types

### Mouse Events
`'click'`, `'dblclick'`, `'mousedown'`, `'mousemove'`, `'mouseup'`, `'mouseover'`, `'mouseout'`, `'globalout'`, `'contextmenu'`

### Component Interaction Events
`'legendselectchanged'`, `'datazoom'`, `'datarangeselected'`, `'timelinechanged'`, `'timelineplaychanged'`, `'brush'`, `'brushEnd'`, `'geoselectchanged'`, etc.

## Binding Events

```javascript
// Basic — all lowercase event names
myChart.on('click', function(params) {
  console.log(params.componentType);  // 'series', 'markLine', 'markPoint', etc.
  console.log(params.seriesType);     // 'line', 'bar', 'pie', etc.
  console.log(params.seriesIndex);
  console.log(params.name);           // Data name / category name
  console.log(params.dataIndex);
  console.log(params.value);
  console.log(params.color);
});
```

## Event Parameters (params object)

| Property | Description |
|----------|-------------|
| `componentType` | `'series'`, `'markLine'`, `'markPoint'`, `'timeline'`, etc. |
| `seriesType` | `'line'`, `'bar'`, `'pie'`, etc. |
| `seriesIndex` | Series index |
| `seriesName` | Series name |
| `name` | Data item name |
| `dataIndex` | Data item index |
| `data` | The data item |
| `value` | Data value |
| `color` | Series color |
| `dataType` | `'node'` or `'edge'` (for graph/sankey) |

## Filtering Events with `query`

### String Format
```javascript
myChart.on('click', 'series', handler);              // Any series
myChart.on('click', 'series.line', handler);          // Line series only
myChart.on('click', 'xAxis.category', handler);       // Category X axis
```

### Object Format
```javascript
// Filter by series name
myChart.on('mouseover', { seriesName: 'Sales' }, handler);

// Filter by graph data type
myChart.on('click', { dataType: 'node' }, handler);

// Filter by custom series element name
myChart.on('mouseup', { element: 'my_el' }, handler);

// Multiple filters
myChart.on('mouseover', { seriesIndex: 1, name: 'Product A' }, handler);
```

### Available Query Properties
`${mainType}Index`, `${mainType}Name`, `${mainType}Id`, `dataIndex`, `name`, `dataType`, `element`

## Blank Area Clicks

```javascript
// ECharts events only fire on graphic elements
// To detect blank area clicks, use zrender:
myChart.getZr().on('click', function(event) {
  if (!event.target) {
    // Clicked on empty space
    console.log('Clicked blank area');
  }
});
```

## Programmatic Actions (dispatchAction)

```javascript
// Highlight a data point
myChart.dispatchAction({ type: 'highlight', seriesIndex: 0, dataIndex: 5 });

// Remove highlight
myChart.dispatchAction({ type: 'downplay', seriesIndex: 0, dataIndex: 5 });

// Show tooltip
myChart.dispatchAction({ type: 'showTip', seriesIndex: 0, dataIndex: 5 });

// Hide tooltip
myChart.dispatchAction({ type: 'hideTip' });
```

## Unbinding Events

```javascript
// Remove specific handler
myChart.off('click', handler);

// Remove all handlers for event
myChart.off('click');

// Remove ALL handlers
myChart.off();
```

## Important Notes

1. Mouse/component event names are lowercase strings (e.g. `'click'`, `'mousemove'`, `'legendselectchanged'`). Note: a few system events use camelCase like `'brushEnd'` and `'globalCursorTaken'`.
2. `myChart.on()` — fires only when the mouse is on a graphic element
3. `myChart.getZr().on()` — fires for any position, including blank areas
4. `'legendselectchanged'` fires on toggle; `'legendselected'` does NOT
5. For `query` objects, `dataIndex` takes precedence over `name` when both are specified
