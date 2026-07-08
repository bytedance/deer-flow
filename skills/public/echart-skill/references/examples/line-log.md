# line-log

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=line-log
**Chart Type:** `category`

## User Data Requirements

Columns needed: check data arrays in reference code for required format

## Data Arrays — Complete Replacement Guide

**4 array(s)** to replace with real data:

### [0] `data` (context: xAxis)
```
data: ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I']
```

### [1] `data` (context: series)
```
data: [1, 3, 9, 27, 81, 247, 741, 2223, 6669]
```

### [2] `data` (context: series)
```
data: [1, 2, 4, 8, 16, 32, 64, 128, 256]
```

### [3] `data` (context: root)
```
data: [
        1 / 2,
        1 / 4,
        1 / 8,
        1 / 16,
        1 / 32,
        1 / 64,
        1 / 128,
        1 / 256,
        1 / 512...
```

## Agent Workflow

1. **Analyze** user table → identify columns matching the required format above
2. **Query DuckDB** → transform to match each data array's format
3. **Replace**: use **bracket-counting** to find each `data: [...]` → replace with real data
4. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: Log Axis
category: line
titleCN: 对数轴示例
difficulty: 7
*/
option = {
  title: {
    text: 'Log Axis',
    left: 'center'
  },
  tooltip: {
    trigger: 'item',
    formatter: '{a} <br/>{b} : {c}'
  },
  legend: {
    left: 'left'
  },
  xAxis: {
    type: 'category',
    name: 'x',
    splitLine: { show: false },
    data: ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I']
  },
  grid: {
    left: '3%',
    right: '4%',
    bottom: '3%',
    containLabel: true
  },
  yAxis: {
    type: 'log',
    name: 'y',
    minorSplitLine: {
      show: true
    }
  },
  series: [
    {
      name: 'Log2',
      type: 'line',
      data: [1, 3, 9, 27, 81, 247, 741, 2223, 6669]
    },
    {
      name: 'Log3',
      type: 'line',
      data: [1, 2, 4, 8, 16, 32, 64, 128, 256]
    },
    {
      name: 'Log1/2',
      type: 'line',
      data: [
        1 / 2,
        1 / 4,
        1 / 8,
        1 / 16,
        1 / 32,
        1 / 64,
        1 / 128,
        1 / 256,
        1 / 512
      ]
    }
  ]
};
```
