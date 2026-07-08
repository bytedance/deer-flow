# gauge-simple

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=gauge-simple
**Chart Type:** `gauge`

## User Data Requirements

Columns needed: need a single **value** (aggregate)

## Data Arrays — Complete Replacement Guide

**2 values** to set from real data:

### [0] `max` — Gauge scale maximum (default 100, must update!)

```javascript
max: 100   // ⚠️ MUST be >= data value; set to value * 1.2 rounded up
```

### [1] `data.value` — Needle position

```javascript
data: [{ value: 50, name: 'SCORE' }]
```

## Agent Workflow

1. **Query DuckDB** → aggregate value
2. **Compute max**: round up to nice number above value (e.g., 629 → 800)
3. **Replace max**: find `max: N` in the option → replace with computed max
4. **Replace data.value**: find `value: N` inside `data: [{ value: N, name: ... }]` → replace
5. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py
6. **⚠️ VERIFY**: `max >= data.value`

## Reference Code

```javascript
option = {
  tooltip: {
    formatter: '{a} <br/>{b} : {c}%'
  },
  series: [
    {
      name: 'Pressure',
      type: 'gauge',
      max: 100,
      progress: {
        show: true
      },
      detail: {
        valueAnimation: true,
        formatter: '{value}'
      },
      data: [
        {
          value: 50,
          name: 'SCORE'
        }
      ]
    }
  ]
};
```
