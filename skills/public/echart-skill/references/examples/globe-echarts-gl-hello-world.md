# globe-echarts-gl-hello-world

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=globe-echarts-gl-hello-world
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
title: ECharts-GL Hello World
category: globe
titleCN: ECharts GL å¥é¨
difficulty: 0
scripts: 'https://echarts.apache.org/zh/js/vendors/echarts-gl/dist/echarts-gl.min.js'
videoStart: 2000
videoEnd: 6000
*/
option = {
  backgroundColor: '#000',
  globe: {
    baseTexture: /* Base64 data replaced — load from server */
'ROOT_PATH + '/data-gl/asset/earth.jpg'',
    heightTexture: /* Base64 data replaced — insert real URL here */
'PLACEHOLDER_URL',
    displacementScale: 0.04,
    shading: 'realistic',
    environment: /* Base64 data replaced — load from server */
'ROOT_PATH + '/data-gl/asset/starfield.jpg'',
    realisticMaterial: {
      roughness: 0.9
    },
    postEffect: {
      enable: true
    },
    light: {
      main: {
        intensity: 5,
        shadow: true
      },
      ambientCubemap: {
        texture: /* Base64 data replaced — insert real URL here */
'PLACEHOLDER_URL',
        diffuseIntensity: 0.2
      }
    }
  }
};
```
