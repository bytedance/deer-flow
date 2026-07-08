# polar-endAngle

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=polar-endAngle
**Chart Type:** `category`

## User Data Requirements

Columns needed: check data arrays in reference code for required format

## Data Arrays — Complete Replacement Guide

**4 array(s)** to replace with real data:

### [0] `data` (context: tooltip)
```
data: ['S1', 'S2', 'S3']
```

### [1] `data` (context: root)
```
data: ['T1', 'T2', 'T3']
```

### [2] `data` (context: series)
```
data: [1, 2, 3]
```

### [3] `data` (context: series)
```
data: [1, 2, 3]
```

## Agent Workflow

1. **Analyze** user table → identify columns matching the required format above
2. **Query DuckDB** → transform to match each data array's format
3. **Replace**: use **bracket-counting** to find each `data: [...]` → replace with real data
4. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: Polar endAngle
category: bar
titleCN: 极坐标系 endAngle
difficulty: 2
*/
option = {
  tooltip: {},
  angleAxis: [
    {
      type: 'category',
      polarIndex: 0,
      startAngle: 90,
      endAngle: 0,
      data: ['S1', 'S2', 'S3']
    },
    {
      type: 'category',
      polarIndex: 1,
      startAngle: -90,
      endAngle: -180,
      data: ['T1', 'T2', 'T3']
    }
  ],
  radiusAxis: [{ polarIndex: 0 }, { polarIndex: 1 }],
  polar: [{}, {}],
  series: [
    {
      type: 'bar',
      polarIndex: 0,
      data: [1, 2, 3],
      coordinateSystem: 'polar'
    },
    {
      type: 'bar',
      polarIndex: 1,
      data: [1, 2, 3],
      coordinateSystem: 'polar'
    }
  ]
};
```
