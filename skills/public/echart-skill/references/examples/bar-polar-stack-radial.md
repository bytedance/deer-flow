# bar-polar-stack-radial

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=bar-polar-stack-radial
**Chart Type:** `category`

## User Data Requirements

Columns needed: check data arrays in reference code for required format

## Data Arrays — Complete Replacement Guide

**5 array(s)** to replace with real data:

### [0] `data` (context: angleAxis)
```
data: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
```

### [1] `data` (context: series)
```
data: [1, 2, 3, 4, 3, 5, 1]
```

### [2] `data` (context: root)
```
data: [2, 4, 6, 1, 3, 2, 1]
```

### [3] `data` (context: root)
```
data: [1, 2, 3, 4, 1, 2, 5]
```

### [4] `data` (context: legend)
```
data: ['A', 'B', 'C']
```

## Agent Workflow

1. **Analyze** user table → identify columns matching the required format above
2. **Query DuckDB** → transform to match each data array's format
3. **Replace**: use **bracket-counting** to find each `data: [...]` → replace with real data
4. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: Stacked Bar Chart on Polar(Radial)
titleCN: 极坐标系下的堆叠柱状图
category: bar
difficulty: 7
*/
option = {
  angleAxis: {
    type: 'category',
    data: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
  },
  radiusAxis: {},
  polar: {},
  series: [
    {
      type: 'bar',
      data: [1, 2, 3, 4, 3, 5, 1],
      coordinateSystem: 'polar',
      name: 'A',
      stack: 'a',
      emphasis: {
        focus: 'series'
      }
    },
    {
      type: 'bar',
      data: [2, 4, 6, 1, 3, 2, 1],
      coordinateSystem: 'polar',
      name: 'B',
      stack: 'a',
      emphasis: {
        focus: 'series'
      }
    },
    {
      type: 'bar',
      data: [1, 2, 3, 4, 1, 2, 5],
      coordinateSystem: 'polar',
      name: 'C',
      stack: 'a',
      emphasis: {
        focus: 'series'
      }
    }
  ],
  legend: {
    show: true,
    data: ['A', 'B', 'C']
  }
};
```
