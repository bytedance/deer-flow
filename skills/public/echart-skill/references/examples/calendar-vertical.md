# calendar-vertical

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=calendar-vertical
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
title: Calendar Heatmap Vertical
category: 'calendar, heatmap'
titleCN: 纵向日历图
shotWidth: 900
difficulty: 1
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
    position: 'top',
    formatter: function (p) {
      const format = echarts.time.format(p.data[0], '{yyyy}-{MM}-{dd}', false);
      return format + ': ' + p.data[1];
    }
  },
  visualMap: {
    min: 0,
    max: 1000,
    calculable: true,
    orient: 'vertical',
    left: '670',
    top: 'center'
  },
  calendar: [
    {
      orient: 'vertical',
      range: '2015'
    },
    {
      left: 300,
      orient: 'vertical',
      range: '2016'
    },
    {
      left: 520,
      cellSize: [20, 'auto'],
      bottom: 10,
      orient: 'vertical',
      range: '2017',
      dayLabel: {
        margin: 5
      }
    }
  ],
  series: [
    {
      type: 'heatmap',
      coordinateSystem: 'calendar',
      calendarIndex: 0,
      data: getVirtualData('2015')
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
      data: getVirtualData('2017')
    }
  ]
};
```
