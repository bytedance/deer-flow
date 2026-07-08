# matrix-stock

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=matrix-stock
**Chart Type:** `time`

## User Data Requirements

Columns needed: check data arrays in reference code for required format

## Data Arrays — Complete Replacement Guide

**2 array(s)** to replace with real data:

### [0] `data` (context: series)
```
data: 
```

### [1] `data` (context: root)
```
data: 
```

## Agent Workflow

1. **Analyze** user table → identify columns matching the required format above
2. **Query DuckDB** → transform to match each data array's format
3. **Replace**: use **bracket-counting** to find each `data: [...]` → replace with real data
4. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: Matrix Stock Application
category: 'matrix, candlestick'
titleCN: 股市矩阵图
difficulty: 3
since: 6.0.0
*/
const lastClose = 50; // Close value of yesterday
const colorGreen = '#47b262';
const colorRed = '#eb5454';
const colorGray = '#888';
const colorGreenOpacity = 'rgba(71, 178, 98, 0.2)';
const colorRedOpacity = 'rgba(235, 84, 84, 0.2)';
const matrixMargin = 10;
const chartWidth = myChart.getWidth();
const chartHeight = myChart.getHeight();
const matrixWidth = chartWidth - matrixMargin * 2;
const matrixHeight = chartHeight - matrixMargin * 2;
const getPriceColor = (price) => {
  return price === lastClose
    ? colorGray
    : price > lastClose
    ? colorRed
    : colorGreen;
};
const priceFormatter = (value) => {
  const result = Math.round(value * 100) / 100 + '';
  // Adding padding 0 if needed
  let dotIndex = result.indexOf('.');
  if (dotIndex < 0) {
    return result + '.00';
  } else if (dotIndex === result.length - 2) {
    return result + '0';
  }
  return result;
};
const priceData = [];
const volumeData = [];
const averageData = []; // Volume weighted average price
const macdData = []; // MACD histogram data
const macdLineData = []; // MACD line (DIF) data
const signalLineData = []; // Signal line (DEA) data
let sumPrice = 0;
let sumVolume = 0;
const sTime = new Date('2025-10-16 09:30:00').getTime();
const eTime = new Date('2025-10-16 15:00:00').getTime();
const breakStartTime = new Date('2025-10-16 11:30:00').getTime();
const breakEndTime = new Date('2025-10-16 13:00:00').getTime();
// MACD algorithm parameters
const shortPeriod = 12; // Short-term EMA period, typically 12
const longPeriod = 26; // Long-term EMA period, typically 26
const signalPeriod = 9; // Signal line EMA period, typically 9
let time = sTime;
let price = 0;
let direction = 1; // 1 for up, -1 for down
let maxAbs = 0;
while (time < eTime) {
  const volume = Math.random() * 1000 + 500;
  volumeData.push([time, volume]);
  sumVolume += volume;
  if (time === sTime) {
    // Today open price
    direction = Math.random() < 0.5 ? 1 : -1;
    price = lastClose * (1 + (Math.random() - 0.5) * 0.02);
  } else {
    // 70% chance to maintain the last direction
    direction = Math.random() < 0.8 ? direction : -direction;
    price = Math.round((price + direction * (Math.random() * 0.1)) * 100) / 100;
  }
  priceData.push([time, price]);
  sumPrice += price * volume;
  averageData.push([time, sumPrice / sumVolume]);
  maxAbs = Math.max(maxAbs, Math.abs(price - lastClose));
  if (time === breakStartTime) {
    time = breakEndTime;
  } else {
    time += 60 * 1000; // increment by 1 minute
  }
}
// Calculate MACD
// 1. Calculate Exponential Moving Average (EMA)
function calculateEMA(prices, period) {
  let ema = [];
  const k = 2 / (period + 1);
  // No special handling for small datasets
  // Just calculate EMA from the period point onwards
  // If we have enough data points
  if (prices.length >= period) {
    // Calculate first EMA using Simple Moving Average (SMA)
    let sum = 0;
    for (let i = 0; i < period; i++) {
      sum += prices[i][1];
    }
    const firstEMA = sum / period;
    // First EMA at the period point
    ema.push([prices[period - 1][0], firstEMA]);
    // Calculate subsequent EMAs
    for (let i = period; i < prices.length; i++) {
      const newEMA = prices[i][1] * k + ema[ema.length - 1][1] * (1 - k);
      ema.push([prices[i][0], newEMA]);
    }
  }
  return ema;
}
// Calculate MACD indicators
if (priceData.length >= longPeriod) {
  // Need at least longPeriod data points
  // Calculate short and long-term EMA
  const shortEMA = calculateEMA(priceData, shortPeriod);
  const longEMA = calculateEMA(priceData, longPeriod);
  // Calculate MACD line (DIF: Difference) for points where both EMAs are available
  const macdLine = [];
  // Find the earliest point where both EMAs are available
  // This should be at longPeriod-1
  let startIndex = longPeriod - 1;
  // Map EMA data to timestamps for easier lookup
  const shortEMAMap = new Map(shortEMA.map((item) => [item[0], item[1]]));
  const longEMAMap = new Map(longEMA.map((item) => [item[0], item[1]]));
  // Process data points starting from where both EMAs are available
  for (let i = startIndex; i < priceData.length; i++) {
    const time = priceData[i][0];
    // If we have both EMA values for this timestamp
    if (shortEMAMap.has(time) && longEMAMap.has(time)) {
      const diff = (shortEMAMap.get(time) || 0) - (longEMAMap.get(time) || 0);
      macdLine.push([time, diff]);
    }
  }
  // Calculate signal line (DEA: Signal Line) using standard EMA
  const signalLine = calculateEMA(macdLine, signalPeriod);
  // Clear existing data arrays
  macdLineData.length = 0;
  signalLineData.length = 0;
  macdData.length = 0;
  // Find common time range where both MACD and signal are available
  const startTimestamp = signalLine.length > 0 ? signalLine[0][0] : null;
  if (startTimestamp !== null) {
    // Create a map of MACD values by timestamp
    const macdMap = new Map();
    for (const item of macdLine) {
      macdMap.set(item[0], item[1]);
    }
    // Create a map of signal values by timestamp
    const signalMap = new Map();
    for (const item of signalLine) {
      signalMap.set(item[0], item[1]);
    }
    // Find all common timestamps between MACD and signal lines
    const commonTimestamps = [];
    for (const time of macdMap.keys()) {
      if (signalMap.has(time)) {
        commonTimestamps.push(time);
      }
    }
    // Sort timestamps to ensure correct order
    commonTimestamps.sort((a, b) => a - b);
    // Use only common timestamps for all three data series
    for (const time of commonTimestamps) {
      const macdValue = macdMap.get(time);
      const signalValue = signalMap.get(time);
      macdLineData.push([time, macdValue]);
      signalLineData.push([time, signalValue]);
      // Calculate histogram
      const histogram = macdValue - signalValue;
      // Determine color based on histogram value
      const color = histogram > 0 ? colorRed : colorGreen;
      macdData.push({
        value: [time, histogram],
        itemStyle: {
          color: color
        }
      });
    }
  }
}
const orderData = [];
const orderCat = [];
const orderCount = 10;
let orderPrice = price - (0.01 * orderCount) / 2;
for (let i = 0; i < orderCount; ++i) {
  if (price === orderPrice) {
    continue;
  }
  orderPrice += 0.01;
  orderCat.push(orderPrice);
  const amount = Math.round(Math.random() * 200) + 10;
  const isLower = orderPrice < price;
  orderData.push({
    value: amount,
    itemStyle: {
      color: isLower ? colorGreenOpacity : colorRedOpacity
    },
    label: {
      formatter:
        `{name|${isLower ? 'Bid' : 'Ask'}} ` +
        `{${isLower ? 'green' : 'red'}|${priceFormatter(orderPrice)}} ` +
        `{amount|(${amount})}`,
      rich: {
        red: {
          color: colorRed
        },
        green: {
          color: colorGreen
        },
        amount: {
          color: '#666'
        },
        name: {
          fontWeight: 'bold',
          color: '#444'
        }
      }
    }
  });
}
const depthCount = 20;
const depthHighData = [];
const depthLowData = [];
let cumulativeHighVolume = 0;
let cumulativeLowVolume = 0;
for (let i = 0; i < depthCount; ++i) {
  depthHighData[depthCount + i] = cumulativeHighVolume;
  cumulativeHighVolume += Math.round(Math.random() * 1000);
  depthLowData[depthCount - i - 1] = cumulativeLowVolume;
  cumulativeLowVolume += Math.round(Math.random() * 1000);
}
const getTitle = (text, subtext, coord) => {
  return {
    text: text,
    subtext: subtext,
    left: 2,
    top: 2,
    padding: 0,
    textStyle: {
      fontSize: 12,
      fontWeight: 'bold',
      color: '#444'
    },
    subtextStyle: {
      fontSize: 10,
      color: '#666'
    },
    itemGap: 0,
    coordinateSystem: 'matrix',
    coord: coord
  };
};
const titles = [
  getTitle('Volume', Math.round(sumVolume / 1000) + 'B', [0, 5]),
  getTitle('MACD', '', [0, 4]),
  getTitle('Order Book', '', [4, 0]),
  getTitle('Depth', '', [4, 5])
];
option = {
  title: titles,
  xAxis: [
    {
      type: 'time',
      show: false,
      breaks: [
        {
          start: breakStartTime,
          end: breakEndTime,
          gap: 0
        }
      ]
    },
    {
      type: 'time',
      gridIndex: 1,
      show: false,
      breaks: [
        {
          start: breakStartTime,
          end: breakEndTime,
          gap: 0
        }
      ]
    },
    {
      type: 'time',
      gridIndex: 2,
      show: false,
      breaks: [
        {
          start: breakStartTime,
          end: breakEndTime,
          gap: 0
        }
      ]
    },
    {
      type: 'value',
      gridIndex: 3,
      show: false,
      max: 'dataMax'
    },
    {
      type: 'category',
      gridIndex: 4,
      show: false,
      boundaryGap: false,
      data: Array.from({ length: depthCount * 2 }, (_, i) => i + '')
    }
  ],
  yAxis: [
    {
      type: 'value',
      show: false,
      // Value should be symmetric around zero
      min: lastClose - maxAbs,
      max: lastClose + maxAbs
    },
    {
      type: 'value',
      gridIndex: 1,
      show: false
    },
    {
      type: 'value',
      gridIndex: 2,
      show: false
    },
    {
      type: 'category',
      gridIndex: 3,
      show: false
    },
    {
      type: 'value',
      gridIndex: 4,
      show: false,
      max: 'dataMax',
      min: 'dataMin'
    }
  ],
  grid: [
    {
      coordinateSystem: 'matrix',
      coord: [0, 0],
      top: 0,
      bottom: 0,
      left: 0,
      right: 0
    },
    {
      coordinateSystem: 'matrix',
      coord: [0, 5],
      top: 20,
      bottom: 0,
      left: 0,
      right: 0
    },
    {
      coordinateSystem: 'matrix',
      coord: [0, 4],
      top: 20,
      bottom: 0,
      left: 0,
      right: 0
    },
    {
      coordinateSystem: 'matrix',
      coord: [4, 0],
      top: 15,
      bottom: 2,
      left: 2,
      right: 2
    },
    {
      coordinateSystem: 'matrix',
      coord: [4, 4],
      top: 15,
      bottom: 0,
      left: 0,
      right: 0
    }
  ],
  series: [
    {
      type: 'line',
      symbolSize: 0,
      data: priceData,
      markPoint: {
        symbolSize: 0,
        symbol: 'circle',
        data: [
          {
            relativeTo: 'coordinate',
            x: 0,
            y: 0,
            name: 'max',
            type: 'max',
            label: {
              align: 'left',
              verticalAlign: 'top',
              formatter: priceFormatter(lastClose + maxAbs),
              color: getPriceColor(lastClose + maxAbs)
            }
          },
          {
            relativeTo: 'coordinate',
            x: 0,
            y: '50%',
            name: lastClose + '',
            label: {
              align: 'left',
              verticalAlign: 'middle',
              formatter: priceFormatter(lastClose),
              color: getPriceColor(lastClose)
            }
          },
          {
            relativeTo: 'coordinate',
            x: 0,
            y: '100%',
            name: 'min',
            type: 'min',
            label: {
              align: 'left',
              verticalAlign: 'bottom',
              formatter: priceFormatter(lastClose - maxAbs),
              color: getPriceColor(lastClose - maxAbs)
            }
          },
          {
            relativeTo: 'coordinate',
            x: '100%',
            y: 0,
            name: priceFormatter((maxAbs / lastClose) * 100) + '%',
            label: {
              align: 'right',
              verticalAlign: 'top',
              color: colorRed,
              formatter: '{b}'
            }
          },
          {
            relativeTo: 'coordinate',
            x: '100%',
            y: '50%',
            name: '0%',
            label: {
              align: 'right',
              verticalAlign: 'middle',
              color: colorGray,
              formatter: '{b}'
            }
          },
          {
            relativeTo: 'coordinate',
            x: '100%',
            y: '100%',
            name: '-' + priceFormatter((maxAbs / lastClose) * 100) + '%',
            label: {
              align: 'right',
              verticalAlign: 'bottom',
              color: colorGreen,
              formatter: '{b}'
            }
          }
        ]
      }
    },
    {
      type: 'line',
      symbolSize: 0,
      data: averageData,
      xAxisIndex: 0,
      yAxisIndex: 0
    },
    {
      type: 'line',
      symbolSize: 0,
      data: averageData,
      xAxisIndex: 0,
      yAxisIndex: 0,
      lineStyle: {
        color: '#FFC458',
        width: 1
      }
    },
    {
      name: 'Volume',
      type: 'bar',
      xAxisIndex: 1,
      yAxisIndex: 1,
      data: volumeData.map((item, index) => {
        // Compare current price with previous price to determine color
        let color = colorGray;
        if (index > 0) {
          const currentPrice = priceData[index][1];
          const prevPrice = priceData[index - 1][1];
          color = currentPrice > prevPrice ? colorRed : colorGreen;
        }
        return {
          value: [item[0], item[1]],
          itemStyle: {
            color: color
          }
        };
      })
    },
    {
      name: 'MACD',
      type: 'bar',
      xAxisIndex: 2,
      yAxisIndex: 2,
      data: macdData,
      barWidth: '70%' // Set bar width to 70% of coordinate area
    },
    {
      name: 'DIF',
      type: 'line',
      xAxisIndex: 2,
      yAxisIndex: 2,
      data: macdLineData,
      lineStyle: {
        color: '#FFC458',
        width: 1
      },
      symbol: 'none'
    },
    {
      name: 'DEA',
      type: 'line',
      xAxisIndex: 2,
      yAxisIndex: 2,
      data: signalLineData,
      lineStyle: {
        color: '#333',
        width: 1
      },
      symbol: 'none'
    },
    {
      name: 'Order Book',
      type: 'bar',
      xAxisIndex: 3,
      yAxisIndex: 3,
      data: orderData,
      barWidth: '90%',
      label: {
        show: true,
        position: 'insideLeft'
      }
    },
    {
      name: 'Depth High',
      type: 'line',
      xAxisIndex: 4,
      yAxisIndex: 4,
      data: depthHighData,
      step: 'end',
      lineStyle: {
        color: colorRed,
        width: 2
      },
      areaStyle: {
        color: colorRedOpacity,
        opacity: 1
      },
      symbol: 'none'
    },
    {
      name: 'Depth Low',
      type: 'line',
      xAxisIndex: 4,
      yAxisIndex: 4,
      data: depthLowData,
      step: 'end',
      lineStyle: {
        color: colorGreen,
        width: 2
      },
      areaStyle: {
        color: colorGreenOpacity,
        opacity: 1
      },
      symbol: 'none'
    }
  ],
  matrix: {
    left: matrixMargin,
    right: matrixMargin,
    top: matrixMargin,
    bottom: matrixMargin,
    x: {
      show: false,
      data: Array(5).fill(null)
    },
    y: {
      show: false,
      data: Array(6).fill(null)
    },
    body: {
      data: [
        {
          coord: [
            [0, 3],
            [0, 3]
          ],
          mergeCells: true
        },
        {
          coord: [
            [0, 3],
            [5, 5]
          ],
          mergeCells: true
        },
        {
          coord: [
            [0, 3],
            [4, 4]
          ],
          mergeCells: true
        },
        {
          coord: [
            [4, 4],
            [0, 3]
          ],
          mergeCells: true
        },
        {
          coord: [
            [4, 4],
            [4, 5]
          ],
          mergeCells: true
        }
      ]
    }
  },
  graphic: {
    elements: Array.from({ length: 3 }, (_, i) => {
      const lineWidth = 1;
      return {
        type: 'line',
        shape: {
          x1: matrixMargin + lineWidth,
          y1: (matrixHeight / 6) * (i + 1),
          x2: (matrixWidth / 5) * 4 + matrixMargin,
          y2: (matrixHeight / 6) * (i + 1)
        },
        style: {
          stroke: i === 1 ? '#bbb' : '#eee',
          lineWidth,
          lineDash: i == 1 ? 'dashed' : false
        }
      };
    }).concat(
      Array.from({ length: 3 }, (_, i) => {
        const lineWidth = 1;
        const matrixWidth = chartWidth - matrixMargin * 2;
        return {
          type: 'line',
          shape: {
            x1: (matrixWidth / 5) * (i + 1) + matrixMargin,
            y1: matrixMargin + lineWidth,
            x2: (matrixWidth / 5) * (i + 1) + matrixMargin,
            y2: chartHeight - matrixMargin
          },
          style: {
            stroke: '#eee',
            lineDash: false,
            lineWidth
          }
        };
      })
    )
  }
};
```
