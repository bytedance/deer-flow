# cycle-plot

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=cycle-plot
**Chart Type:** `polyline`

## User Data Requirements

Columns needed: check data arrays in reference code for required format

## Data Arrays — Complete Replacement Guide

**1 array(s)** to replace with real data:

### [0] `data` (context: legend)
```
data: ['Trend by year (2002 - 2012)', 'Average']
```

## Agent Workflow

1. **Analyze** user table → identify columns matching the required format above
2. **Query DuckDB** → transform to match each data array's format
3. **Replace**: use **bracket-counting** to find each `data: [...]` → replace with real data
4. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: Cycle Plot
category: custom
titleCN: 周期图
difficulty: 3
*/
// prettier-ignore
var rawData = [
    [2002, 14, 21, 25, 21, 26, 32, 27, 20, 10, 11, 5, 5],
    [2003, 18, 24, 28, 24, 33, 37, 30, 25, 13, 14, 6, 6],
    [2004, 22, 31, 36, 28, 37, 43, 35, 30, 13, 13, 7, 7],
    [2005, 25, 32, 38, 34, 39, 48, 38, 29, 14, 14, 8, 8],
    [2006, 29, 38, 47, 33, 44, 57, 41, 39, 16, 16, 9, 8],
    [2007, 29, 35, 49, 34, 43, 57, 41, 37, 20, 17, 9, 10],
    [2008, 22, 32, 37, 30, 35, 44, 38, 31, 16, 17, 8, 7],
    [2009, 25, 34, 41, 33, 39, 47, 44, 32, 17, 17, 9, 8],
    [2010, 26, 35, 46, 40, 47, 61, 47, 41, 20, 18, 9, 10],
    [2011, 29, 39, 55, 38, 55, 67, 53, 41, 19, 20, 11, 11],
    [2012, 38, 48, 60, 49, 57, 79, 62, 54, 26, 26, 13, 11]
];
var dataByMonth = [];
// prettier-ignore
var months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
rawData.forEach(function (entry, yearIndex) {
  entry.forEach(function (value, index) {
    if (index) {
      var monthIndex = index - 1;
      var monthItem = (dataByMonth[monthIndex] = dataByMonth[monthIndex] || []);
      monthItem[0] = monthIndex;
      monthItem[yearIndex + 1] = value;
    }
  });
});
var averageByMonth = [];
dataByMonth.forEach(function (entry, index) {
  var sum = 0;
  entry.forEach(function (value, index) {
    index && (sum += value);
  });
  averageByMonth.push([index, sum / (entry.length - 1)]);
});
function renderTrendItem(params, api) {
  var categoryIndex = api.value(0);
  var unitBandWidth = (api.size([0, 0])[0] * 0.85) / (rawData.length - 1);
  var points = rawData.map(function (entry, index) {
    var value = api.value(index + 1);
    var point = api.coord([categoryIndex, value]);
    point[0] += unitBandWidth * (index - rawData.length / 2);
    return point;
  });
  return {
    type: 'polyline',
    transition: ['shape'],
    shape: {
      points: points
    },
    style: api.style({
      fill: null,
      stroke: api.visual('color'),
      lineWidth: 2
    })
  };
}
function renderAverageItem(param, api) {
  var bandWidth = api.size([0, 0])[0] * 0.85;
  var point = api.coord([api.value(0), api.value(1)]);
  return {
    type: 'line',
    transition: ['shape'],
    shape: {
      x1: point[0] - bandWidth / 2,
      x2: point[0] + bandWidth / 2,
      y1: point[1],
      y2: point[1]
    },
    style: api.style({
      fill: null,
      stroke: api.visual('color'),
      lineWidth: 2
    })
  };
}
option = {
  tooltip: {},
  title: {
    text: 'Sales Trends by Year within Each Month',
    subtext: 'Sample of Cycle Plot',
    left: 'center'
  },
  legend: {
    top: 70,
    data: ['Trend by year (2002 - 2012)', 'Average']
  },
  dataZoom: [
    {
      type: 'slider',
      labelFormatter: ''
    },
    {
      type: 'inside'
    }
  ],
  grid: {
    bottom: 70,
    top: 120
  },
  xAxis: {
    data: months
  },
  yAxis: {
    boundaryGap: [0, '20%']
  },
  series: [
    {
      type: 'custom',
      name: 'Average',
      renderItem: renderAverageItem,
      encode: {
        x: 0,
        y: 1
      },
      data: averageByMonth
    },
    {
      type: 'custom',
      name: 'Trend by year (2002 - 2012)',
      renderItem: renderTrendItem,
      encode: {
        x: 0,
        y: rawData.map(function (entry, index) {
          return index + 1;
        })
      },
      data: dataByMonth
    }
  ]
};
```
