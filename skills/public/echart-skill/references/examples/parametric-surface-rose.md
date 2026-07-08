# parametric-surface-rose

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=parametric-surface-rose
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
title: Parametric Surface Rose
category: surface
titleCN: Parametric Surface Rose
*/
var sin = Math.sin;
var cos = Math.cos;
var pow = Math.pow;
var sqrt = Math.sqrt;
var cosh = Math.cosh;
var sinh = Math.sinh;
var exp = Math.exp;
var PI = Math.PI;
var square = function (x) {
  return x * x;
};
var mod2 = function (a, b) {
  var c = a % b;
  return c > 0 ? c : c + b;
};
var theta1 = -(20 / 9) * PI;
var theta2 = 15 * PI;
function getParametricEquation() {
  return {
    u: {
      min: 0,
      max: 1,
      step: 1 / 24
    },
    v: {
      min: theta1,
      max: theta2,
      step: (theta2 - theta1) / 575
    },
    x: function (x1, theta) {
      var phi = (PI / 2) * exp(-theta / (8 * PI));
      var y1 =
        1.9565284531299512 *
        square(x1) *
        square(1.2768869870150188 * x1 - 1) *
        sin(phi);
      var X =
        1 -
        square(1.25 * square(1 - mod2(3.6 * theta, 2 * PI) / PI) - 0.25) / 2;
      var r = X * (x1 * sin(phi) + y1 * cos(phi));
      return r * sin(theta);
    },
    y: function (x1, theta) {
      var phi = (PI / 2) * exp(-theta / (8 * PI));
      var y1 =
        1.9565284531299512 *
        square(x1) *
        square(1.2768869870150188 * x1 - 1) *
        sin(phi);
      var X =
        1 -
        square(1.25 * square(1 - mod2(3.6 * theta, 2 * PI) / PI) - 0.25) / 2;
      var r = X * (x1 * sin(phi) + y1 * cos(phi));
      return r * cos(theta);
    },
    z: function (x1, theta) {
      var phi = (PI / 2) * exp(-theta / (8 * PI));
      var y1 =
        1.9565284531299512 *
        square(x1) *
        square(1.2768869870150188 * x1 - 1) *
        sin(phi);
      var X =
        1 -
        square(1.25 * square(1 - mod2(3.6 * theta, 2 * PI) / PI) - 0.25) / 2;
      var r = X * (x1 * sin(phi) + y1 * cos(phi));
      return X * (x1 * cos(phi) - y1 * sin(phi));
    }
  };
}
option = {
  toolbox: {
    feature: {
      saveAsImage: {
        backgroundColor: '#111'
      }
    },
    iconStyle: {
      normal: {
        borderColor: '#fff'
      }
    },
    left: 0
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
    show: false,
    axisPointer: {
      show: false
    },
    axisLine: {
      lineStyle: {
        color: '#fff'
      }
    },
    postEffect: {
      enable: true,
      SSAO: {
        enable: true,
        radius: 10,
        intensity: 2
      },
      edge: {
        enable: true
      }
    },
    temporalSuperSampling: {
      enable: true
    },
    light: {
      main: {
        intensity: 3,
        shadow: true
      },
      ambient: {
        intensity: 0
      },
      ambientCubemap: {
        texture: /* Base64 data replaced — insert real URL here */
'PLACEHOLDER_URL',
        exposure: 0,
        diffuseIntensity: 1,
        specularIntensity: 0.5
      }
    },
    viewControl: {
      // projection: 'orthographic'
    }
  },
  series: [
    {
      type: 'surface',
      parametric: true,
      shading: 'realistic',
      silent: true,
      wireframe: {
        show: false
      },
      realisticMaterial: {
        baseTexture:
          'https://echarts.apache.org/examples/asset/get/s/data-1494250104909-SkZtfeAyZ.jpg',
        roughness: 0.7,
        metalness: 0,
        textureTiling: [200, 20]
      },
      itemStyle: {
        color: '#fff'
      },
      parametricEquation: getParametricEquation()
    }
  ]
};
```
