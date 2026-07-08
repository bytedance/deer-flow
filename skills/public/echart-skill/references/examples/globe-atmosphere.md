# globe-atmosphere

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=globe-atmosphere
**Chart Type:** `unknown`

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
title: Globe with Atmosphere
category: globe
titleCN: å¤§æ°å±æ¾ç¤º
difficulty: 1
*/
option = {
  backgroundColor: '#000',
  globe: {
    baseTexture: /* Base64 data replaced — load from server */
'ROOT_PATH + '/data-gl/asset/world.topo.bathy.200401.jpg'',
    shading: 'lambert',
    environment: /* Base64 data replaced — load from server */
'ROOT_PATH + '/data-gl/asset/starfield.jpg'',
    atmosphere: {
      show: true
    },
    light: {
      ambient: {
        intensity: 0.1
      },
      main: {
        intensity: 1.5
      }
    }
  },
  series: []
};
```
