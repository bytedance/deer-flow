# line-pen

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=line-pen
**Chart Type:** `value`

## User Data Requirements

Columns needed: check data arrays in reference code for required format

## Data Arrays — Replacement Guide

The code contains **0 data array(s)** to replace:

## Agent Workflow

1. **Analyze** user table → identify columns matching the required format above
2. **Query DuckDB** → transform to match each data array's format
3. **Replace**: use **bracket-counting** to find each `data: [...]` → replace with real data
4. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: Click to Add Points
category: line
titleCN: 点击添加折线图拐点
difficulty: 9
*/
const symbolSize = 20;
const data = [
  [15, 0],
  [-50, 10],
  [-56.5, 20],
  [-46.5, 30],
  [-22.1, 40]
];
option = {
  title: {
    text: 'Click to Add Points'
  },
  tooltip: {
    formatter: function (params) {
      var data = params.data || [0, 0];
      return data[0].toFixed(2) + ', ' + data[1].toFixed(2);
    }
  },
  grid: {
    left: '3%',
    right: '4%',
    bottom: '3%',
    containLabel: true
  },
  xAxis: {
    min: -60,
    max: 20,
    type: 'value',
    axisLine: { onZero: false }
  },
  yAxis: {
    min: 0,
    max: 40,
    type: 'value',
    axisLine: { onZero: false }
  },
  series: [
    {
      id: 'a',
      type: 'line',
      smooth: true,
      symbolSize: symbolSize,
      data: data
    }
  ]
};
var zr = myChart.getZr();
zr.on('click', function (params) {
  var pointInPixel = [params.offsetX, params.offsetY];
  var pointInGrid = myChart.convertFromPixel('grid', pointInPixel);
  if (myChart.containPixel('grid', pointInPixel)) {
    data.push(pointInGrid);
    myChart.setOption({
      series: [
        {
          id: 'a',
          data: data
        }
      ]
    });
  }
});
zr.on('mousemove', function (params) {
  var pointInPixel = [params.offsetX, params.offsetY];
  zr.setCursorStyle(
    myChart.containPixel('grid', pointInPixel) ? 'copy' : 'default'
  );
});
```
