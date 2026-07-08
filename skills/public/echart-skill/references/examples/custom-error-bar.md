# custom-error-bar

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=custom-error-bar
**Chart Type:** `shadow`

## User Data Requirements

Columns needed: check data arrays in reference code for required format

## Data Arrays — Complete Replacement Guide

**2 array(s)** to replace with real data:

### [0] `data` (context: legend)
```
data: ['bar', 'error']
```

### [1] `children` (context: root)
```
children: 
```

## Agent Workflow

1. **Analyze** user table → identify columns matching the required format above
2. **Query DuckDB** → transform to match each data array's format
3. **Replace**: use **bracket-counting** to find each `data: [...]` → replace with real data
4. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: Error Bar on Catesian
category: custom
titleCN: 使用自定系列给柱状图添加误差范围
difficulty: 3
*/
var categoryData = [];
var errorData = [];
var barData = [];
var dataCount = 100;
for (var i = 0; i < dataCount; i++) {
  var val = Math.random() * 1000;
  categoryData.push('category' + i);
  errorData.push([
    i,
    echarts.number.round(Math.max(0, val - Math.random() * 100)),
    echarts.number.round(val + Math.random() * 80)
  ]);
  barData.push(echarts.number.round(val, 2));
}
option = {
  tooltip: {
    trigger: 'axis',
    axisPointer: {
      type: 'shadow'
    }
  },
  title: {
    text: 'Error bar chart'
  },
  legend: {
    data: ['bar', 'error'],
    top: 20,
    right: 30
  },
  dataZoom: [
    {
      type: 'slider',
      start: 50,
      end: 70
    },
    {
      type: 'inside',
      start: 50,
      end: 70
    }
  ],
  xAxis: {
    data: categoryData
  },
  yAxis: {},
  series: [
    {
      type: 'bar',
      name: 'bar',
      data: barData,
      itemStyle: {
        color: '#77bef7'
      }
    },
    {
      type: 'custom',
      name: 'error',
      itemStyle: {
        borderWidth: 1.5
      },
      renderItem: function (params, api) {
        var xValue = api.value(0);
        var highPoint = api.coord([xValue, api.value(1)]);
        var lowPoint = api.coord([xValue, api.value(2)]);
        var halfWidth = api.size([1, 0])[0] * 0.1;
        var style = api.style({
          stroke: api.visual('color'),
          fill: undefined
        });
        return {
          type: 'group',
          children: [
            {
              type: 'line',
              transition: ['shape'],
              shape: {
                x1: highPoint[0] - halfWidth,
                y1: highPoint[1],
                x2: highPoint[0] + halfWidth,
                y2: highPoint[1]
              },
              style: style
            },
            {
              type: 'line',
              transition: ['shape'],
              shape: {
                x1: highPoint[0],
                y1: highPoint[1],
                x2: lowPoint[0],
                y2: lowPoint[1]
              },
              style: style
            },
            {
              type: 'line',
              transition: ['shape'],
              shape: {
                x1: lowPoint[0] - halfWidth,
                y1: lowPoint[1],
                x2: lowPoint[0] + halfWidth,
                y2: lowPoint[1]
              },
              style: style
            }
          ]
        };
      },
      encode: {
        x: 0,
        y: [1, 2]
      },
      data: errorData,
      z: 100
    }
  ]
};
```
