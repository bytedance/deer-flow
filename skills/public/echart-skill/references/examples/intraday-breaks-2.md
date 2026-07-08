# intraday-breaks-2

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=intraday-breaks-2
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
title: Intraday Chart with Breaks (II)
titleCN: 断轴上的日内走势图 (II)
category: candlestick, line
difficulty: 4
since: 6.0.0
*/
var formatTime = echarts.time.format;
var _data = generateData1();
option = {
  // Choose axis ticks based on UTC time.
  useUTC: true,
  title: {
    text: 'Intraday Chart with Breaks (Single Day)',
    left: 'center'
  },
  tooltip: {
    show: true,
    trigger: 'axis'
  },
  xAxis: [
    {
      type: 'time',
      interval: 1000 * 60 * 30,
      axisLabel: {
        showMinLabel: true,
        showMaxLabel: true,
        formatter: (value, index, extra) => {
          if (!extra || !extra.break) {
            // The third parameter is `useUTC: true`.
            return formatTime(value, '{HH}:{mm}', true);
          }
          // Only render the label on break start, but not on break end.
          if (extra.break.type === 'start') {
            return (
              formatTime(extra.break.start, '{HH}:{mm}', true) +
              '/' +
              formatTime(extra.break.end, '{HH}:{mm}', true)
            );
          }
          return '';
        }
      },
      breakLabelLayout: {
        // Disable auto move of break labels if overlapping,
        // and use `axisLabel.formatter` to control the label display.
        moveOverlap: false
      },
      breaks: [
        {
          start: _data.breakStart,
          end: _data.breakEnd,
          gap: 0
        }
      ],
      breakArea: {
        expandOnClick: false,
        zigzagAmplitude: 0,
        zigzagZ: 200
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
      xAxisIndex: 0
    },
    {
      type: 'slider',
      xAxisIndex: 0
    }
  ],
  series: [
    {
      type: 'line',
      symbolSize: 0,
      data: _data.seriesData
    }
  ]
};
/**
 * Generate random data, not relevant to echarts API.
 */
function generateData1() {
  var seriesData = [];
  var time = new Date('2024-04-09T09:30:00Z');
  var endTime = new Date('2024-04-09T15:00:00Z').getTime();
  var breakStart = new Date('2024-04-09T11:30:00Z').getTime();
  var breakEnd = new Date('2024-04-09T13:00:00Z').getTime();
  for (var val = 1669; time.getTime() <= endTime; ) {
    if (time.getTime() <= breakStart || time.getTime() >= breakEnd) {
      val =
        val +
        Math.floor((Math.random() - 0.5 * Math.sin(val / 1000)) * 20 * 100) /
          100;
      val = +val.toFixed(2);
      seriesData.push([time.getTime(), val]);
    }
    time.setMinutes(time.getMinutes() + 1);
  }
  return {
    seriesData: seriesData,
    breakStart: breakStart,
    breakEnd: breakEnd
  };
}
```
