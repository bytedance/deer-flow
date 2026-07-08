# Pattern: Drag Interaction

> **Source:** `echarts-docs/handbook/zh/how-to/interaction/drag.md`

## Architecture

Drag interaction uses three ECharts subsystems:
1. **`graphic` component** — draggable overlay elements
2. **Coordinate conversion** — `convertToPixel` / `convertFromPixel`
3. **`dispatchAction`** — tooltip control

## Implementation

### Step 1: Base Chart

```javascript
var chart = echarts.init(document.getElementById('main'));
chart.setOption({
  xAxis: { type: 'value' },
  yAxis: { type: 'value' },
  series: [{
    type: 'line',
    symbolSize: 20,            // Large enough for dragging
    data: [[10, 20], [20, 50], [30, 30]]
  }]
});
```

### Step 2: Add Draggable Overlays

```javascript
// Must be called AFTER setOption (coordinates are available)
chart.setOption({
  graphic: chart.getOption().series[0].data.map(function(item, dataIndex) {
    return {
      type: 'circle',
      shape: { r: 10 },
      position: chart.convertToPixel({ seriesIndex: 0 }, item),  // Data → pixels
      invisible: true,           // Invisible but interactive
      draggable: true,
      ondrag: echarts.util.curry(onPointDragging, dataIndex),
      z: 100
    };
  })
});
```

### Step 3: Drag Handler

```javascript
function onPointDragging(dataIndex, dx, dy) {
  // this.position = current pixel position of the dragged graphic element

  // Pixel → data coordinates
  var newCoords = chart.convertFromPixel({ seriesIndex: 0 }, this.position);

  // Update data
  var data = chart.getOption().series[0].data;
  data[dataIndex] = newCoords;

  // Re-render
  chart.setOption({ series: [{ data: data }] });
}
```

### Step 4: Handle Resize

```javascript
window.addEventListener('resize', function() {
  // Re-position graphic overlays
  var data = chart.getOption().series[0].data;
  chart.setOption({
    graphic: data.map(function(item, dataIndex) {
      return {
        position: chart.convertToPixel({ seriesIndex: 0 }, item)
      };
    })
  });
});
```

### Step 5: Manual Tooltip Control

```javascript
// Disable default tooltip trigger
tooltip: { triggerOn: 'none' }

// On drag start, show tooltip
graphic: {
  onmousedown: function() {
    chart.dispatchAction({ type: 'showTip', seriesIndex: 0, dataIndex: dataIndex });
  },
  ondrag: function() {
    chart.dispatchAction({ type: 'showTip', seriesIndex: 0, dataIndex: dataIndex, position: this.position });
  },
  onmouseup: function() {
    chart.dispatchAction({ type: 'hideTip' });
  }
}
```

## Extension Ideas

- Add `dataZoom` component for pan/zoom
- Build a drawing/annotation board
- Implement drag-to-reorder for ranked lists

## Key Rules

1. `convertToPixel` / `convertFromPixel` only work **after** `setOption` (coordinate system must be initialized)
2. Pixel coordinates are relative to the chart container DOM's top-left corner
3. `graphic` elements use the same coordinate system as chart rendering
4. `echarts.util.curry(fn, arg)` creates the curried drag handler
