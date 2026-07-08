# custom-wind

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=custom-wind
**Chart Type:** `custom`

## User Data Requirements

Columns needed: check data arrays in reference code for required format

## Data Arrays — Replacement Guide

The code contains **0 data array(s)** to replace:


## External Data Format

This example uses external data. Format from `winds.json`:

```json
[
  [
    -2.9,
    4.2
  ],
  [
    -3,
    4.1
  ],
  [
    -3,
    4.1
  ]
]
```

Agent: build DuckDB query to produce matching data structure.
## Agent Workflow

1. **Analyze** user table → identify columns matching the required format above
2. **Query DuckDB** → transform to match each data array's format
3. **Replace**: use **bracket-counting** to find each `data: [...]` → replace with real data
4. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: Use custom series to draw wind vectors
titleCN: 使用自定义系列绘制风场
category: custom
difficulty: 7
*/
function shuffle(array) {
  // https://stackoverflow.com/questions/2450954/how-to-randomize-shuffle-a-javascript-array
  var currentIndex = array.length;
  var temporaryValue;
  var randomIndex;
  // While there remain elements to shuffle...
  while (0 !== currentIndex) {
    // Pick a remaining element...
    randomIndex = Math.floor(Math.random() * currentIndex);
    currentIndex -= 1;
    // And swap it with the current element.
    temporaryValue = array[currentIndex];
    array[currentIndex] = array[randomIndex];
    array[randomIndex] = temporaryValue;
  }
  return array;
}
var windData = {
  "nx": 360,
  "ny": 181,
  "max": 28.700000762939453,
  "data": [
    [-2.9, 4.2],
    [-3, 4.1],
    [-3, 4.1],
    [-3.1, 4],
    [-3.2, 4],
    [-3.2, 3.9],
    [-3.3, 3.9],
    [-3.4, 3.8],
    // ... (65159 total entries — truncated, keep first 8 as sample. Agent: query DuckDB)
      ]
};
var p = 0;
  var maxMag = 0;
  var minMag = Infinity;
  var data = [];
  for (var j = 0; j < windData.ny; j++) {
    for (var i = 0; i < windData.nx; i++, p++) {
      var vx = windData.data[p][0];
      var vy = windData.data[p][1];
      var mag = Math.sqrt(vx * vx + vy * vy);
      // 数据是一个一维数组
      // [ [经度, 维度，向量经度方向的值，向量维度方向的值] ]
      data.push([
        (i / windData.nx) * 360 - 180,
        (j / windData.ny) * 180 - 90,
        vx,
        vy,
        mag
      ]);
      maxMag = Math.max(mag, maxMag);
      minMag = Math.min(mag, minMag);
    }
  }
  shuffle(data);
  myChart.setOption(
    (option = {
      backgroundColor: '#333',
      visualMap: {
        left: 'center',
        min: minMag,
        max: maxMag,
        dimension: 4,
        inRange: {
          // prettier-ignore
          color: ['#313695', '#4575b4', '#74add1', '#abd9e9', '#e0f3f8', '#ffffbf', '#fee090', '#fdae61', '#f46d43', '#d73027', '#a50026']
        },
        calculable: true,
        textStyle: {
          color: '#fff'
        },
        orient: 'horizontal'
      },
      geo: {
        map: 'world',
        left: 0,
        right: 0,
        top: 0,
        zoom: 1,
        silent: true,
        roam: true,
        itemStyle: {
          areaColor: '#323c48',
          borderColor: '#111'
        }
      },
      series: {
        type: 'custom',
        coordinateSystem: 'geo',
        data: data,
        encode: {
          x: 0,
          y: 0
        },
        renderItem: function (params, api) {
          const x = api.value(0);
          const y = api.value(1);
          const dx = api.value(2);
          const dy = api.value(3);
          const start = api.coord([
            Math.max(x - dx / 5, -180),
            Math.max(y - dy / 5, -90)
          ]);
          const end = api.coord([
            Math.min(x + dx / 5, 180),
            Math.min(y + dy / 5, 90)
          ]);
          return {
            type: 'line',
            shape: {
              x1: start[0],
              y1: start[1],
              x2: end[0],
              y2: end[1]
            },
            style: {
              lineWidth: 0.5,
              stroke: api.visual('color')
            }
          };
        },
        progressive: 2000
      }
    })
  );

```
