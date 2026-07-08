# matrix-sparkline

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=matrix-sparkline
**Chart Type:** `slider`

## User Data Requirements

Columns needed: check data arrays in reference code for required format

## Data Arrays — Complete Replacement Guide

**2 array(s)** to replace with real data:

### [0] `data` (context: root)
```
data: [
        {
          coord: [-1, -1],
          value: 'Time'
        }
      ]
```

### [1] `data` (context: root)
```
data: [
        {
          coord: [null, _yBreakTimeIndex],
          coordClamp: true,
          mergeCells: true,
          value: 'Break',
       ...
```

## Agent Workflow

1. **Analyze** user table → identify columns matching the required format above
2. **Query DuckDB** → transform to match each data array's format
3. **Replace**: use **bracket-counting** to find each `data: [...]` → replace with real data
4. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: Mini Line Charts (Sparkline) in Matrix
category: matrix, line
titleCN: 矩阵中的微型折线图
difficulty: 5
since: 6.0.0
*/
const _matrixDimensionData = {
  x: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'],
  y: [
    { value: '8:00\n~\n10:00' },
    { value: '10:00\n~\n12:00' },
    { value: '12:00\n~\n14:00', size: 55 },
    { value: '14:00\n~\n16:00' },
    { value: '16:00\n~\n18:00' },
    { value: '18:00\n~\n20:00' }
  ]
};
const _yBreakTimeIndex = 2; // '12:00 - 14:00',
const _seriesFakeDataLength = 365;
option = {
  matrix: {
    x: {
      data: _matrixDimensionData.x,
      levelSize: 40,
      label: {
        fontSize: 16,
        color: '#555'
      }
    },
    y: {
      data: _matrixDimensionData.y,
      levelSize: 70,
      label: {
        fontSize: 14,
        color: '#777'
      }
    },
    corner: {
      data: [
        {
          coord: [-1, -1],
          value: 'Time'
        }
      ],
      label: {
        fontSize: 16,
        color: '#777'
      }
    },
    body: {
      data: [
        {
          coord: [null, _yBreakTimeIndex],
          coordClamp: true,
          mergeCells: true,
          value: 'Break',
          label: {
            color: '#999',
            fontSize: 16
          }
        }
      ]
    },
    top: 30,
    bottom: 80,
    width: '90%',
    left: 'center'
  },
  tooltip: {
    trigger: 'axis'
  },
  dataZoom: [
    {
      type: 'slider',
      xAxisIndex: 'all',
      left: '10%',
      right: '10%',
      bottom: 30,
      height: 30,
      throttle: 120
    },
    {
      type: 'inside',
      xAxisIndex: 'all',
      throttle: 120
    }
  ],
  grid: [],
  xAxis: [],
  yAxis: [],
  series: []
};
eachMatrixCell((xval, yval, xidx, yidx) => {
  const id = makeId(xidx, yidx);
  option.grid.push({
    id: id,
    coordinateSystem: 'matrix',
    coord: [xval, yval],
    top: 10,
    bottom: 10,
    left: 'center',
    width: '90%',
    containLabel: true
  });
  option.xAxis.push({
    type: 'category',
    id: id,
    gridId: id,
    scale: true,
    axisTick: { show: false },
    axisLabel: { show: false },
    axisLine: { show: false },
    splitLine: { show: false }
  });
  option.yAxis.push({
    id: id,
    gridId: id,
    interval: Number.MAX_SAFE_INTEGER,
    scale: true,
    axisLabel: {
      showMaxLabel: true,
      fontSize: 9
    },
    axisLine: { show: false },
    axisTick: { show: false }
  });
  option.series.push({
    xAxisId: id,
    yAxisId: id,
    type: 'line',
    symbol: 'none',
    lineStyle: {
      lineWidth: 1
    },
    data: generateFakeSeriesData(_seriesFakeDataLength, xidx, yidx)
  });
});
// ------ Helpers Start ------
function makeId(xidx, yidx) {
  return `${xidx}|${yidx}`;
}
function eachMatrixCell(cb) {
  _matrixDimensionData.y.forEach((yvalItem, yidx) => {
    const yval = yvalItem.value;
    if (yidx === _yBreakTimeIndex) {
      return;
    }
    _matrixDimensionData.x.forEach((xval, xidx) => {
      cb(xval, yval, xidx, yidx);
    });
  });
}
function generateFakeSeriesData(dayCount, xidx, yidx) {
  const dayStart = new Date('2025-05-05T00:00:00.000Z'); // Monday
  dayStart.setDate(xidx + 5);
  const timeStart = dayStart.getTime();
  const sevenDay = 7 * 1000 * 3600 * 24;
  const cellData = [];
  let lastVal = +(Math.random() * 300).toFixed(0);
  let turnCount = null;
  let sign = -1;
  for (let idx = 0; idx < dayCount; idx++) {
    if (turnCount == null || idx >= turnCount) {
      turnCount =
        idx + Math.round((dayCount / 4) * ((Math.random() - 0.5) * 0.1));
      sign = -sign;
    }
    const deltaMag = 50;
    const delta = +(
      Math.random() * deltaMag -
      deltaMag / 2 +
      (sign * deltaMag) / 3
    ).toFixed(0);
    const val = Math.max(0, (lastVal += delta));
    const xTime = timeStart + idx * sevenDay;
    const dataXVal = echarts.time.format(xTime, '{yyyy}-{MM}-{dd}');
    cellData.push([dataXVal, val]);
  }
  return cellData;
}
```
