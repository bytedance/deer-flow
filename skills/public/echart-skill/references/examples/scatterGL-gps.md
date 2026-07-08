# scatterGL-gps

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=scatterGL-gps
**Chart Type:** `scatterGL`

## User Data Requirements

Columns needed: check data arrays in reference code for required format

## Data Arrays — Complete Replacement Guide

**1 array(s)** to replace with real data:

### [0] `dimensions` (context: root)
```
dimensions: ['lng', 'lat']
```

## Agent Workflow

1. **Analyze** user table → identify columns matching the required format above
2. **Query DuckDB** → transform to match each data array's format
3. **Replace**: use **bracket-counting** to find each `data: [...]` → replace with real data
4. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: 10 million Bulk GPS points
titleCN: 1 åä¸ GPS ç¹å¯è§å
category: scatterGL
*/
var dataCount = 0;
var CHUNK_COUNT = 230;
// https://blog.openstreetmap.org/2012/04/01/bulk-gps-point-data/
function fetchData(idx) {
  if (idx >= CHUNK_COUNT) {
    return;
  }
  var dataURL = 'https://echarts.apache.org/examples/data/asset/data/gps/gps_' + idx + '.bin';
  var xhr = new XMLHttpRequest();
  xhr.open('GET', dataURL, true);
  xhr.responseType = 'arraybuffer';
  xhr.onload = function (e) {
    var rawData = new Int32Array(this.response);
    var data = new Float32Array(rawData.length);
    var addedDataCount = rawData.length / 2;
    for (var i = 0; i < rawData.length; i += 2) {
      data[i] = rawData[i + 1] / 1e7;
      data[i + 1] = rawData[i] / 1e7;
    }
    myChart.appendData({
      seriesIndex: 0,
      data: data
    });
    fetchData(idx + 1);
  };
  xhr.send();
}
option = {
  backgroundColor: '#000',
  title: {
    text: '10000000 GPS Points',
    left: 'center',
    textStyle: {
      color: '#fff'
    }
  },
  geo: {
    map: 'world',
    roam: true,
    label: {
      emphasis: {
        show: false
      }
    },
    silent: true,
    itemStyle: {
      normal: {
        areaColor: '#323c48',
        borderColor: '#111'
      },
      emphasis: {
        areaColor: '#2a333d'
      }
    }
  },
  series: [
    {
      name: 'å¼±',
      type: 'scatterGL',
      progressive: 1e6,
      coordinateSystem: 'geo',
      symbolSize: 1,
      zoomScale: 0.002,
      blendMode: 'lighter',
      large: true,
      itemStyle: {
        color: 'rgb(20, 15, 2)'
      },
      postEffect: {
        enable: true
      },
      silent: true,
      dimensions: ['lng', 'lat'],
      data: new Float32Array()
    }
  ]
};
fetchData(0);
```
