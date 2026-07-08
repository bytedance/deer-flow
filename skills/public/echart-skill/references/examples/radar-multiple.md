# radar-multiple

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=radar-multiple
**Chart Type:** `radar`

## User Data Requirements

Columns needed: need **name** + multiple **dimension** columns

## Data Arrays — Complete Replacement Guide

**6 array(s)** to replace with real data:

### [0] `data` (context: legend)
```
data: [
      'A Software',
      'A Phone',
      'Another Phone',
      'Precipitation',
      'Evaporation'
    ]
```

### [1] `data` (context: series)
```
data: [
        {
          value: [60, 73, 85, 40],
          name: 'A Software'
        }
      ]
```

### [2] `data` (context: root)
```
data: [
        {
          value: [85, 90, 90, 95, 95],
          name: 'A Phone'
        },
        {
          value: [95, 80, 95, 90, 93],
       ...
```

### [3] `data` (context: root)
```
data: [
        {
          name: 'Precipitation',
          value: [
            2.6, 5.9, 9.0, 26.4, 28.7, 70.7, 75.6, 82.2, 48.7, 18.8, 6.0, 2.3
  ...
```

### [4] `indicator` (context: legend)
```
indicator: [
        { text: 'Brand', max: 100 },
        { text: 'Content', max: 100 },
        { text: 'Usability', max: 100 },
        { text: 'Fun...
```

### [5] `indicator` (context: root)
```
indicator: [
        { text: 'Look', max: 100 },
        { text: 'Photo', max: 100 },
        { text: 'System', max: 100 },
        { text: 'Performan...
```

## Agent Workflow

1. **Analyze** user table → identify columns matching the required format above
2. **Query DuckDB** → transform to match each data array's format
3. **Replace**: use **bracket-counting** to find each `data: [...]` → replace with real data
4. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: Multiple Radar
category: radar
titleCN: 多雷达图
*/
option = {
  title: {
    text: 'Multiple Radar'
  },
  tooltip: {
    trigger: 'axis'
  },
  legend: {
    left: 'center',
    data: [
      'A Software',
      'A Phone',
      'Another Phone',
      'Precipitation',
      'Evaporation'
    ]
  },
  radar: [
    {
      indicator: [
        { text: 'Brand', max: 100 },
        { text: 'Content', max: 100 },
        { text: 'Usability', max: 100 },
        { text: 'Function', max: 100 }
      ],
      center: ['25%', '40%'],
      radius: 80
    },
    {
      indicator: [
        { text: 'Look', max: 100 },
        { text: 'Photo', max: 100 },
        { text: 'System', max: 100 },
        { text: 'Performance', max: 100 },
        { text: 'Screen', max: 100 }
      ],
      radius: 80,
      center: ['50%', '60%']
    },
    {
      indicator: (function () {
        var res = [];
        for (var i = 1; i <= 12; i++) {
          res.push({ text: i + '月', max: 100 });
        }
        return res;
      })(),
      center: ['75%', '40%'],
      radius: 80
    }
  ],
  series: [
    {
      type: 'radar',
      tooltip: {
        trigger: 'item'
      },
      areaStyle: {},
      data: [
        {
          value: [60, 73, 85, 40],
          name: 'A Software'
        }
      ]
    },
    {
      type: 'radar',
      radarIndex: 1,
      areaStyle: {},
      data: [
        {
          value: [85, 90, 90, 95, 95],
          name: 'A Phone'
        },
        {
          value: [95, 80, 95, 90, 93],
          name: 'Another Phone'
        }
      ]
    },
    {
      type: 'radar',
      radarIndex: 2,
      areaStyle: {},
      data: [
        {
          name: 'Precipitation',
          value: [
            2.6, 5.9, 9.0, 26.4, 28.7, 70.7, 75.6, 82.2, 48.7, 18.8, 6.0, 2.3
          ]
        },
        {
          name: 'Evaporation',
          value: [
            2.0, 4.9, 7.0, 23.2, 25.6, 76.7, 35.6, 62.2, 32.6, 20.0, 6.4, 3.3
          ]
        }
      ]
    }
  ]
};
```
