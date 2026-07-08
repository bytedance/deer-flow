# surface-wave

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=surface-wave
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
title: Surface Wave
category: surface
titleCN: Surface Wave
*/
option = {
  tooltip: {},
  backgroundColor: '#fff',
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
  xAxis3D: {
    type: 'value'
  },
  yAxis3D: {
    type: 'value'
  },
  zAxis3D: {
    type: 'value',
    max: 1,
    splitNumber: 2
  },
  grid3D: {
    viewControl: {
      // projection: 'orthographic'
    },
    boxHeight: 40
  },
  series: [
    {
      type: 'surface',
      wireframe: {
        show: false
      },
      shading: 'color',
      equation: {
        x: {
          step: 0.05,
          min: -3,
          max: 3
        },
        y: {
          step: 0.05,
          min: -3,
          max: 3
        },
        z: function (x, y) {
          return (Math.sin(x * x + y * y) * x) / 3.14;
        }
      }
    }
  ]
};
```
