# data-transform-multiple-pie

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=data-transform-multiple-pie
**Chart Type:** `filter`

## User Data Requirements

Columns needed: check data arrays in reference code for required format

## Data Arrays — Complete Replacement Guide

**1 array(s)** to replace with real data:

### [0] `source` (context: dataset)
```
source: 
```

## Agent Workflow

1. **Analyze** user table → identify columns matching the required format above
2. **Query DuckDB** → transform to match each data array's format
3. **Replace**: use **bracket-counting** to find each `data: [...]` → replace with real data
4. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: Partition Data to Pies
category: dataset, pie, transform
titleCN: 分割数据到数个饼图
difficulty: 3
*/
option = {
  dataset: [
    {
      source: [
        ['Product', 'Sales', 'Price', 'Year'],
        ['Cake', 123, 32, 2011],
        ['Cereal', 231, 14, 2011],
        ['Tofu', 235, 5, 2011],
        ['Dumpling', 341, 25, 2011],
        ['Biscuit', 122, 29, 2011],
        ['Cake', 143, 30, 2012],
        ['Cereal', 201, 19, 2012],
        ['Tofu', 255, 7, 2012],
        ['Dumpling', 241, 27, 2012],
        ['Biscuit', 102, 34, 2012],
        ['Cake', 153, 28, 2013],
        ['Cereal', 181, 21, 2013],
        ['Tofu', 395, 4, 2013],
        ['Dumpling', 281, 31, 2013],
        ['Biscuit', 92, 39, 2013],
        ['Cake', 223, 29, 2014],
        ['Cereal', 211, 17, 2014],
        ['Tofu', 345, 3, 2014],
        ['Dumpling', 211, 35, 2014],
        ['Biscuit', 72, 24, 2014]
      ]
    },
    {
      transform: {
        type: 'filter',
        config: { dimension: 'Year', value: 2011 }
      }
    },
    {
      transform: {
        type: 'filter',
        config: { dimension: 'Year', value: 2012 }
      }
    },
    {
      transform: {
        type: 'filter',
        config: { dimension: 'Year', value: 2013 }
      }
    }
  ],
  series: [
    {
      type: 'pie',
      radius: 50,
      center: ['50%', '25%'],
      datasetIndex: 1
    },
    {
      type: 'pie',
      radius: 50,
      center: ['50%', '50%'],
      datasetIndex: 2
    },
    {
      type: 'pie',
      radius: 50,
      center: ['50%', '75%'],
      datasetIndex: 3
    }
  ],
  // Optional. Only for responsive layout:
  media: [
    {
      query: { minAspectRatio: 1 },
      option: {
        series: [
          { center: ['25%', '50%'] },
          { center: ['50%', '50%'] },
          { center: ['75%', '50%'] }
        ]
      }
    },
    {
      option: {
        series: [
          { center: ['50%', '25%'] },
          { center: ['50%', '50%'] },
          { center: ['50%', '75%'] }
        ]
      }
    }
  ]
};
```
