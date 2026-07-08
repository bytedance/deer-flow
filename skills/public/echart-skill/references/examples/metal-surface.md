# metal-surface

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=metal-surface
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
title: Metal Surface
category: surface
titleCN: Metal Surface
*/
var sin = Math.sin;
var cos = Math.cos;
var pow = Math.pow;
var sqrt = Math.sqrt;
var cosh = Math.cosh;
var sinh = Math.sinh;
var PI = Math.PI;
var aa = 0.4;
var r = 1 - aa * aa;
var w = sqrt(r);
option = {
  tooltip: {},
  visualMap: {
    show: false,
    dimension: 2,
    min: -5,
    max: 5,
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
  grid3D: {
    show: false,
    postEffect: {
      enable: true,
      SSAO: {
        enable: true,
        radius: 4,
        quality: 'high',
        intensity: 1.5
      }
    },
    temporalSuperSampling: {
      enable: true
    },
    light: {
      main: {
        intensity: 2,
        shadow: true
      },
      ambient: {
        intensity: 0
      },
      ambientCubemap: {
        texture: /* Base64 data replaced — load from server */
'ROOT_PATH + '/data-gl/asset/leather/leather_roughness.jpg'',
        exposure: 2,
        diffuseIntensity: 0.2,
        specularIntensity: 3
      }
    }
  },
  series: [
    {
      type: 'surface',
      parametric: true,
      silent: true,
      wireframe: {
        show: false
      },
      shading: 'realistic',
      realisticMaterial: {
        roughness: 0.2,
        metalness: 1
      },
      parametricEquation: {
        u: {
          min: -13.2,
          max: 13.2,
          step: 0.2
        },
        v: {
          min: -37.4,
          max: 37.4,
          step: 0.2
        },
        x: function (u, v) {
          var denom = aa * (pow(w * cosh(aa * u), 2) + aa * pow(sin(w * v), 2));
          return -u + (2 * r * cosh(aa * u) * sinh(aa * u)) / denom;
        },
        y: function (u, v) {
          var denom = aa * (pow(w * cosh(aa * u), 2) + aa * pow(sin(w * v), 2));
          return (
            (2 *
              w *
              cosh(aa * u) *
              (-(w * cos(v) * cos(w * v)) - sin(v) * sin(w * v))) /
            denom
          );
        },
        z: function (u, v) {
          var denom = aa * (pow(w * cosh(aa * u), 2) + aa * pow(sin(w * v), 2));
          return (
            (2 *
              w *
              cosh(aa * u) *
              (-(w * sin(v) * cos(w * v)) + cos(v) * sin(w * v))) /
            denom
          );
        }
      }
    }
  ]
};
```
