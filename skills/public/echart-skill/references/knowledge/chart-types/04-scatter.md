# Scatter Chart 散点图

> **Source:** `echarts-docs/handbook/zh/how-to/chart-types/scatter/basic-scatter.md`

## Basic Scatter

### Category Axis Scatter
```javascript
option = {
  xAxis: { type: 'category', data: ['A', 'B', 'C'] },
  yAxis: { type: 'value' },
  series: [{
    type: 'scatter',
    data: [10, 20, 30]     // Simple values — X from category axis
  }]
};
```

### Cartesian (XY) Scatter
```javascript
option = {
  xAxis: { type: 'value' },
  yAxis: { type: 'value' },
  series: [{
    type: 'scatter',
    data: [[10, 20], [20, 50], [30, 30], [40, 80]]  // Each point: [x, y]
  }]
};
```

## Symbol Customization

### Built-in Symbols
```javascript
series: {
  symbol: 'circle',    // Options: 'circle', 'rect', 'roundRect', 'triangle',
                       // 'diamond', 'pin', 'arrow'
  // 'emptyCircle', 'emptyRect', etc. (hollow versions starting with 'empty')
}
```

### Image Symbol
```javascript
series: {
  symbol: 'image://http://example.com/icon.png'
}
```

### SVG Path Symbol (Recommended)
```javascript
series: {
  symbol: 'path://M 0 0 L 10 10 L 20 0 Z'  // SVG path d-attribute value
}
```

**Advantage of SVG paths:** Never blurry, smaller than image files.
**How to get:** Open SVG file, find `<path d="...">`, copy the `d` value.

## Symbol Size

```javascript
// Fixed size
symbolSize: 10

// Width/height array
symbolSize: [20, 10]    // [width, height]

// Function (data-driven)
symbolSize: function(value, params) {
  return Math.sqrt(value[2]) * 5;  // Map 3rd dimension to size
}

// Using visualMap (recommended for size mapping)
visualMap: {
  type: 'continuous',
  dimension: 2,
  inRange: { symbolSize: [5, 50] }
}
```

## Bubble Chart (3D Scatter)

Use symbol size to represent a third dimension:

```javascript
option = {
  xAxis: { type: 'value' },
  yAxis: { type: 'value' },
  visualMap: {
    dimension: 2,
    min: 0, max: 100,
    inRange: { symbolSize: [5, 60] }
  },
  series: [{
    type: 'scatter',
    data: [[10, 20, 30], [30, 40, 80], [50, 10, 50]]  // [x, y, sizeValue]
  }]
};
```

## Beeswarm & Jitter (ECharts 6+)

```javascript
series: {
  type: 'scatter',
  jitter: 0.2,              // Random offset amount on non-value axis
  jitterOverlap: false       // false = beeswarm (no overlap); true = jitter (random)
}
```

## Scatter with dataset

```javascript
dataset: {
  source: [[x, y, size], ...]
},
series: {
  type: 'scatter',
  encode: { x: 0, y: 1 }  // Map dimensions to axes
}
```
