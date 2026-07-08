# Bar Chart 柱状图

> **Source:** `echarts-docs/handbook/zh/how-to/chart-types/bar/*.md`

## Basic Bar Chart

```javascript
option = {
  xAxis: { type: 'category', data: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'] },
  yAxis: { type: 'value' },
  series: [{ type: 'bar', data: [120, 200, 150, 80, 70] }]
};
```

### Multi-Series
```javascript
series: [
  { type: 'bar', name: 'Sales', data: [120, 200, 150, 80, 70] },
  { type: 'bar', name: 'Cost', data: [80, 120, 100, 60, 50] }
]
```

## Bar Styling

```javascript
series: {
  type: 'bar',
  itemStyle: {
    color: '#5470c6',
    borderColor: '#333',
    borderWidth: 1,
    barBorderRadius: [5, 5, 0, 0],  // Rounded top corners [tl, tr, br, bl]
    opacity: 0.8
  },
  // Background behind bars (ECharts 4.7.0+)
  showBackground: true,
  backgroundStyle: { color: 'rgba(180, 180, 180, 0.2)' }
}
```

## Bar Width & Spacing

```javascript
series: {
  type: 'bar',
  barWidth: 20,          // Fixed pixel width
  barMaxWidth: 30,       // Max width cap
  barMinHeight: 2,       // Min height for very small values
  barGap: '30%',         // Gap between bars in same category (percentage of bar width)
  barCategoryGap: '20%'  // Gap between categories
}
```

**CRITICAL:** `barGap` and `barCategoryGap` are shared across all bar series on the same coordinate system. If set on multiple bar series in the same grid, the last series' value takes effect.

## Stacked Bar Chart

```javascript
series: [
  { type: 'bar', name: 'A', stack: 'total', data: [10, 20, 30] },
  { type: 'bar', name: 'B', stack: 'total', data: [5, 15, 25] },
  { type: 'bar', name: 'C', stack: 'total', data: [8, 12, 20] }
]
// All series with same 'stack' value get stacked together
```

**Best Practice:** Use semantic `stack` values like `'total'`, `'male'`, `'female'` — not `'a'`, `'b'`.

## Waterfall Chart

ECharts has NO built-in waterfall chart type. Build it with 3 stacked bar series:

```javascript
// Three series with same stack value:
// 1. 'help' (transparent) — creates floating effect
// 2. 'positive' — increases (colored green)
// 3. 'negative' — decreases (colored red, absolute values)

series = [
  {
    name: 'help', type: 'bar', stack: 'all',
    itemStyle: { color: 'rgba(0,0,0,0)', borderColor: 'rgba(0,0,0,0)' },
    data: helpData    // Computed offsets
  },
  {
    name: 'increase', type: 'bar', stack: 'all',
    data: positiveData  // Positive values only, '-' for others
  },
  {
    name: 'decrease', type: 'bar', stack: 'all',
    data: negativeData  // |-values| for negatives, '-' for others
  }
];
```

Data preprocessing logic computes cumulative sum and splits positive/negative.

## Bar Race (Dynamic Sorting) — ECharts 5+

```javascript
option = {
  xAxis: { max: 'dataMax' },          // X-axis follows max data value
  yAxis: {
    type: 'category',
    inverse: true,                     // Top-to-bottom: largest at top
    animationDuration: 300,
    animationDurationUpdate: 300,
    max: 4                             // Show only top 5 items (0-indexed)
  },
  series: [{
    type: 'bar',
    realtimeSort: true,               // Enable live sorting
    label: { show: true, position: 'right', valueAnimation: true },
    animationDuration: 0,
    animationDurationUpdate: 3000,     // Match update interval
    animationEasing: 'linear',
    animationEasingUpdate: 'linear'
  }]
};

// Update with setInterval matching animationDurationUpdate
setInterval(() => {
  // Shift data and call setOption
  chart.setOption({ series: [{ data: newData }] });
}, 3000);
```

## Horizontal Bar (Y-Category)
```javascript
option = {
  yAxis: { type: 'category', data: [...] },
  xAxis: { type: 'value' },
  series: [{ type: 'bar', data: [...] }]
};
```

## Key Mistakes to Avoid

1. Setting `barGap` on the wrong series — must be the **last** bar series
2. Using `barWidth: '20%'` alongside `barGap` — let ECharts auto-calculate
3. Forgetting `itemStyle: { color: 'transparent' }` on waterfall helper series
4. Not matching `animationDurationUpdate` with `setInterval` frequency in bar race
