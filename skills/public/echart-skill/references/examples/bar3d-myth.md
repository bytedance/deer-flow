# bar3d-myth

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=bar3d-myth
**Chart Type:** `value`

## User Data Requirements

Columns needed: check data arrays in reference code for required format

## Data Arrays — Complete Replacement Guide

**1 array(s)** to replace with real data:

### [0] `dimensions` (context: series)
```
dimensions: ['x', 'y', 'z']
```

## Agent Workflow

1. **Analyze** user table → identify columns matching the required format above
2. **Query DuckDB** → transform to match each data array's format
3. **Replace**: use **bracket-counting** to find each `data: [...]` → replace with real data
4. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: Bar3D - Myth
category: bar3D
titleCN: Bar3D - æäº
*/
var img = new Image();
var canvas = document.createElement('canvas');
var ctx = canvas.getContext('2d');
img.onload = function () {
  var width = (canvas.width = img.width);
  var height = (canvas.height = img.height);
  ctx.drawImage(img, 0, 0, width, height);
  var imgData = ctx.getImageData(0, 0, width, height);
  var data = new Float32Array((imgData.data.length / 4) * 3);
  var off = 0;
  for (var i = 0; i < imgData.data.length / 4; i++) {
    var r = imgData.data[i * 4];
    var g = imgData.data[i * 4 + 1];
    var b = imgData.data[i * 4 + 2];
    var lum = 0.2125 * r + 0.7154 * g + 0.0721 * b;
    lum = (lum - 125) / 4 + 50;
    data[off++] = i % width;
    data[off++] = height - Math.floor(i / width);
    data[off++] = lum;
  }
  myChart.setOption(
    (option = {
      tooltip: {},
      backgroundColor: '#fff',
      xAxis3D: {
        type: 'value'
      },
      yAxis3D: {
        type: 'value'
      },
      zAxis3D: {
        type: 'value',
        min: 0,
        max: 100
      },
      grid3D: {
        show: false,
        viewControl: {
          alpha: 70,
          beta: 0
        },
        postEffect: {
          enable: true,
          depthOfField: {
            enable: true,
            blurRadius: 4,
            fstop: 10
          }
          // SSAO: {
          //     enable: true
          // }
        },
        boxDepth: 100,
        boxHeight: 20,
        environment: /* Base64 data replaced — load from server */
'ROOT_PATH + '/data-gl/asset/starfield.jpg'',
        light: {
          main: {
            shadow: true,
            intensity: 2
          },
          ambientCubemap: {
            texture: /* Base64 data replaced — insert real URL here */
'PLACEHOLDER_URL',
            exposure: 2,
            diffuseIntensity: 0.2
          }
        }
      },
      series: [
        {
          type: 'bar3D',
          shading: 'lambert',
          barSize: 0.8,
          silent: true,
          dimensions: ['x', 'y', 'z'],
          itemStyle: {
            color: function (params) {
              var i = params.dataIndex;
              var r = imgData.data[i * 4] / 255;
              var g = imgData.data[i * 4 + 1] / 255;
              var b = imgData.data[i * 4 + 2] / 255;
              var lum = 0.2125 * r + 0.7154 * g + 0.0721 * b;
              r *= lum * 2;
              g *= lum * 2;
              b *= lum * 2;
              return [r, g, b, 1];
            }
          },
          data: data
        }
      ]
    })
  );
};
img.src = /* Base64 data replaced — insert real URL here */
'PLACEHOLDER_URL';
img.crossOrigin = 'Anonymous';
```
