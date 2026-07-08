# flowGL-noise

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=flowGL-noise
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
title: Flow on the cartesian
category: flowGL
titleCN: ç´è§åæ ç³»ä¸çåéåº
theme: dark
videoStart: 2000
videoEnd: 10000
*/
$.getScript(CDN_PATH + 'simplex-noise@2.4.0/simplex-noise.js').done(
  function () {
    var noise = new SimplexNoise(Math.random);
    var noise2 = new SimplexNoise(Math.random);
    function generateData() {
      var data = [];
      for (var i = 0; i <= 50; i++) {
        for (var j = 0; j <= 50; j++) {
          var dx = noise.noise2D(i / 30, j / 30);
          var dy = noise2.noise2D(i / 30, j / 30);
          var mag = Math.sqrt(dx * dx + dy * dy);
          valMax = Math.max(valMax, mag);
          valMin = Math.min(valMin, mag);
          data.push([i, j, dx, dy, mag]);
        }
      }
      return data;
    }
    var valMin = Infinity;
    var valMax = -Infinity;
    var data = generateData();
    myChart.setOption({
      visualMap: {
        show: false,
        min: valMin,
        max: valMax,
        dimension: 4,
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
      xAxis: {
        type: 'value',
        axisLine: {
          lineStyle: {
            color: '#fff'
          }
        },
        splitLine: {
          show: false,
          lineStyle: {
            color: 'rgba(255,255,255,0.2)'
          }
        }
      },
      yAxis: {
        type: 'value',
        axisLine: {
          lineStyle: {
            color: '#fff'
          }
        },
        splitLine: {
          show: false,
          lineStyle: {
            color: 'rgba(255,255,255,0.2)'
          }
        }
      },
      series: [
        {
          type: 'flowGL',
          data: data,
          particleDensity: 64,
          particleSize: 5,
          itemStyle: {
            opacity: 0.5
          }
        },
        {
          type: 'custom',
          data: data,
          encode: {
            x: 0,
            y: 0
          },
          renderItem: function (params, api) {
            var x = api.value(0),
              y = api.value(1),
              dx = api.value(2),
              dy = api.value(3);
            var start = api.coord([x - dx / 2, y - dy / 2]);
            var end = api.coord([x + dx / 2, y + dy / 2]);
            return {
              type: 'line',
              shape: {
                x1: start[0],
                y1: start[1],
                x2: end[0],
                y2: end[1]
              },
              style: {
                lineWidth: 2,
                stroke: '#fff',
                opacity: 0.2
              }
            };
          }
        }
      ]
    });
  }
);
```
