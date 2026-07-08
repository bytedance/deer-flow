# gauge

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=gauge
**Chart Type:** `gauge`

## User Data Requirements

Columns needed: need a single **value** (aggregate)

## Data Arrays — Complete Replacement Guide

**2 values** to set from real data:

### [0] `max` — Gauge scale maximum

```javascript
max: 100   // ⚠️ MUST be >= data value; set to value * 1.2 rounded up
```

### [1] `data.value` — Needle position

```javascript
data: [{ value: 50, name: 'SCORE' }]
```

## Agent Workflow

1. **Query DuckDB** → aggregate value (e.g., `SELECT SUM(amount) FROM sales`)
2. **Compute max**: `Math.ceil(value * 1.2 / 10) * 10` (nice round number above value)
3. **Replace max**: find `max: N` in the option → replace with computed max
4. **Replace data.value**: find `value: N` inside `data: [{ value: N, name: ... }]` → replace
5. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py
6. **⚠️ VERIFY**: `max >= data.value` — if value > max, you forgot to update max!

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
      detail: {
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
