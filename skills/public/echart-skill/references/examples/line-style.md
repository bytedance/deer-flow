# line-style

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=line-style
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
data: [120, 200, 150, 80, 70, 110, 130]
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
title: Line Style and Item Style
category: line
titleCN: 自定义折线图样式
difficulty: 6
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
      data: [120, 200, 150, 80, 70, 110, 130],
      type: 'line',
      symbol: 'triangle',
      symbolSize: 20,
      lineStyle: {
        color: '#5470C6',
        width: 4,
        type: 'dashed'
      },
      itemStyle: {
        borderWidth: 3,
        borderColor: '#EE6666',
        color: 'yellow'
      }
    }
  ]
};
```
