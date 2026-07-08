# sphere-parametric-surface

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=sphere-parametric-surface
**Chart Type:** `surface`

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
title: Sphere Parametric Surface
category: surface
titleCN: Sphere Parametric Surface
*/
option = {
  tooltip: {},
  visualMap: {
    show: false,
    dimension: 2,
    min: -1,
    max: 1,
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
  xAxis3D: {},
  yAxis3D: {},
  zAxis3D: {},
  grid3D: {},
  series: [
    {
      type: 'surface',
      parametric: true,
      // shading: 'albedo',
      parametricEquation: {
        u: {
          min: -Math.PI,
          max: Math.PI,
          step: Math.PI / 20
        },
        v: {
          min: 0,
          max: Math.PI,
          step: Math.PI / 20
        },
        x: function (u, v) {
          return Math.sin(v) * Math.sin(u);
        },
        y: function (u, v) {
          return Math.sin(v) * Math.cos(u);
        },
        z: function (u, v) {
          return Math.cos(v);
        }
      }
    }
  ]
};
```
