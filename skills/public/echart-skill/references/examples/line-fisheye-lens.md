# line-fisheye-lens

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=line-fisheye-lens
**Chart Type:** `line`

## User Data Requirements

Columns needed: need **time/category** + **value** columns

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
title: Fisheye Lens on Line Chart
titleCN: 折线图鱼眼放大
category: line
difficulty: 8
since: 6.0.0
*/
var GRID_TOP = 120;
var GRID_BOTTOM = 80;
var GRID_LEFT = 60;
var GRID_RIGHT = 60;
var Y_DATA_ROUND_PRECISION = 0;
var _breakAreaStyle = {
  expandOnClick: false,
  zigzagZ: 200,
  zigzagAmplitude: 0,
  itemStyle: {
    borderColor: '#777',
    opacity: 0
  }
};
option = {
  title: {
    text: 'Fisheye Lens on Line Chart',
    subtext: 'Brush to magnify the details',
    left: 'center',
    textStyle: {
      fontSize: 20
    },
    subtextStyle: {
      color: '#175ce5',
      fontSize: 15,
      fontWeight: 'bold'
    }
  },
  tooltip: {
    trigger: 'axis'
  },
  legend: {},
  grid: {
    top: GRID_TOP,
    bottom: GRID_BOTTOM,
    left: GRID_LEFT,
    right: GRID_RIGHT
  },
  xAxis: [
    {
      splitLine: {
        show: false
      },
      breakArea: _breakAreaStyle
    }
  ],
  yAxis: [
    {
      axisTick: {
        show: true
      },
      breakArea: _breakAreaStyle
    }
  ],
  series: [
    {
      type: 'line',
      name: 'Data A',
      symbol: 'circle',
      showSymbol: false,
      symbolSize: 5,
      data: generateSeriesData()
    }
  ]
};
/**
 * This is some interaction logic with axis break:
 *  - Brush to fisheye-magnify an area.
 *
 * You can ignore this part if you do not need it.
 */
function initAxisBreakInteraction() {
  var _brushingEl = null;
  myChart.on('click', function (params) {
    if (params.name === 'clearAxisBreakBtn') {
      var option = {
        xAxis: { breaks: [] },
        yAxis: { breaks: [] }
      };
      addClearButtonUpdateOption(option, false);
      myChart.setOption(option);
    }
  });
  function addClearButtonUpdateOption(option, show) {
    option.graphic = [
      {
        elements: [
          {
            type: 'rect',
            ignore: !show,
            name: 'clearAxisBreakBtn',
            top: 5,
            left: 5,
            shape: { r: 3, width: 70, height: 30 },
            style: { fill: '#eee', stroke: '#999', lineWidth: 1 },
            textContent: {
              type: 'text',
              style: {
                text: 'Reset',
                fontSize: 15,
                fontWeight: 'bold'
              }
            },
            textConfig: { position: 'inside' }
          }
        ]
      }
    ];
  }
  myChart.getZr().on('mousedown', function (params) {
    _brushingEl = new echarts.graphic.Rect({
      shape: { x: params.offsetX, y: params.offsetY },
      style: { stroke: 'none', fill: '#ccc' },
      ignore: true
    });
    myChart.getZr().add(_brushingEl);
  });
  myChart.getZr().on('mousemove', function (params) {
    if (!_brushingEl) {
      return;
    }
    var initX = _brushingEl.shape.x;
    var initY = _brushingEl.shape.y;
    var currPoint = [params.offsetX, params.offsetY];
    _brushingEl.setShape('width', currPoint[0] - initX);
    _brushingEl.setShape('height', currPoint[1] - initY);
    _brushingEl.ignore = false;
  });
  document.addEventListener('mouseup', function (params) {
    if (!_brushingEl) {
      return;
    }
    var initX = _brushingEl.shape.x;
    var initY = _brushingEl.shape.y;
    var currPoint = [params.offsetX, params.offsetY];
    var xPixelSpan = Math.abs(currPoint[0] - initX);
    var yPixelSpan = Math.abs(currPoint[1] - initY);
    if (xPixelSpan > 2 && yPixelSpan > 2) {
      updateAxisBreak(
        myChart,
        [initX, initY],
        currPoint,
        xPixelSpan,
        yPixelSpan
      );
    }
    myChart.getZr().remove(_brushingEl);
    _brushingEl = null;
  });
  function updateAxisBreak(myChart, initXY, currPoint, xPixelSpan, yPixelSpan) {
    var dataXY0 = myChart.convertFromPixel({ gridIndex: 0 }, initXY);
    var dataXY1 = myChart.convertFromPixel({ gridIndex: 0 }, currPoint);
    function makeDataRange(v0, v1) {
      var dataRange = [roundXYValue(v0), roundXYValue(v1)];
      if (dataRange[0] > dataRange[1]) {
        dataRange.reverse();
      }
      return dataRange;
    }
    var xDataRange = makeDataRange(dataXY0[0], dataXY1[0]);
    var yDataRange = makeDataRange(dataXY0[1], dataXY1[1]);
    var xySpan = getXYAxisPixelSpan(myChart);
    var xGapPercentStr = (xPixelSpan / xySpan[0]) * 100 + '%';
    var yGapPercentStr = (yPixelSpan / xySpan[1]) * 100 + '%';
    function makeOption(xGapPercentStr, yGapPercentStr) {
      return {
        xAxis: {
          breaks: [
            {
              start: xDataRange[0],
              end: xDataRange[1],
              gap: xGapPercentStr
            }
          ]
        },
        yAxis: {
          breaks: [
            {
              start: yDataRange[0],
              end: yDataRange[1],
              gap: yGapPercentStr
            }
          ]
        }
      };
    }
    // This is to make a transition animation effect - firstly create axis break
    // on the brushed area, then collapse it to a small gap.
    myChart.setOption(makeOption(xGapPercentStr, yGapPercentStr));
    setTimeout(() => {
      var option = makeOption('80%', '80%');
      addClearButtonUpdateOption(option, true);
      myChart.setOption(option);
    }, 0);
  }
  function getXYAxisPixelSpan(myChart) {
    return [
      myChart.getWidth() - GRID_LEFT - GRID_RIGHT,
      myChart.getHeight() - GRID_BOTTOM - GRID_TOP
    ];
  }
} // End of initAxisBreakInteraction
function roundXYValue(val) {
  return +(+val).toFixed(Y_DATA_ROUND_PRECISION);
}
function generateSeriesData() {
  function makeRandom(lastYVal, range, factor) {
    lastYVal = lastYVal - range[0];
    var delta =
      (Math.random() - 0.5 * Math.sin(lastYVal / factor)) *
      (range[1] - range[0]) *
      0.8;
    return roundXYValue(lastYVal + delta + range[0]);
  }
  var seriesData = [];
  var DATA_COUNT = 1000;
  var reset1 = true;
  var reset2 = true;
  let yVal = 0;
  for (var idx = 0; idx < DATA_COUNT; idx++) {
    if (idx < DATA_COUNT / 4) {
      yVal = makeRandom(yVal, [100, 10000], 50000);
    } else if (idx < (2 * DATA_COUNT) / 3) {
      if (reset1) {
        yVal = 110010;
        reset1 = false;
      }
      yVal = makeRandom(yVal, [100000, 105000], 50000);
    } else {
      if (reset2) {
        yVal = 300100;
        reset2 = false;
      }
      yVal = makeRandom(yVal, [300000, 305000], 20000);
    }
    seriesData.push([idx, yVal]);
  }
  return seriesData;
}
setTimeout(initAxisBreakInteraction, 0);
```
