# iron-globe

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=iron-globe
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
title: Iron globe
category: globe
titleCN: éè´¨æå°ç
*/
option = {
  backgroundColor: '#000',
  globe: {
    baseTexture: /* Base64 data replaced — load from server */
'ROOT_PATH + '/data-gl/asset/earth.jpg'',
    heightTexture: /* Base64 data replaced — load from server */
'ROOT_PATH + '/data-gl/asset/earth.jpg'',
    displacementScale: 0.2,
    shading: 'realistic',
    environment: /* Base64 data replaced — load from server */
'ROOT_PATH + '/data-gl/asset/starfield.jpg'',
    realisticMaterial: {
      roughness: 'https://echarts.apache.org/examples/asset/get/s/data-1497599804873-H1SHkG-mZ.jpg',
      metalness: 'https://echarts.apache.org/examples/asset/get/s/data-1497599800643-BJbHyGWQW.jpg',
      textureTiling: [8, 4]
    },
    postEffect: {
      enable: true
    },
    viewControl: {
      autoRotate: false
    },
    light: {
      main: {
        intensity: 2,
        shadow: true
      },
      ambientCubemap: {
        texture: /* Base64 data replaced — load from server */
'ROOT_PATH + '/data-gl/asset/earth.jpg'',
        exposure: 2,
        diffuseIntensity: 2,
        specularIntensity: 2
      }
    }
  }
};
```
