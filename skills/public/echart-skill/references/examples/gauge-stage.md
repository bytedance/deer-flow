# gauge-stage

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=gauge-stage
**Chart Type:** `gauge`

## User Data Requirements

Columns needed: need a single **value** (aggregate)

## Data Arrays — Complete Replacement Guide

**2 values** to set from real data:

### [0] `max` — Gauge scale maximum (default 100, must update!)

```javascript
max: 100   // ⚠️ MUST be >= data value; set to value * 1.2 rounded up
```

### [1] `data.value` — Speed value

```javascript
data: [{ value: 70 }]
```

## Agent Workflow

1. **Query DuckDB** → aggregate value
2. **Compute max**: round up to nice number above value
3. **Replace max**: if no explicit `max` in option, ADD `max: N` after `type: 'gauge'`
4. **Replace data.value**: `data: [{ value: N }]` → replace N
5. **Replace setInterval value** (if present): `Math.random() * 100` → `Math.random() * MAX`
6. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py
7. **⚠️ VERIFY**: `max >= data.value`

## Reference Code

```javascript
option = {
  series: [
    {
      type: 'gauge',
      max: 100,
      axisLine: {
        lineStyle: {
          width: 30,
          color: [
            [0.3, '#67e0e3'],
            [0.7, '#37a2da'],
            [1, '#fd666d']
          ]
        }
      },
      pointer: { itemStyle: { color: 'auto' } },
      axisTick: { distance: -30, length: 8, lineStyle: { color: '#fff', width: 2 } },
      splitLine: { distance: -30, length: 30, lineStyle: { color: '#fff', width: 4 } },
      axisLabel: { color: 'inherit', distance: 40, fontSize: 20 },
      detail: {
        valueAnimation: true,
        formatter: '{value} km/h',
        color: 'inherit'
      },
      data: [{ value: 70 }]
    }
  ]
};

setInterval(function () {
  myChart.setOption({
    series: [{ data: [{ value: +(Math.random() * 100).toFixed(2) }] }]
  });
}, 2000);
```
