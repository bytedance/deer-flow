# candlestick-simple

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=candlestick-simple
**Chart Type:** `candlestick`

## User Data Requirements

Columns needed: need **open/close/low/high** columns

## Data Arrays — Complete Replacement Guide

**2 `data: [...]` arrays** — ⚠️ careful not to swap them:

| # | Context | Format | Element type |
|---|---------|--------|-------------|
| 0 | `xAxis.data` | date strings | `'YYYY-MM-DD'` |
| 1 | `series[0].data` | OHLC arrays | `[open, close, low, high]` |

### [0] xAxis date labels → `data: ['2017-10-24', ...]`

```javascript
xAxis: {
  data: ['2017-10-24', '2017-10-25', '2017-10-26', '2017-10-27']
}
```

### [1] Series OHLC data → `data: [[20, 34, 10, 38], ...]`

```javascript
series: [{
  type: 'candlestick',
  data: [
    [20, 34, 10, 38],   // [open, close, low, high]
    [40, 35, 30, 50],
    [31, 38, 33, 44],
    [38, 15, 5, 42]
  ]
}]
```

## Agent Workflow

1. **Analyze** user table → identify columns for date + OHLC prices
2. **Query DuckDB** → `SELECT date, open, close, low, high FROM ...`
3. **Replace xAxis.data first**: find `xAxis: { data: [...]` → replace with date strings from query
4. **Replace series.data second**: find `series: [{ ... data: [...]` → replace with OHLC arrays from query
5. **⚠️ VERIFY**: xAxis has strings, series has number arrays — if xAxis has number arrays, you swapped them!
6. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: Basic Candlestick
category: candlestick
titleCN: 基础 K 线图
difficulty: 0
*/
option = {
  xAxis: {
    data: ['2017-10-24', '2017-10-25', '2017-10-26', '2017-10-27']
  },
  yAxis: {},
  series: [
    {
      type: 'candlestick',
      data: [
        [20, 34, 10, 38],
        [40, 35, 30, 50],
        [31, 38, 33, 44],
        [38, 15, 5, 42]
      ]
    }
  ]
};
```
