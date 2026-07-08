# API: Actions (dispatchAction)

> **Source:** `echarts-api-docs/action/`

All actions are dispatched via:
```javascript
chart.dispatchAction({ type: 'actionName', ...params });
```

---

## Highlight & Select

### highlight / downplay
```javascript
chart.dispatchAction({
  type: 'highlight',
  seriesIndex: 0,        // or seriesId/seriesName
  dataIndex: 5           // or name
});
chart.dispatchAction({ type: 'downplay', seriesIndex: 0, dataIndex: 5 });

// Geo component (v5.1+)
chart.dispatchAction({
  type: 'highlight',
  geoIndex: 0,
  name: 'Beijing'        // Region name in geo component
});
```

### select / unselect / toggleSelect
```javascript
chart.dispatchAction({ type: 'select', seriesIndex: 0, dataIndex: 5 });
chart.dispatchAction({ type: 'unselect', seriesIndex: 0, dataIndex: 5 });
chart.dispatchAction({ type: 'toggleSelect', seriesIndex: 0, dataIndex: 5 });
```
All support: `seriesIndex`/`seriesId`/`seriesName` (single or array), `dataIndex`/`name`.

---

## Tooltip

### showTip
```javascript
// By screen position
chart.dispatchAction({ type: 'showTip', x: 100, y: 200 });

// By data item
chart.dispatchAction({ type: 'showTip', seriesIndex: 0, dataIndex: 5 });

// Geo region (v5.1+)
chart.dispatchAction({ type: 'showTip', geoIndex: 0, name: 'Shanghai' });

// All forms support optional position override
chart.dispatchAction({ type: 'showTip', seriesIndex: 0, dataIndex: 5, position: [100, 200] });
```

### hideTip
```javascript
chart.dispatchAction({ type: 'hideTip' });
```

---

## Legend

```javascript
// Toggle single item (most common)
chart.dispatchAction({ type: 'legendToggleSelect', name: 'Sales' });

// Select/unselect specific item
chart.dispatchAction({ type: 'legendSelect', name: 'Sales' });
chart.dispatchAction({ type: 'legendUnSelect', name: 'Sales' });

// Batch operations (v5.6+ optional legendId/legendIndex)
chart.dispatchAction({ type: 'legendInverseSelect' });
chart.dispatchAction({ type: 'legendAllSelect' });

// Scroll legend (type: 'scroll' only)
chart.dispatchAction({ type: 'legendScroll', scrollDataIndex: 5 });
```

---

## DataZoom

```javascript
// By percentage
chart.dispatchAction({ type: 'dataZoom', start: 20, end: 80 });

// By value
chart.dispatchAction({ type: 'dataZoom', startValue: 100, endValue: 500 });

// Specific dataZoom component
chart.dispatchAction({ type: 'dataZoom', dataZoomIndex: 1, start: 0, end: 50 });

// Activate brush zoom cursor
chart.dispatchAction({ type: 'takeGlobalCursor', key: 'dataZoomSelect', dataZoomSelectActive: true });
```

---

## Brush

```javascript
// Set brush selection areas
chart.dispatchAction({
  type: 'brush',
  areas: [{
    brushType: 'rect',
    coordRange: [[10, 20], [30, 50]],  // Data coordinates
    xAxisIndex: 0
  }]
});

// Clear all brush areas
chart.dispatchAction({ type: 'brush', areas: [] });

// Activate brush mode
chart.dispatchAction({
  type: 'takeGlobalCursor',
  key: 'brush',
  brushOption: { brushType: 'rect', brushMode: 'single' }  // false to disable
});
```

---

## VisualMap

```javascript
// Continuous
chart.dispatchAction({ type: 'selectDataRange', selected: [20, 40] });

// Piecewise (by index)
chart.dispatchAction({ type: 'selectDataRange', selected: { 1: false } });

// Piecewise (by name)
chart.dispatchAction({ type: 'selectDataRange', selected: { 'Excellent': false } });
```

---

## Timeline

```javascript
chart.dispatchAction({ type: 'timelineChange', currentIndex: 3 });
chart.dispatchAction({ type: 'timelinePlayChange', playState: true });   // Play
chart.dispatchAction({ type: 'timelinePlayChange', playState: false });  // Pause
```

---

## Toolbox

```javascript
chart.dispatchAction({ type: 'restore' });  // Reset to initial state
```

---

## Geo/Map

```javascript
chart.dispatchAction({ type: 'geoSelect', geoIndex: 0, name: 'China' });
chart.dispatchAction({ type: 'geoUnSelect', geoIndex: 0, name: 'China' });
chart.dispatchAction({ type: 'geoToggleSelect', geoIndex: 0, name: 'China' });
```

---

## Treemap

```javascript
chart.dispatchAction({ type: 'treemapRootToNode', seriesIndex: 0, targetNodeId: 'nodeId' });
chart.dispatchAction({ type: 'treemapZoomToNode', seriesIndex: 0, targetNodeId: 'nodeId' });
// targetNodeId refers to the node's id (or name if no id set)
```

---

## Axis Break (v6.0+)

```javascript
chart.dispatchAction({
  type: 'toggleAxisBreak',
  yAxisIndex: 0,
  breaks: { start: 0, end: 10 }
});
// Also: 'expandAxisBreak', 'collapseAxisBreak'
// Target axis via: xAxisIndex/xAxisId/xAxisName, yAxisIndex/yAxisId/yAxisName, singleAxisIndex/singleAxisId/singleAxisName
// Use 'all' for axis index to target all axes
```

---

## Batch Actions

```javascript
chart.dispatchAction({
  type: 'dataZoom',
  batch: [
    { start: 20, end: 30 },
    { dataZoomIndex: 1, start: 10, end: 20 }
  ]
});
```
