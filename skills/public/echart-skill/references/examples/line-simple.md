# line-simple

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=line-simple
**Chart Type:** `category`

## User Data Requirements

Columns needed: check data arrays in reference code for required format

## Data Arrays — Complete Replacement Guide

**2 `data: [...]` arrays** — ⚠️ careful: xAxis = string labels, series = numbers

| # | Context | Format | Example |
|---|---------|--------|---------|
| 0 | `xAxis.data` | string labels (category) | `['Mon','Tue','Wed','Thu','Fri','Sat','Sun']` |
| 1 | `series[0].data` | number array (values) | `[150, 230, 224, 218, 135, 147, 260]` |

## Agent Workflow

1. **Query DuckDB** → `SELECT category_col, value_col FROM ...`
2. **Replace xAxis.data first**: find `xAxis: { ... data: [...]` → replace with category strings from query
3. **Replace series.data second**: find `series: [{ ... data: [...]` → replace with numeric values from query
4. **⚠️ VERIFY**: xAxis has strings, series has numbers; both arrays have same length
5. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: Basic Line Chart
category: line
titleCN: 基础折线图
difficulty: 0
*/
option = {
  xAxis: {
    type: 'category',
    data: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
  },
  yAxis: {
    type: 'value'
  },
  series: [
    {
      data: [150, 230, 224, 218, 135, 147, 260],
      type: 'line'
    }
  ]
};
```
