# pictorialBar-hill

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=pictorialBar-hill
**Chart Type:** `pictorialBar`

## User Data Requirements

Columns needed: check data arrays in reference code for required format

## Data Arrays — Complete Replacement Guide

**4 array(s)** to replace with real data:

### [0] `data` (context: xAxis)
```
data: ['Christmas Wish List', '', 'Qomolangma', 'Kilimanjaro']
```

### [1] `data` (context: root)
```
data: 
```

### [2] `data` (context: markLine)
```
data: [
          {
            yAxis: 8844
          }
        ]
```

### [3] `data` (context: root)
```
data: [
        {
          value: 1,
          symbolSize: ['150%', 50]
        },
        {
          value: '-'
        },
        {
          valu...
```

## Agent Workflow

1. **Analyze** user table → identify columns matching the required format above
2. **Query DuckDB** → transform to match each data array's format
3. **Replace**: use **bracket-counting** to find each `data: [...]` → replace with real data
4. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: Wish List and Mountain Height
category: pictorialBar
titleCN: 圣诞愿望清单和山峰高度
videoStart: 0
videoEnd: 2000
*/
var paperDataURI =
  /* Base64 data replaced — insert real URL here */
'PLACEHOLDER_URL';
option = {
  backgroundColor: '#0f375f',
  tooltip: {},
  legend: {
    textStyle: { color: '#ddd' }
  },
  xAxis: [
    {
      data: ['Christmas Wish List', '', 'Qomolangma', 'Kilimanjaro'],
      axisTick: { show: false },
      axisLine: { show: false },
      axisLabel: {
        margin: 20,
        color: '#ddd',
        fontSize: 14
      }
    }
  ],
  yAxis: {
    splitLine: { show: false },
    axisTick: { show: false },
    axisLine: { show: false },
    axisLabel: { show: false }
  },
  markLine: {
    z: -1
  },
  animationEasing: 'elasticOut',
  series: [
    {
      type: 'pictorialBar',
      name: 'All',
      emphasis: {
        scale: true
      },
      label: {
        show: true,
        position: 'top',
        formatter: '{c} m',
        fontSize: 16,
        color: '#e54035'
      },
      data: [
        {
          value: 13000,
          symbol: 'image://' + paperDataURI,
          symbolRepeat: true,
          symbolSize: ['130%', '20%'],
          symbolOffset: [0, 10],
          symbolMargin: '-30%',
          animationDelay: function (dataIndex, params) {
            return params.index * 30;
          }
        },
        {
          value: '-',
          symbol: 'none'
        },
        {
          value: 8844,
          symbol:
            'image://' + /* Base64 data replaced — insert real URL here */
'PLACEHOLDER_URL',
          symbolSize: ['200%', '105%'],
          symbolPosition: 'end',
          z: 10
        },
        {
          value: 5895,
          symbol:
            'image://' + /* Base64 data replaced — insert real URL here */
'PLACEHOLDER_URL',
          symbolSize: ['200%', '105%'],
          symbolPosition: 'end'
        }
      ],
      markLine: {
        symbol: ['none', 'none'],
        label: {
          show: false
        },
        lineStyle: {
          color: '#e54035',
          width: 2
        },
        data: [
          {
            yAxis: 8844
          }
        ]
      }
    },
    {
      name: 'All',
      type: 'pictorialBar',
      barGap: '-100%',
      symbol: 'circle',
      itemStyle: {
        color: '#185491'
      },
      silent: true,
      symbolOffset: [0, '50%'],
      z: -10,
      data: [
        {
          value: 1,
          symbolSize: ['150%', 50]
        },
        {
          value: '-'
        },
        {
          value: 1,
          symbolSize: ['200%', 50]
        },
        {
          value: 1,
          symbolSize: ['200%', 50]
        }
      ]
    }
  ]
};
```
