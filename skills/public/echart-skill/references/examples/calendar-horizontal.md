# calendar-horizontal

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=calendar-horizontal
**Chart Type:** `heatmap`

## User Data Requirements

Columns needed: need **x**, **y**, **value** columns

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
title: Calendar Heatmap Horizontal
category: calendar
titleCN: 横向日历图
shotWidth: 900
difficulty: 2
*/
function getVirtualData(year) {
  const date = +echarts.time.parse(year + '-01-01');
  const end = +echarts.time.parse(+year + 1 + '-01-01');
  const dayTime = 3600 * 24 * 1000;
  const data = [];
  for (let time = date; time < end; time += dayTime) {
    data.push([
      echarts.time.format(time, '{yyyy}-{MM}-{dd}', false),
      Math.floor(Math.random() * 1000)
    ]);
  }
  return data;
}
option = {
  tooltip: {
    position: 'top'
  },
  visualMap: {
    min: 0,
    max: 1000,
    calculable: true,
    orient: 'horizontal',
    left: 'center',
    top: 'top'
  },
  calendar: [
    {
      range: '2017',
      cellSize: ['auto', 20]
    },
    {
      top: 260,
      range: '2016',
      cellSize: ['auto', 20]
    },
    {
      top: 450,
      range: '2015',
      cellSize: ['auto', 20],
      right: 5
    }
  ],
  series: [
    {
      type: 'heatmap',
      coordinateSystem: 'calendar',
      calendarIndex: 0,
      data: getVirtualData('2017')
    },
    {
      type: 'heatmap',
      coordinateSystem: 'calendar',
      calendarIndex: 1,
      data: getVirtualData('2016')
    },
    {
      type: 'heatmap',
      coordinateSystem: 'calendar',
      calendarIndex: 2,
      data: getVirtualData('2015')
    }
  ]
};
```
