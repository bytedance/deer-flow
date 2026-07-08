# line-y-category

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=line-y-category
**Chart Type:** `value`

## User Data Requirements

Columns needed: check data arrays in reference code for required format

## Data Arrays — Complete Replacement Guide

**3 array(s)** to replace with real data:

### [0] `data` (context: legend)
```
data: ['Altitude (km) vs. temperature (°C)']
```

### [1] `data` (context: yAxis)
```
data: ['0', '10', '20', '30', '40', '50', '60', '70', '80']
```

### [2] `data` (context: root)
```
data: [15, -50, -56.5, -46.5, -22.1, -2.5, -27.7, -55.7, -76.5]
```

## Agent Workflow

1. **Analyze** user table → identify columns matching the required format above
2. **Query DuckDB** → transform to match each data array's format
3. **Replace**: use **bracket-counting** to find each `data: [...]` → replace with real data
4. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: Line Y Category
category: line
titleCN: 垂直折线图（Y轴为类目轴）
difficulty: 8
*/
option = {
  legend: {
    data: ['Altitude (km) vs. temperature (°C)']
  },
  tooltip: {
    trigger: 'axis',
    formatter: 'Temperature : <br/>{b}km : {c}°C'
  },
  grid: {
    left: '3%',
    right: '4%',
    bottom: '3%',
    containLabel: true
  },
  xAxis: {
    type: 'value',
    axisLabel: {
      formatter: '{value} °C'
    }
  },
  yAxis: {
    type: 'category',
    axisLine: { onZero: false },
    axisLabel: {
      formatter: '{value} km'
    },
    boundaryGap: false,
    data: ['0', '10', '20', '30', '40', '50', '60', '70', '80']
  },
  series: [
    {
      name: 'Altitude (km) vs. temperature (°C)',
      type: 'line',
      symbolSize: 10,
      symbol: 'circle',
      smooth: true,
      lineStyle: {
        width: 3,
        shadowColor: 'rgba(0,0,0,0.3)',
        shadowBlur: 10,
        shadowOffsetY: 8
      },
      data: [15, -50, -56.5, -46.5, -22.1, -2.5, -27.7, -55.7, -76.5]
    }
  ]
};
```
