# line3d-orthographic

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=line3d-orthographic
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
title: Line3D - Orthographic Projection
category: line3D
titleCN: ä¸ç»´æçº¿å¾ - æ­£äº¤æå½±
*/
var data = [];
// Parametric curve
for (var t = 0; t < 25; t += 0.001) {
  var x = (1 + 0.25 * Math.cos(75 * t)) * Math.cos(t);
  var y = (1 + 0.25 * Math.cos(75 * t)) * Math.sin(t);
  var z = t + 2.0 * Math.sin(75 * t);
  data.push([x, y, z]);
}
console.log(data.length);
option = {
  tooltip: {},
  backgroundColor: '#fff',
  visualMap: {
    show: false,
    dimension: 2,
    min: 0,
    max: 30,
    inRange: {
      color: [
        '#313695',
        '#4575b4',
        '#74add1',
        '#abd9e9',
        '#e0f3f8',
        '#ffffbf',
        '#fee090',
        '#fdae61',
        '#f46d43',
        '#d73027',
        '#a50026'
      ]
    }
  },
  xAxis3D: {
    type: 'value'
  },
  yAxis3D: {
    type: 'value'
  },
  zAxis3D: {
    type: 'value'
  },
  grid3D: {
    viewControl: {
      projection: 'orthographic'
    }
  },
  series: [
    {
      type: 'line3D',
      data: data,
      lineStyle: {
        width: 4
      }
    }
  ]
};
```
