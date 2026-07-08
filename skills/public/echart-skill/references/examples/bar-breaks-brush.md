# bar-breaks-brush

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=bar-breaks-brush
**Chart Type:** `shadow`

## User Data Requirements

Columns needed: check data arrays in reference code for required format

## Data Arrays — Complete Replacement Guide

**5 array(s)** to replace with real data:

### [0] `data` (context: xAxis)
```
data: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
```

### [1] `data` (context: series)
```
data: [1500, 2032, 2001, 3154, 2190, 4330, 2410]
```

### [2] `data` (context: root)
```
data: [1200, 1320, 1010, 1340, 900, 2300, 2100]
```

### [3] `data` (context: root)
```
data: [103200, 100320, 103010, 102340, 103900, 103300, 103200]
```

### [4] `data` (context: root)
```
data: [106212, 102118, 102643, 104631, 106679, 100130, 107022]
```

## Agent Workflow

1. **Analyze** user table → identify columns matching the required format above
2. **Query DuckDB** → transform to match each data array's format
3. **Replace**: use **bracket-counting** to find each `data: [...]` → replace with real data
4. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: Bar Chart with Axis Breaks (Brush-enabled)
titleCN: 断轴上的柱状图（可刷选）
category: bar
difficulty: 8
since: 6.0.0
*/
var GRID_TOP = 120;
var GRID_BOTTOM = 80;
var Y_DATA_ROUND_PRECISION = 0;
var _currentAxisBreaks = [
  {
    start: 5000,
    end: 100000,
    gap: '2%'
  }
];
option = {
  title: {
    text: 'Bar Chart with Axis Break (Brush-enabled)',
    subtext:
      'Brush to create a new axis break.\nClick on the break area to reset.',
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
    trigger: 'axis',
    axisPointer: {
      type: 'shadow'
    }
  },
  legend: {},
  grid: {
    top: GRID_TOP,
    bottom: GRID_BOTTOM
  },
  xAxis: [
    {
      type: 'category',
      data: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    }
  ],
  yAxis: [
    {
      type: 'value',
      breaks: _currentAxisBreaks,
      breakArea: {
        itemStyle: {
          opacity: 1
        },
        zigzagMaxSpan: 15,
        zigzagAmplitude: 2,
        zigzagZ: 200
      }
    }
  ],
  series: [
    {
      name: 'Data A',
      type: 'bar',
      emphasis: {
        focus: 'series'
      },
      data: [1500, 2032, 2001, 3154, 2190, 4330, 2410]
    },
    {
      name: 'Data B',
      type: 'bar',
      emphasis: {
        focus: 'series'
      },
      data: [1200, 1320, 1010, 1340, 900, 2300, 2100]
    },
    {
      name: 'Data C',
      type: 'bar',
      emphasis: {
        focus: 'series'
      },
      data: [103200, 100320, 103010, 102340, 103900, 103300, 103200]
    },
    {
      name: 'Data D',
      type: 'bar',
      data: [106212, 102118, 102643, 104631, 106679, 100130, 107022],
      emphasis: {
        focus: 'series'
      }
    }
  ]
};
/**
 * This is some interaction logic with axis break:
 *  - Brush to create a axis break.
 *
 * You can ignore this part if you do not need it.
 */
function initAxisBreakInteraction() {
  var _brushingEl = null;
  myChart.getZr().on('mousedown', function (params) {
    _brushingEl = new echarts.graphic.Rect({
      shape: { x: 0, y: params.offsetY },
      style: { stroke: 'none', fill: '#ccc' },
      ignore: true
    });
    myChart.getZr().add(_brushingEl);
  });
  myChart.getZr().on('mousemove', function (params) {
    if (!_brushingEl) {
      return;
    }
    var initY = _brushingEl.shape.y;
    var currPoint = [params.offsetX, params.offsetY];
    _brushingEl.setShape('width', myChart.getWidth());
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
    var pixelSpan = Math.abs(currPoint[1] - initY);
    if (pixelSpan > 2) {
      updateAxisBreak(myChart, [initX, initY], currPoint);
    }
    myChart.getZr().remove(_brushingEl);
    _brushingEl = null;
  });
  myChart.on('axisbreakchanged', function (params) {
    // Remove expanded axis breaks from _currentAxisBreaks.
    var changedBreaks = params.breaks || [];
    for (var i = 0; i < changedBreaks.length; i++) {
      var changedBreakItem = changedBreaks[i];
      if (changedBreakItem.isExpanded) {
        for (var j = _currentAxisBreaks.length - 1; j >= 0; j--) {
          if (
            _currentAxisBreaks[j].start === changedBreakItem.start &&
            _currentAxisBreaks[j].end === changedBreakItem.end
          ) {
            _currentAxisBreaks.splice(j, 1);
          }
        }
      }
    }
  });
  function updateAxisBreak(myChart, initXY, currPoint) {
    var dataXY0 = myChart.convertFromPixel({ gridIndex: 0 }, initXY);
    var dataXY1 = myChart.convertFromPixel({ gridIndex: 0 }, currPoint);
    var dataRange = [roundYValue(dataXY0[1]), roundYValue(dataXY1[1])];
    if (dataRange[0] > dataRange[1]) {
      dataRange.reverse();
    }
    var newBreak = {
      start: dataRange[0],
      end: dataRange[1]
    };
    insertAndMergeNewBreakWithExistingBreaks(newBreak);
    var gapPercentStr =
      (Math.abs(
        myChart.convertToPixel({ yAxisIndex: 0 }, newBreak.start) -
          myChart.convertToPixel({ yAxisIndex: 0 }, newBreak.end)
      ) /
        getYAxisPixelSpan(myChart)) *
        100 +
      '%';
    function makeOption(gapPercentStr) {
      newBreak.gap = gapPercentStr;
      return {
        yAxis: {
          breaks: _currentAxisBreaks
        }
      };
    }
    // This is to make a transition animation effect - firstly create axis break
    // on the brushed area, then collapse it to a small gap.
    myChart.setOption(makeOption(gapPercentStr));
    setTimeout(() => {
      myChart.setOption(makeOption('2%'));
    }, 0);
  }
  // Insert and merge new break with existing breaks if intersecting.
  function insertAndMergeNewBreakWithExistingBreaks(newBreak) {
    for (var i = _currentAxisBreaks.length - 1; i >= 0; i--) {
      var existingBreak = _currentAxisBreaks[i];
      if (
        existingBreak.start <= newBreak.end &&
        existingBreak.end >= newBreak.start
      ) {
        newBreak.start = Math.min(existingBreak.start, newBreak.start);
        newBreak.end = Math.max(existingBreak.end, newBreak.end);
        _currentAxisBreaks.splice(i, 1); // Remove the existing break.
      }
    }
    _currentAxisBreaks.push(newBreak);
  }
  function getYAxisPixelSpan(myChart) {
    return myChart.getHeight() - GRID_BOTTOM - GRID_TOP;
  }
  function roundYValue(val) {
    return +(+val).toFixed(Y_DATA_ROUND_PRECISION);
  }
} // End of initAxisBreakInteraction
setTimeout(initAxisBreakInteraction, 0);
```
