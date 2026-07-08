# gauge-temperature

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=gauge-temperature
**Chart Type:** `gauge`

## User Data Requirements

Columns needed: need a temperature **value**

## Data Arrays — Complete Replacement Guide

**3 values** to set from real data:

### [0] `max` — Both series share the same scale (currently 60)

```javascript
max: 60   // ⚠️ MUST be >= data value; set based on temperature range
```

### [1] `data.value` — Temperature value (both series share same value)

```javascript
data: [{ value: 20 }]   // appears in both series[0] and series[1]
```

### [2] `setInterval` data — If using live update, update those values too

```javascript
data: [{ value: random }]   // replace `random` with real value
```

## Agent Workflow

1. **Query DuckDB** → temperature value (e.g., AVG, MAX, or latest)
2. **Compute max**: round up (e.g., 27 → 40, 85 → 100)
3. **Replace max**: find ALL occurrences of `max: 60` in option → replace
4. **Replace data.value**: find ALL `value: N` inside `data: [{ value: N }]` → replace
5. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py
6. **⚠️ VERIFY**: every `max >= data.value` in every series

## Reference Code

```javascript
option = {
  series: [
    {
      type: 'gauge',
      center: ['50%', '60%'],
      startAngle: 200,
      endAngle: -20,
      min: 0,
      max: 60,
      splitNumber: 12,
      itemStyle: { color: '#FFAB91' },
      progress: { show: true, width: 30 },
      pointer: { show: false },
      axisLine: { lineStyle: { width: 30 } },
      axisTick: { distance: -45, splitNumber: 5, lineStyle: { width: 2, color: '#999' } },
      splitLine: { distance: -52, length: 14, lineStyle: { width: 3, color: '#999' } },
      axisLabel: { distance: -20, color: '#999', fontSize: 20 },
      anchor: { show: false },
      title: { show: false },
      detail: {
        valueAnimation: true, width: '60%', lineHeight: 40,
        borderRadius: 8, offsetCenter: [0, '-15%'], fontSize: 60,
        fontWeight: 'bolder', formatter: '{value} °C', color: 'inherit'
      },
      data: [{ value: 20 }]
    },
    {
      type: 'gauge',
      center: ['50%', '60%'],
      startAngle: 200,
      endAngle: -20,
      min: 0,
      max: 60,
      itemStyle: { color: '#FD7347' },
      progress: { show: true, width: 8 },
      pointer: { show: false },
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { show: false },
      axisLabel: { show: false },
      detail: { show: false },
      data: [{ value: 20 }]
    }
  ]
};

// Optional: live update (remove if static data is sufficient)
setInterval(function () {
  const random = +(Math.random() * 60).toFixed(2);
  myChart.setOption({
    series: [
      { data: [{ value: random }] },
      { data: [{ value: random }] }
    ]
  });
}, 2000);
```
