# bar-y-category

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=bar-y-category
**Chart Type:** `shadow`

## User Data Requirements

Columns needed: check data arrays in reference code for required format

## Data Arrays — Complete Replacement Guide

**3 array(s)** to replace with real data:

### [0] `data` (context: xAxis)
```
data: ['Brazil', 'Indonesia', 'USA', 'India', 'China', 'World']
```

### [1] `data` (context: series)
```
data: [18203, 23489, 29034, 104970, 131744, 630230]
```

### [2] `data` (context: series)
```
data: [19325, 23438, 31000, 121594, 134141, 681807]
```

## Agent Workflow

1. **Analyze** user table → identify columns matching the required format above
2. **Query DuckDB** → transform to match each data array's format
3. **Replace**: use **bracket-counting** to find each `data: [...]` → replace with real data
4. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: World Population
category: bar
titleCN: 世界人口总量 - 条形图
difficulty: 2
*/
option = {
  title: {
    text: 'World Population'
  },
  tooltip: {
    trigger: 'axis',
    axisPointer: {
      type: 'shadow'
    }
  },
  legend: {},
  xAxis: {
    type: 'value',
    boundaryGap: [0, 0.01]
  },
  yAxis: {
    type: 'category',
    data: ['Brazil', 'Indonesia', 'USA', 'India', 'China', 'World']
  },
  series: [
    {
      name: '2011',
      type: 'bar',
      data: [18203, 23489, 29034, 104970, 131744, 630230]
    },
    {
      name: '2012',
      type: 'bar',
      data: [19325, 23438, 31000, 121594, 134141, 681807]
    }
  ]
};
```
