# matrix-simple

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=matrix-simple
**Chart Type:** `continuous`

## User Data Requirements

Columns needed: check data arrays in reference code for required format

## Data Arrays — Complete Replacement Guide

**5 array(s)** to replace with real data:

### [0] `data` (context: root)
```
data: [
        {
          value: 'A',
          children: [
            'A1',
            'A2',
            {
              value: 'A3',
           ...
```

### [1] `data` (context: root)
```
data: ['U', 'V']
```

### [2] `data` (context: series)
```
data: [
      ['A1', 'U', 10],
      ['A1', 'V', 20],
      ['A2', 'U', 30],
      ['A2', 'V', 40],
      ['A31', 'U', 50],
      ['A3', 'V', 60]
    ...
```

### [3] `children` (context: root)
```
children: [
            'A1',
            'A2',
            {
              value: 'A3',
              children: ['A31', 'A32']
            }
        ...
```

### [4] `children` (context: root)
```
children: ['A31', 'A32']
```

## Agent Workflow

1. **Analyze** user table → identify columns matching the required format above
2. **Query DuckDB** → transform to match each data array's format
3. **Replace**: use **bracket-counting** to find each `data: [...]` → replace with real data
4. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: Simple Matrix
category: matrix
titleCN: 简单的矩阵图
difficulty: 1
since: 6.0.0
*/
option = {
  matrix: {
    x: {
      data: [
        {
          value: 'A',
          children: [
            'A1',
            'A2',
            {
              value: 'A3',
              children: ['A31', 'A32']
            }
          ]
        }
      ]
    },
    y: {
      data: ['U', 'V']
    },
    top: 150,
    bottom: 150
  },
  visualMap: {
    type: 'continuous',
    min: 0,
    max: 80,
    top: 'middle',
    dimension: 2,
    calculable: true
  },
  series: {
    type: 'heatmap',
    coordinateSystem: 'matrix',
    data: [
      ['A1', 'U', 10],
      ['A1', 'V', 20],
      ['A2', 'U', 30],
      ['A2', 'V', 40],
      ['A31', 'U', 50],
      ['A3', 'V', 60]
    ],
    label: {
      show: true
    }
  }
};
```
