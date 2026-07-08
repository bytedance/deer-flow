# stacked-bar3d

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=stacked-bar3d
**Chart Type:** `bar3D`

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
title: Stacked Bar3D
category: bar3D
titleCN: ä¸ç»´å å æ±ç¶å¾
*/
$.getScript(CDN_PATH + 'simplex-noise@2.4.0/simplex-noise.js').done(
  function () {
    function generateData() {
      var data = [];
      var noise = new SimplexNoise(Math.random);
      for (var i = 0; i <= 10; i++) {
        for (var j = 0; j <= 10; j++) {
          var value = noise.noise2D(i / 5, j / 5);
          data.push([i, j, value * 2 + 4]);
        }
      }
      return data;
    }
    var series = [];
    for (var i = 0; i < 10; i++) {
      series.push({
        type: 'bar3D',
        data: generateData(),
        stack: 'stack',
        shading: 'lambert',
        emphasis: {
          label: {
            show: false
          }
        }
      });
    }
    myChart.setOption({
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
          // autoRotate: true
        },
        light: {
          main: {
            shadow: true,
            quality: 'ultra',
            intensity: 1.5
          }
        }
      },
      series: series
    });
  }
);
```
