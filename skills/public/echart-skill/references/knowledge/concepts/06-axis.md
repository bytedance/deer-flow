# Axis 坐标轴配置

> **Source:** `echarts-docs/handbook/zh/concepts/axis.md`

## Basic Structure

```javascript
xAxis: { type: 'category', data: ['A', 'B', 'C'] },  // Category axis
yAxis: { type: 'value' }                               // Value axis
```

Axis types: `'category'`, `'value'`, `'time'`, `'log'`

## Multiple Axes

```javascript
yAxis: [
  { type: 'value', name: 'Sales', position: 'left' },
  { type: 'value', name: 'Growth Rate', position: 'right' }
],
series: [
  { type: 'bar', data: [...], yAxisIndex: 0 },   // Binds to first Y-axis
  { type: 'line', data: [...], yAxisIndex: 1 }    // Binds to second Y-axis
]
```

**Important:** A single grid can hold at most 2 x-axes and 2 y-axes. For more, use `offset` to prevent overlap.

## Axis Components

### axisLine — The axis line
```javascript
axisLine: {
  show: true,
  symbol: 'arrow',           // Arrow at ends
  lineStyle: {
    color: '#999',
    width: 2,
    type: 'dashed'           // 'solid', 'dashed', 'dotted'
  }
}
```

### axisTick — Tick marks
```javascript
axisTick: {
  show: true,
  length: 6,
  lineStyle: { color: '#999', type: 'solid' }
}
```

### axisLabel — Tick labels
```javascript
axisLabel: {
  show: true,
  formatter: '{value} kg',   // Label formatter
  rotate: 45,                // Rotate labels
  align: 'center',
  interval: 'auto',          // Auto-spacing to avoid overlap
  color: '#666',
  fontSize: 12
}
```

### axisPointer — Axis indicator on hover
```javascript
axisPointer: {
  type: 'line',              // 'line', 'shadow', 'cross', 'none'
  link: [{ xAxisIndex: 'all' }]  // Link multiple axes
}
```

## Dual Y-Axis Example

```javascript
option = {
  tooltip: {},
  legend: { data: ['Temperature', 'Precipitation'] },
  xAxis: { data: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'] },
  yAxis: [
    { type: 'value', name: 'Temperature (°C)', position: 'left' },
    { type: 'value', name: 'Precipitation (mm)', position: 'right' }
  ],
  series: [
    { name: 'Temperature', type: 'bar', data: [2.0, 4.9, 7.0, 23.2, 25.6, 76.7] },
    { name: 'Precipitation', type: 'bar', data: [2.6, 5.9, 9.0, 26.4, 28.7, 70.7], yAxisIndex: 1 }
  ]
};
```

## DataZoom Integration

```javascript
dataZoom: [
  { type: 'slider', start: 0, end: 100 },   // Slider control
  { type: 'inside', start: 0, end: 100 }     // Mouse/touch zoom
]
```

## Important Notes

1. **A single grid ≤ 2 xAxes and ≤ 2 yAxes** — beyond that use `offset`
2. Series bind to axes via `xAxisIndex` and `yAxisIndex` (default: 0)
3. `xAxis.type` defaults to `'category'` when `data` is provided
4. `yAxis.type` defaults to `'value'`
