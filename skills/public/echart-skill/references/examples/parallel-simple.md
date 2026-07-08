# parallel-simple

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=parallel-simple
**Chart Type:** `category`

## User Data Requirements

Columns needed: check data arrays in reference code for required format

## Data Arrays — Complete Replacement Guide

**2 array(s)** to replace with real data:

### [0] `data` (context: parallelAxis)
```
data: ['Excellent', 'Good', 'OK', 'Bad']
```

### [1] `data` (context: series)
```
data: [
      [12.99, 100, 82, 'Good'],
      [9.99, 80, 77, 'OK'],
      [20, 120, 60, 'Excellent']
    ]
```

## Agent Workflow

1. **Analyze** user table → identify columns matching the required format above
2. **Query DuckDB** → transform to match each data array's format
3. **Replace xAxis.data first** (strings), then **series.data** (numbers) — ⚠️ do NOT swap!
4. **⚠️ VERIFY**: xAxis has string labels, series has numbers; BOTH must have same length
5. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: Basic Parallel
category: parallel
titleCN: 基础平行坐标
difficulty: 1
*/
option = {
  parallelAxis: [
    { dim: 0, name: 'Price' },
    { dim: 1, name: 'Net Weight' },
    { dim: 2, name: 'Amount' },
    {
      dim: 3,
      name: 'Score',
      type: 'category',
      data: ['Excellent', 'Good', 'OK', 'Bad']
    }
  ],
  series: {
    type: 'parallel',
    lineStyle: {
      width: 4
    },
    data: [
      [12.99, 100, 82, 'Good'],
      [9.99, 80, 77, 'OK'],
      [20, 120, 60, 'Excellent']
    ]
  }
};
```
