# line-marker

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=line-marker
**Chart Type:** `category`

## User Data Requirements

Columns needed: check data arrays in reference code for required format

## Data Arrays — Complete Replacement Guide

**7 array(s)** to replace with real data:

### [0] `data` (context: xAxis)
```
data: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
```

### [1] `data` (context: series)
```
data: [10, 11, 13, 11, 12, 12, 9]
```

### [2] `data` (context: series)
```
data: [
          { type: 'max', name: 'Max' },
          { type: 'min', name: 'Min' }
        ]
```

### [3] `data` (context: markLine)
```
data: [{ type: 'average', name: 'Avg' }]
```

### [4] `data` (context: markLine)
```
data: [1, -2, 2, 5, 3, 2, 0]
```

### [5] `data` (context: markLine)
```
data: [{ name: '周最低', value: -2, xAxis: 1, yAxis: -1.5 }]
```

### [6] `data` (context: xAxis)
```
data: [
          { type: 'average', name: 'Avg' },
          [
            {
              symbol: 'none',
              x: '90%',
              yAxi...
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
title: Temperature Change in the Coming Week
category: line
titleCN: 未来一周气温变化
difficulty: 2
*/
option = {
  title: {
    text: 'Temperature Change in the Coming Week'
  },
  tooltip: {
    trigger: 'axis'
  },
  legend: {},
  toolbox: {
    show: true,
    feature: {
      dataZoom: {
        yAxisIndex: 'none'
      },
      dataView: { readOnly: false },
      magicType: { type: ['line', 'bar'] },
      restore: {},
      saveAsImage: {}
    }
  },
  xAxis: {
    type: 'category',
    boundaryGap: false,
    data: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
  },
  yAxis: {
    type: 'value',
    axisLabel: {
      formatter: '{value} °C'
    }
  },
  series: [
    {
      name: 'Highest',
      type: 'line',
      data: [10, 11, 13, 11, 12, 12, 9],
      markPoint: {
        data: [
          { type: 'max', name: 'Max' },
          { type: 'min', name: 'Min' }
        ]
      },
      markLine: {
        data: [{ type: 'average', name: 'Avg' }]
      }
    },
    {
      name: 'Lowest',
      type: 'line',
      data: [1, -2, 2, 5, 3, 2, 0],
      markPoint: {
        data: [{ name: '周最低', value: -2, xAxis: 1, yAxis: -1.5 }]
      },
      markLine: {
        data: [
          { type: 'average', name: 'Avg' },
          [
            {
              symbol: 'none',
              x: '90%',
              yAxis: 'max'
            },
            {
              symbol: 'circle',
              label: {
                position: 'start',
                formatter: 'Max'
              },
              type: 'max',
              name: '最高点'
            }
          ]
        ]
      }
    }
  ]
};
```
