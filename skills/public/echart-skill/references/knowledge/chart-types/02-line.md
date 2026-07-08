# Line Chart 折线图

> **Source:** `echarts-docs/handbook/zh/how-to/chart-types/line/*.md`

## Basic Line Chart

```javascript
option = {
  xAxis: { type: 'category', data: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'] },
  yAxis: { type: 'value' },
  series: [{
    type: 'line',
    data: [120, 200, 150, 80, 70]
  }]
};
```

### Cartesian (XY) Line
```javascript
// Both axes are numeric — data is [x, y] pairs
series: [{
  type: 'line',
  data: [[10, 20], [20, 50], [30, 30], [40, 80]]
}]
```

## Line Styling

```javascript
series: {
  type: 'line',
  lineStyle: {
    color: '#5470c6',
    width: 2,
    type: 'dashed'        // 'solid', 'dashed', 'dotted'
  },
  itemStyle: {             // Data point styling
    color: '#fff',        // Fill
    borderColor: '#5470c6', // Border
    borderWidth: 2
  },
  symbol: 'circle',        // Point shape: 'circle','rect','triangle','diamond','emptyCircle', etc.
  symbolSize: 6,
  showSymbol: true         // false = hide points
}
```

**Note:** `lineStyle.width` does NOT change data point border width — set that in `itemStyle` separately.

## Line Variants

### Smooth Line
```javascript
series: { type: 'line', smooth: true }
```

### Step Line
```javascript
series: {
  type: 'line',
  step: 'end'       // 'start' (bend at current point), 'middle', 'end' (bend at next point)
}
```

### Stacked Line
```javascript
series: [
  { type: 'line', name: 'A', stack: 'total', data: [...] },
  { type: 'line', name: 'B', stack: 'total', data: [...] }
]
// Always add areaStyle for visual clarity:
series: [
  { type: 'line', stack: 'total', areaStyle: {}, data: [...] },
  { type: 'line', stack: 'total', areaStyle: {}, data: [...] }
]
```

### Area Line
```javascript
series: {
  type: 'line',
  areaStyle: {
    color: {
      type: 'linear',
      x: 0, y: 0, x2: 0, y2: 1,
      colorStops: [
        { offset: 0, color: 'rgba(84,112,198,0.6)' },
        { offset: 1, color: 'rgba(84,112,198,0)' }
      ]
    }
  }
}
```

## Data Labels

```javascript
series: {
  label: {
    show: true,
    position: 'top',        // 'top', 'bottom', 'left', 'right', 'inside'
    formatter: '{c}'         // {c}=value, {b}=name, {a}=series name
  },
  emphasis: {
    label: { show: true }    // Show label on hover
  }
}
```

## Null/Empty Data

Use `'-'` or `null` for missing data — the line will break at that point:

```javascript
data: [120, '-', 150, '-', 70]   // Line breaks before and after missing points
```

**Warning:** `'-'` (gap) is different from `0` — `0` connects to adjacent points.

## Common Mistakes

- Forgetting to set `areaStyle` on stacked lines (hard to distinguish otherwise)
- Setting `smooth: true` but wanting a step appearance
- Not understanding `step: 'start'` vs `'middle'` vs `'end'`
