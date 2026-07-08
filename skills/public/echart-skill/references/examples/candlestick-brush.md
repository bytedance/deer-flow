# candlestick-brush

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=candlestick-brush
**Chart Type:** `candlestick` + `brush`

## Data Arrays — Complete Replacement Guide

**3 array(s)** to replace with real data:

### [0] `rawData` — Main candlestick data (OHLC)
Each element: `[date_string, open, close, low, high]`

```javascript
var rawData = [
  ['2024-01-02', 100.5, 102.3, 99.8, 103.1],
  ['2024-01-03', 102.3, 101.1, 100.5, 103.0],
  ...
];
```

> **DuckDB query**: `SELECT date, open, close, low, high FROM ohlc_table ORDER BY date`

### [1] `legendNames` (context: legend.data)

```javascript
legend: { data: ['Dow-Jones index', 'MA5', 'MA10', 'MA20', 'MA30'] }
```

### [2] `pieces` (context: visualMap)

```javascript
pieces: [{ value: 1, color: downColor }, { value: -1, color: upColor }]
```

## Agent Workflow

1. **Analyze** user table → identify columns for date + OHLC prices
2. **Query DuckDB** → `PIVOT` or GROUP BY to produce `[date, open, close, low, high]` rows
3. **Replace** the `rawData` array using bracket-counting — find `var rawData = [\n  ...\n];`
4. **Replace** legend names if needed
5. **Wrap HTML**: ECharts inline + `<div id="main">` + `<script>` with the reference code below
6. **Validate**: `validate_chart.py output.html`

## Reference Code

```javascript
const upColor = '#00da3c';
const downColor = '#ec0000';

function splitData(rawData) {
  let categoryData = [];
  let values = [];
  let volumes = [];
  for (let i = 0; i < rawData.length; i++) {
    categoryData.push(rawData[i].splice(0, 1)[0]);
    values.push(rawData[i]);
    volumes.push([i, rawData[i][4], rawData[i][0] > rawData[i][1] ? 1 : -1]);
  }
  return {
    categoryData: categoryData,
    values: values,
    volumes: volumes
  };
}

function calculateMA(dayCount, data) {
  var result = [];
  for (var i = 0, len = data.values.length; i < len; i++) {
    if (i < dayCount) {
      result.push('-');
      continue;
    }
    var sum = 0;
    for (var j = 0; j < dayCount; j++) {
      sum += data.values[i - j][1];
    }
    result.push(+(sum / dayCount).toFixed(3));
  }
  return result;
}

// ⚠️ Agent: replace this sample data with real DuckDB query results
var rawData = [
  ['2024-01-02', 100.5, 102.3, 99.8, 103.1],
  ['2024-01-03', 102.3, 101.1, 100.5, 103.0],
  ['2024-01-04', 101.1, 103.5, 100.2, 104.0]
];
// ... more rows from DuckDB

var data = splitData(rawData);

var myChart = echarts.init(document.getElementById('main'));

var option = {
  animation: false,
  legend: {
    bottom: 10,
    left: 'center',
    data: ['Dow-Jones index', 'MA5', 'MA10', 'MA20', 'MA30']
  },
  tooltip: {
    trigger: 'axis',
    axisPointer: { type: 'cross' },
    borderWidth: 1,
    borderColor: '#ccc',
    padding: 10,
    textStyle: { color: '#000' },
    position: function (pos, params, el, elRect, size) {
      const obj = { top: 10 };
      obj[['left', 'right'][+(pos[0] < size.viewSize[0] / 2)]] = 30;
      return obj;
    }
  },
  axisPointer: {
    link: [{ xAxisIndex: 'all' }],
    label: { backgroundColor: '#777' }
  },
  toolbox: {
    feature: {
      dataZoom: { yAxisIndex: false },
      brush: { type: ['lineX', 'clear'] }
    }
  },
  brush: {
    xAxisIndex: 'all',
    brushLink: 'all',
    outOfBrush: { colorAlpha: 0.1 }
  },
  visualMap: {
    show: false,
    seriesIndex: 5,
    dimension: 2,
    pieces: [
      { value: 1, color: downColor },
      { value: -1, color: upColor }
    ]
  },
  grid: [
    { left: '10%', right: '8%', height: '50%' },
    { left: '10%', right: '8%', top: '63%', height: '16%' }
  ],
  xAxis: [
    {
      type: 'category',
      data: data.categoryData,
      boundaryGap: false,
      axisLine: { onZero: false },
      splitLine: { show: false },
      min: 'dataMin',
      max: 'dataMax',
      axisPointer: { z: 100 }
    },
    {
      type: 'category',
      gridIndex: 1,
      data: data.categoryData,
      boundaryGap: false,
      axisLine: { onZero: false },
      axisTick: { show: false },
      splitLine: { show: false },
      axisLabel: { show: false },
      min: 'dataMin',
      max: 'dataMax'
    }
  ],
  yAxis: [
    { scale: true, splitArea: { show: true } },
    {
      scale: true,
      gridIndex: 1,
      splitNumber: 2,
      axisLabel: { show: false },
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { show: false }
    }
  ],
  dataZoom: [
    { type: 'inside', xAxisIndex: [0, 1], start: 98, end: 100 },
    { show: true, xAxisIndex: [0, 1], type: 'slider', top: '85%', start: 98, end: 100 }
  ],
  series: [
    {
      name: 'Dow-Jones index',
      type: 'candlestick',
      data: data.values,
      itemStyle: {
        color: upColor,
        color0: downColor,
        borderColor: undefined,
        borderColor0: undefined
      }
    },
    {
      name: 'MA5',
      type: 'line',
      data: calculateMA(5, data),
      smooth: true,
      lineStyle: { opacity: 0.5 }
    },
    {
      name: 'MA10',
      type: 'line',
      data: calculateMA(10, data),
      smooth: true,
      lineStyle: { opacity: 0.5 }
    },
    {
      name: 'MA20',
      type: 'line',
      data: calculateMA(20, data),
      smooth: true,
      lineStyle: { opacity: 0.5 }
    },
    {
      name: 'MA30',
      type: 'line',
      data: calculateMA(30, data),
      smooth: true,
      lineStyle: { opacity: 0.5 }
    },
    {
      name: 'Volume',
      type: 'bar',
      xAxisIndex: 1,
      yAxisIndex: 1,
      data: data.volumes
    }
  ]
};

myChart.setOption(option);

myChart.dispatchAction({
  type: 'brush',
  areas: [{
    brushType: 'lineX',
    coordRange: ['2016-06-02', '2016-06-20'],
    xAxisIndex: 0
  }]
});

window.addEventListener('resize', function() { myChart.resize(); });
```
