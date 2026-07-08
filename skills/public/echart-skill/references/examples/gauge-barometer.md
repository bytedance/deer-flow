# gauge-barometer

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=gauge-barometer
**Chart Type:** `gauge`

## User Data Requirements

Columns needed: need a single **value** (aggregate)

## Data Arrays — Complete Replacement Guide

**2 array(s)** to replace with real data:

### [0] `data` (context: root)
```
data: [
        {
          value: 58.46,
          name: 'PLP'
        }
      ]
```

### [1] `data` (context: series)
```
data: [
          {
            value: +(Math.random() * 100).toFixed(2),
            name: 'PLP'
          }
        ]
```

## Agent Workflow

1. **Analyze** user table → identify columns matching the required format above
2. **Query DuckDB** → transform to match each data array's format
3. **Replace**: use **bracket-counting** to find each `data: [...]` → replace with real data
4. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: Gauge Barometer chart
titleCN: 气压表
category: gauge
difficulty: 6
*/
option = {
  series: [
    {
      type: 'gauge',
      min: 0,
      max: 100,
      splitNumber: 10,
      radius: '80%',
      axisLine: {
        lineStyle: {
          color: [[1, '#f00']],
          width: 3
        }
      },
      splitLine: {
        distance: -18,
        length: 18,
        lineStyle: {
          color: '#f00'
        }
      },
      axisTick: {
        distance: -12,
        length: 10,
        lineStyle: {
          color: '#f00'
        }
      },
      axisLabel: {
        distance: -50,
        color: '#f00',
        fontSize: 25
      },
      anchor: {
        show: true,
        size: 20,
        itemStyle: {
          borderColor: '#000',
          borderWidth: 2
        }
      },
      pointer: {
        offsetCenter: [0, '10%'],
        icon: 'path://M2090.36389,615.30999 L2090.36389,615.30999 C2091.48372,615.30999 2092.40383,616.194028 2092.44859,617.312956 L2096.90698,728.755929 C2097.05155,732.369577 2094.2393,735.416212 2090.62566,735.56078 C2090.53845,735.564269 2090.45117,735.566014 2090.36389,735.566014 L2090.36389,735.566014 C2086.74736,735.566014 2083.81557,732.63423 2083.81557,729.017692 C2083.81557,728.930412 2083.81732,728.84314 2083.82081,728.755929 L2088.2792,617.312956 C2088.32396,616.194028 2089.24407,615.30999 2090.36389,615.30999 Z',
        length: '115%',
        itemStyle: {
          color: '#000'
        }
      },
      detail: {
        valueAnimation: true,
        precision: 1
      },
      title: {
        offsetCenter: [0, '-50%']
      },
      data: [
        {
          value: 58.46,
          name: 'PLP'
        }
      ]
    },
    {
      type: 'gauge',
      min: 0,
      max: 60,
      splitNumber: 6,
      axisLine: {
        lineStyle: {
          color: [[1, '#000']],
          width: 3
        }
      },
      splitLine: {
        distance: -3,
        length: 18,
        lineStyle: {
          color: '#000'
        }
      },
      axisTick: {
        distance: 0,
        length: 10,
        lineStyle: {
          color: '#000'
        }
      },
      axisLabel: {
        distance: 10,
        fontSize: 25,
        color: '#000'
      },
      pointer: {
        show: false
      },
      title: {
        show: false
      },
      anchor: {
        show: true,
        size: 14,
        itemStyle: {
          color: '#000'
        }
      }
    }
  ]
};
setInterval(function () {
  myChart.setOption({
    series: [
      {
        type: 'gauge',
        data: [
          {
            value: +(Math.random() * 100).toFixed(2),
            name: 'PLP'
          }
        ]
      }
    ]
  });
}, 2000);
```
