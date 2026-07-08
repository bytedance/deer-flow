# dataset-default

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=dataset-default
**Chart Type:** `pie`

## User Data Requirements

Columns needed: need **name** + **value** columns

## Data Arrays — Complete Replacement Guide

**1 array(s)** to replace with real data:

### [0] `source` (context: legend)
```
source: [
      ['product', '2012', '2013', '2014', '2015', '2016', '2017'],
      ['Milk Tea', 86.5, 92.1, 85.7, 83.1, 73.4, 55.1],
      ['Matcha La...
```

## Agent Workflow

1. **Analyze** user table → identify columns matching the required format above
2. **Query DuckDB** → transform to match each data array's format
3. **Replace**: use **bracket-counting** to find each `data: [...]` → replace with real data
4. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: Default arrangement
category: 'dataset, pie'
titleCN: 默认 encode 设置
difficulty: 3
*/
option = {
  legend: {},
  tooltip: {},
  dataset: {
    source: [
      ['product', '2012', '2013', '2014', '2015', '2016', '2017'],
      ['Milk Tea', 86.5, 92.1, 85.7, 83.1, 73.4, 55.1],
      ['Matcha Latte', 41.1, 30.4, 65.1, 53.3, 83.8, 98.7],
      ['Cheese Cocoa', 24.1, 67.2, 79.5, 86.4, 65.2, 82.5],
      ['Walnut Brownie', 55.2, 67.1, 69.2, 72.4, 53.9, 39.1]
    ]
  },
  series: [
    {
      type: 'pie',
      radius: '20%',
      center: ['25%', '30%']
      // No encode specified, by default, it is '2012'.
    },
    {
      type: 'pie',
      radius: '20%',
      center: ['75%', '30%'],
      encode: {
        itemName: 'product',
        value: '2013'
      }
    },
    {
      type: 'pie',
      radius: '20%',
      center: ['25%', '75%'],
      encode: {
        itemName: 'product',
        value: '2014'
      }
    },
    {
      type: 'pie',
      radius: '20%',
      center: ['75%', '75%'],
      encode: {
        itemName: 'product',
        value: '2015'
      }
    }
  ]
};
```
