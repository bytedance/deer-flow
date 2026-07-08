# bar-waterfall

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=bar-waterfall
**Chart Type:** `shadow`

## User Data Requirements

Columns needed: check data arrays in reference code for required format

## Data Arrays — Complete Replacement Guide

**3 array(s)** to replace with real data:

### [0] `data` (context: xAxis)
```
data: ['Total', 'Rent', 'Utilities', 'Transportation', 'Meals', 'Other']
```

### [1] `data` (context: root)
```
data: [0, 1700, 1400, 1200, 300, 0]
```

### [2] `data` (context: root)
```
data: [2900, 1200, 300, 200, 900, 300]
```

## Agent Workflow

1. **Analyze** user table → identify columns matching the required format above
2. **Query DuckDB** → transform to match each data array's format
3. **Replace**: use **bracket-counting** to find each `data: [...]` → replace with real data
4. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: Waterfall Chart
titleCN: 瀑布图（柱状图模拟）
category: bar
difficulty: 1
*/
option = {
  title: {
    text: 'Waterfall Chart',
    subtext: 'Living Expenses in Shenzhen'
  },
  tooltip: {
    trigger: 'axis',
    axisPointer: {
      type: 'shadow'
    },
    formatter: function (params) {
      var tar = params[1];
      return tar.name + '<br/>' + tar.seriesName + ' : ' + tar.value;
    }
  },
  grid: {
    left: '3%',
    right: '4%',
    bottom: '3%',
    containLabel: true
  },
  xAxis: {
    type: 'category',
    splitLine: { show: false },
    data: ['Total', 'Rent', 'Utilities', 'Transportation', 'Meals', 'Other']
  },
  yAxis: {
    type: 'value'
  },
  series: [
    {
      name: 'Placeholder',
      type: 'bar',
      stack: 'Total',
      itemStyle: {
        borderColor: 'transparent',
        color: 'transparent'
      },
      emphasis: {
        itemStyle: {
          borderColor: 'transparent',
          color: 'transparent'
        }
      },
      data: [0, 1700, 1400, 1200, 300, 0]
    },
    {
      name: 'Life Cost',
      type: 'bar',
      stack: 'Total',
      label: {
        show: true,
        position: 'inside'
      },
      data: [2900, 1200, 300, 200, 900, 300]
    }
  ]
};
```
