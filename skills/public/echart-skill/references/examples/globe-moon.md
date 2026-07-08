# globe-moon

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=globe-moon
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
title: Moon
category: globe
titleCN: æç
*/
option = {
  globe: {
    baseTexture: /* Base64 data replaced — load from server */
'ROOT_PATH + '/data-gl/asset/moon-base.jpg'',
    heightTexture: /* Base64 data replaced — load from server */
'ROOT_PATH + '/data-gl/asset/moon-bump.jpg'',
    displacementScale: 0.05,
    displacementQuality: 'medium',
    environment: /* Base64 data replaced — load from server */
'ROOT_PATH + '/data-gl/asset/starfield.jpg'',
    shading: 'realistic',
    realisticMaterial: {
      roughness: 0.8,
      metalness: 0
    },
    postEffect: {
      enable: true,
      SSAO: {
        enable: true,
        radius: 2,
        intensity: 1,
        quality: 'high'
      }
    },
    temporalSuperSampling: {
      enable: true
    },
    light: {
      ambient: {
        intensity: 0
      },
      main: {
        intensity: 2,
        shadow: true
      },
      ambientCubemap: {
        texture: /* Base64 data replaced — insert real URL here */
'PLACEHOLDER_URL',
        exposure: 0,
        diffuseIntensity: 0.02
      }
    },
    viewControl: {
      autoRotate: false
    }
  },
  series: []
};
```
