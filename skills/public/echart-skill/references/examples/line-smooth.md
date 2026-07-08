# line-smooth

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=line-smooth
**Chart Type:** `category`

## User Data Requirements

Columns needed: check data arrays in reference code for required format

## Data Arrays — Complete Replacement Guide

**2 array(s)** to replace with real data:

### [0] `data` (context: xAxis)
```
data: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
```

### [1] `data` (context: series)
```
data: [820, 932, 901, 934, 1290, 1330, 1320]
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
title: Smoothed Line Chart
category: line
titleCN: 基础平滑折线图
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
      data: [820, 932, 901, 934, 1290, 1330, 1320],
      type: 'line',
      smooth: true
    }
  ]
};
```
