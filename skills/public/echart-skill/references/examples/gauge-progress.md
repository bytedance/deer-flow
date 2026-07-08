# gauge-progress

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=gauge-progress
**Chart Type:** `gauge`

## User Data Requirements

Columns needed: need a single **value** (aggregate)

## Data Arrays — Complete Replacement Guide

**2 values** to set from real data:

### [0] `max` — Gauge scale maximum (default 100, must update!)

```javascript
max: 100   // ⚠️ MUST be >= data value; set to value * 1.2 rounded up
```

### [1] `data.value` — Progress value

```javascript
data: [{ value: 70 }]
```

## Agent Workflow

1. **Query DuckDB** → aggregate value
2. **Compute max**: round up to nice number above value
3. **Replace max**: find `max: N` in the option → replace
4. **Replace data.value**: `data: [{ value: N }]` → replace N
5. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py
6. **⚠️ VERIFY**: `max >= data.value`

## Reference Code

```javascript
option = {
  series: [
    {
      type: 'gauge',
      max: 100,
      progress: {
        show: true,
        width: 18
      },
      axisLine: {
        lineStyle: {
          width: 18
        }
      },
      axisTick: {
        show: false
      },
      splitLine: {
        length: 15,
        lineStyle: {
          width: 2,
          color: '#999'
        }
      },
      axisLabel: {
        distance: 25,
        color: '#999',
        fontSize: 20
      },
      anchor: {
        show: true,
        showAbove: true,
        size: 25,
        itemStyle: {
          borderWidth: 10
        }
      },
      title: {
        show: false
      },
      detail: {
        valueAnimation: true,
        fontSize: 80,
        offsetCenter: [0, '70%']
      },
      data: [
        {
          value: 70
        }
      ]
    }
  ]
};
```
