# linesGL-ny

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=linesGL-ny
**Chart Type:** `linesGL`

## User Data Requirements

Columns needed: check data arrays in reference code for required format

## Data Arrays — Complete Replacement Guide

**1 array(s)** to replace with real data:

### [0] `dimensions` (context: series)
```
dimensions: ['value']
```

## Agent Workflow

1. **Analyze** user table → identify columns matching the required format above
2. **Query DuckDB** → transform to match each data array's format
3. **Replace**: use **bracket-counting** to find each `data: [...]` → replace with real data
4. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: Use linesGL to draw 1 million New York streets
titleCN: LinesGL - å®æ¶äº¤äºççº½çº¦è¡éå¯è§å
category: linesGL
*/
var CHUNK_COUNT = 32;
var dataCount = 0;
function fetchData(idx) {
  if (idx >= CHUNK_COUNT) {
    return;
  }
  var dataURL =
    'https://echarts.apache.org/examples/data/asset/data/links-ny/links_ny_' + idx + '.bin';
  var xhr = new XMLHttpRequest();
  xhr.open('GET', dataURL, true);
  xhr.responseType = 'arraybuffer';
  xhr.onload = function (e) {
    var rawData = new Float32Array(this.response);
    var data = new Float64Array(rawData.length - 2);
    var offsetX = rawData[0];
    var offsetY = rawData[1];
    var off = 0;
    var addedDataCount = 0;
    for (var i = 2; i < rawData.length; ) {
      var count = rawData[i++];
      data[off++] = count;
      for (var k = 0; k < count; k++) {
        var x = rawData[i++] + offsetX;
        var y = rawData[i++] + offsetY;
        data[off++] = x;
        data[off++] = y;
        addedDataCount++;
      }
    }
    myChart.appendData({
      seriesIndex: 0,
      data: data
    });
    dataCount += addedDataCount;
    fetchData(idx + 1);
  };
  xhr.send();
}
option = {
  progressive: 20000,
  backgroundColor: '#111',
  geo: {
    center: [-74.04327099998152, 40.86737600240287],
    zoom: 360,
    map: 'world',
    roam: true,
    silent: true,
    itemStyle: {
      normal: {
        color: 'transparent',
        borderColor: 'rgba(255,255,255,0.1)',
        borderWidth: 1
      }
    }
  },
  series: [
    {
      type: 'linesGL',
      coordinateSystem: 'geo',
      blendMode: 'lighter',
      dimensions: ['value'],
      data: new Float64Array(),
      polyline: true,
      large: true,
      lineStyle: {
        color: 'orange',
        opacity: 0.3
      }
    }
  ]
};
fetchData(0);
```
