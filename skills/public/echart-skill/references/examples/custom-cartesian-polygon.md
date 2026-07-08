# custom-cartesian-polygon

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=custom-cartesian-polygon
**Chart Type:** `slider`

## User Data Requirements

Columns needed: check data arrays in reference code for required format

## Data Arrays — Complete Replacement Guide

**1 array(s)** to replace with real data:

### [0] `data` (context: legend)
```
data: ['bar', 'error']
```

## Agent Workflow

1. **Analyze** user table → identify columns matching the required format above
2. **Query DuckDB** → transform to match each data array's format
3. **Replace**: use **bracket-counting** to find each `data: [...]` → replace with real data
4. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: Custom Cartesian Polygon
titleCN: 自定义多边形图
category: custom
difficulty: 3
*/
const data = [];
const dataCount = 7;
for (let i = 0; i < dataCount; i++) {
  data.push([
    echarts.number.round(Math.random() * 100),
    echarts.number.round(Math.random() * 400)
  ]);
}
option = {
  tooltip: {
    trigger: 'axis'
  },
  legend: {
    data: ['bar', 'error']
  },
  dataZoom: [
    {
      type: 'slider',
      filterMode: 'none'
    },
    {
      type: 'inside',
      filterMode: 'none'
    }
  ],
  xAxis: {},
  yAxis: {},
  series: [
    {
      type: 'custom',
      renderItem: function (params, api) {
        if (params.context.rendered) {
          return;
        }
        params.context.rendered = true;
        let points = [];
        for (let i = 0; i < data.length; i++) {
          points.push(api.coord(data[i]));
        }
        let color = api.visual('color');
        return {
          type: 'polygon',
          transition: ['shape'],
          shape: {
            points: points
          },
          style: api.style({
            fill: color,
            stroke: echarts.color.lift(color, 0.1)
          })
        };
      },
      clip: true,
      data: data
    }
  ]
};
```
