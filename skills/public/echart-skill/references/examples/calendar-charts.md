# calendar-charts

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=calendar-charts
**Chart Type:** `graph`

## User Data Requirements

Columns needed: need **nodes** [{name,...}] + **links/edges** [{source,target}]

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
title: Calendar Charts
category: 'calendar, scatter'
titleCN: 日历图
shotWidth: 1000
difficulty: 11
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
const graphData = [
  ['2017-02-01', 260],
  ['2017-02-04', 200],
  ['2017-02-09', 279],
  ['2017-02-13', 847],
  ['2017-02-18', 241],
  ['2017-02-23', 411],
  ['2017-02-27', 985]
];
const links = graphData.map(function (item, idx) {
  return {
    source: idx,
    target: idx + 1
  };
});
links.pop();
option = {
  tooltip: {
    position: 'top'
  },
  visualMap: [
    {
      min: 0,
      max: 1000,
      calculable: true,
      seriesIndex: [2, 3, 4],
      orient: 'horizontal',
      left: '55%',
      bottom: 20
    },
    {
      min: 0,
      max: 1000,
      inRange: {
        color: ['grey'],
        opacity: [0, 0.3]
      },
      controller: {
        inRange: {
          opacity: [0.3, 0.6]
        },
        outOfRange: {
          color: '#ccc'
        }
      },
      seriesIndex: [1],
      orient: 'horizontal',
      left: '10%',
      bottom: 20
    }
  ],
  calendar: [
    {
      orient: 'vertical',
      yearLabel: {
        margin: 40
      },
      monthLabel: {
        nameMap: 'cn',
        margin: 20
      },
      dayLabel: {
        firstDay: 1,
        nameMap: 'cn'
      },
      cellSize: 40,
      range: '2017-02'
    },
    {
      orient: 'vertical',
      yearLabel: {
        margin: 40
      },
      monthLabel: {
        margin: 20
      },
      cellSize: 40,
      left: 460,
      range: '2017-01'
    },
    {
      orient: 'vertical',
      yearLabel: {
        margin: 40
      },
      monthLabel: {
        margin: 20
      },
      cellSize: 40,
      top: 350,
      range: '2017-03'
    },
    {
      orient: 'vertical',
      yearLabel: {
        margin: 40
      },
      dayLabel: {
        firstDay: 1,
        nameMap: ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
      },
      monthLabel: {
        nameMap: 'cn',
        margin: 20
      },
      cellSize: 40,
      top: 350,
      left: 460,
      range: '2017-04'
    }
  ],
  series: [
    {
      type: 'graph',
      edgeSymbol: ['none', 'arrow'],
      coordinateSystem: 'calendar',
      links: links,
      symbolSize: 10,
      calendarIndex: 0,
      data: graphData
    },
    {
      type: 'heatmap',
      coordinateSystem: 'calendar',
      data: getVirtualData('2017')
    },
    {
      type: 'effectScatter',
      coordinateSystem: 'calendar',
      calendarIndex: 1,
      symbolSize: function (val) {
        return val[1] / 40;
      },
      data: getVirtualData('2017')
    },
    {
      type: 'scatter',
      coordinateSystem: 'calendar',
      calendarIndex: 2,
      symbolSize: function (val) {
        return val[1] / 60;
      },
      data: getVirtualData('2017')
    },
    {
      type: 'heatmap',
      coordinateSystem: 'calendar',
      calendarIndex: 3,
      data: getVirtualData('2017')
    }
  ]
};
```
