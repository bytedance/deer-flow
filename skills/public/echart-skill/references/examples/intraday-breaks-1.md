# intraday-breaks-1

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=intraday-breaks-1
**Chart Type:** `time`

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
title: Intraday Chart with Breaks
titleCN: 断轴上的日内走势图
category: candlestick, line
difficulty: 4
since: 6.0.0
*/
var roundTime = echarts.time.roundTime;
var formatTime = echarts.time.format;
var BREAK_GAP = '1%';
var DATA_ZOOM_MIN_VALUE_SPAN = 3600 * 1000;
var _data = generateData();
option = {
  // Choose axis ticks based on UTC time.
  useUTC: true,
  title: {
    text: 'Intraday Chart with Breaks (Multiple Days)',
    left: 'center'
  },
  tooltip: {
    show: true,
    trigger: 'axis'
  },
  grid: {
    outerBounds: {
      top: '20%',
      bottom: '30%'
    }
  },
  xAxis: [
    {
      type: 'time',
      interval: 1000 * 60 * 30,
      axisLabel: {
        showMinLabel: true,
        showMaxLabel: true,
        formatter(timestamp, _, opt) {
          if (opt.break) {
            // The third parameter is `useUTC: true`.
            return formatTime(timestamp, '{HH}:{mm}\n{weak|{dd}d}', true);
          }
          return formatTime(timestamp, '{HH}:{mm}', true);
        },
        rich: {
          weak: {
            color: '#999'
          }
        }
      },
      breaks: _data.breaks,
      breakArea: {
        expandOnClick: false,
        zigzagAmplitude: 0,
        zigzagZ: 200,
        itemStyle: {
          borderColor: 'none',
          opacity: 0
        }
      }
    }
  ],
  yAxis: {
    type: 'value',
    min: 'dataMin'
  },
  dataZoom: [
    {
      type: 'inside',
      minValueSpan: DATA_ZOOM_MIN_VALUE_SPAN
    },
    {
      type: 'slider',
      top: '73%',
      minValueSpan: DATA_ZOOM_MIN_VALUE_SPAN
    }
  ],
  series: [
    {
      type: 'line',
      symbolSize: 0,
      areaStyle: {},
      data: _data.seriesData
    }
  ]
};
/**
 * Generate random data, not relevant to echarts API.
 */
function generateData() {
  var seriesData = [];
  var breaks = [];
  var time = new Date('2024-04-09T00:00:00Z');
  var endTime = new Date('2024-04-12T23:59:59Z').getTime();
  var todayCloseTime = new Date();
  updateDayTime(time, todayCloseTime);
  function updateDayTime(time, todayCloseTime) {
    roundTime(time, 'day', true);
    todayCloseTime.setTime(time.getTime());
    time.setUTCHours(9, 30); // Open time
    todayCloseTime.setUTCHours(16, 0); // Close time
  }
  var valBreak = false;
  for (var val = 1669; time.getTime() <= endTime; ) {
    var delta;
    if (valBreak) {
      delta =
        Math.floor((Math.random() - 0.5 * Math.sin(val / 1000)) * 20 * 100) /
        10;
      valBreak = false;
    } else {
      delta =
        Math.floor((Math.random() - 0.5 * Math.sin(val / 1000)) * 20 * 100) /
        100;
    }
    val = val + delta;
    val = +val.toFixed(2);
    seriesData.push([time.getTime(), val]);
    time.setMinutes(time.getMinutes() + 1);
    if (time.getTime() > todayCloseTime.getTime()) {
      // Use `NaN` to break the line.
      seriesData.push([time.getTime(), NaN]);
      var breakStart = todayCloseTime.getTime();
      time.setUTCDate(time.getUTCDate() + 1);
      updateDayTime(time, todayCloseTime);
      var breakEnd = time.getTime();
      valBreak = true;
      breaks.push({
        start: breakStart,
        end: breakEnd,
        gap: BREAK_GAP
      });
    }
  }
  return {
    seriesData: seriesData,
    breaks: breaks
  };
}
```
