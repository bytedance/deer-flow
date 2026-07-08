# gauge-car

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=gauge-car
**Chart Type:** `gauge`

## User Data Requirements

Columns needed: need a single **value** (aggregate)

## Data Arrays — Complete Replacement Guide

**7 array(s)** to replace with real data:

### [0] `data` (context: root)
```
data: [
        {
          value: 250,
          name: 'km/h'
        }
      ]
```

### [1] `data` (context: root)
```
data: [
        {
          value: 0,
          name: '当前位置：\n \n 中科路'
        }
      ]
```

### [2] `data` (context: root)
```
data: [
        {
          value: 0.6,
          name: '1/min x 1000'
        }
      ]
```

### [3] `data` (context: root)
```
data: [
        {
          value: 0,
          name: ''
        }
      ]
```

### [4] `data` (context: root)
```
data: [
        {
          value: 250,
          name: ''
        }
      ]
```

### [5] `data` (context: root)
```
data: [
        {
          value: 0.85,
          name: ''
        }
      ]
```

### [6] `data` (context: root)
```
data: [
        {
          value: -120,
          name: ''
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
title: Gauge Car
category: gauge
titleCN: 汽车仪表盘
difficulty: 8
*/
option = {
  backgroundColor: '#000',
  tooltip: {
    formatter: '{a} <br/>{b} : {c}%'
  },
  toolbox: {
    feature: {
      restore: {},
      saveAsImage: {}
    }
  },
  series: [
    // left
    {
      name: 'gauge 0',
      type: 'gauge',
      min: -200,
      max: 250,
      startAngle: -30,
      endAngle: -315,
      splitNumber: 9,
      radius: '35%',
      center: ['21%', '55%'],
      axisLine: {
        lineStyle: {
          color: [[1, '#AE96A6']]
        }
      },
      splitLine: {
        show: false
      },
      axisTick: {
        show: false
      },
      axisLabel: {
        show: false
      },
      anchor: {},
      pointer: {
        show: false
      },
      detail: {
        show: false
      },
      title: {
        fontSize: 12,
        fontWeight: 800,
        fontFamily: 'Arial',
        color: '#fff',
        offsetCenter: [0, '-60%']
      },
      progress: {
        show: true,
        width: 3,
        itemStyle: {
          color: '#fff'
        }
      },
      data: [
        {
          value: 250,
          name: 'km/h'
        }
      ]
    },
    {
      name: 'gauge 1',
      type: 'gauge',
      min: 0,
      max: 250,
      startAngle: -140,
      endAngle: -305,
      splitNumber: 5,
      radius: '35%',
      center: ['21%', '55%'],
      axisLine: {
        lineStyle: {
          color: [[1, '#AE96A6']]
        }
      },
      splitLine: {
        distance: -7,
        length: 12,
        lineStyle: {
          color: '#fff',
          width: 4
        }
      },
      axisTick: {
        distance: -8,
        length: 8,
        lineStyle: {
          color: '#fff',
          width: 2
        }
      },
      axisLabel: {
        distance: 14,
        fontSize: 18,
        fontWeight: 800,
        fontFamily: 'Arial',
        color: '#fff'
      },
      anchor: {},
      pointer: {
        icon: 'path://M-36.5,23.9L-41,4.4c-0.1-0.4-0.4-0.7-0.7-0.7c-0.5-0.1-1.1,0.2-1.2,0.7l-4.5,19.5c0,0.1,0,0.1,0,0.2v92.3c0,0.6,0.4,1,1,1h9c0.6,0,1-0.4,1-1V24.1C-36.5,24-36.5,23.9-36.5,23.9z M-39.5,114.6h-5v-85h5V114.6z',
        width: 5,
        length: '40%',
        offsetCenter: [0, '-58%'],
        itemStyle: {
          color: '#f00',
          shadowColor: 'rgba(255, 0, 0)',
          shadowBlur: 5,
          shadowOffsetY: 2
        }
      },
      title: {
        color: '#fff',
        fontSize: 14,
        fontWeight: 800,
        fontFamily: 'Arial',
        offsetCenter: [0, 0]
      },
      detail: {
        show: false
      },
      data: [
        {
          value: 0,
          name: '当前位置：\n \n 中科路'
        }
      ]
    },
    // middle
    {
      name: 'gauge 2',
      type: 'gauge',
      min: 0,
      max: 8,
      z: 10,
      startAngle: 210,
      endAngle: -30,
      splitNumber: 8,
      radius: '50%',
      center: ['50%', '50%'],
      axisLine: {
        show: true,
        lineStyle: {
          width: 0,
          color: [
            [0.825, '#fff'],
            [1, '#f00']
          ]
        }
      },
      splitLine: {
        distance: 20,
        length: 15,
        lineStyle: {
          color: 'auto',
          width: 4,
          shadowColor: 'rgba(255, 255, 255, 0.5)',
          shadowBlur: 15,
          shadowOffsetY: -10
        }
      },
      axisTick: {
        distance: 20,
        length: 8,
        lineStyle: {
          color: 'auto',
          width: 2,
          shadowColor: 'rgba(255, 255, 255)',
          shadowBlur: 10,
          shadowOffsetY: -10
        }
      },
      axisLabel: {
        distance: 10,
        fontSize: 35,
        fontWeight: 800,
        fontFamily: 'Arial',
        color: '#fff'
      },
      anchor: {},
      pointer: {
        icon: 'path://M-36.5,23.9L-41,4.4c-0.1-0.4-0.4-0.7-0.7-0.7c-0.5-0.1-1.1,0.2-1.2,0.7l-4.5,19.5c0,0.1,0,0.1,0,0.2v92.3c0,0.6,0.4,1,1,1h9c0.6,0,1-0.4,1-1V24.1C-36.5,24-36.5,23.9-36.5,23.9z M-39.5,114.6h-5v-85h5V114.6z',
        width: 10,
        offsetCenter: [0, '-10%'],
        length: '75%',
        itemStyle: {
          color: '#f00',
          shadowColor: 'rgba(255, 0, 0)',
          shadowBlur: 5,
          shadowOffsetY: 3
        }
      },
      title: {
        color: '#fff',
        fontSize: 12,
        fontWeight: 800,
        fontFamily: 'Arial',
        offsetCenter: [0, '-50%']
      },
      data: [
        {
          value: 0.6,
          name: '1/min x 1000'
        }
      ],
      detail: {
        show: false
      }
    },
    {
      name: 'gauge 3',
      type: 'gauge',
      min: 0,
      max: 8,
      z: 10,
      splitNumber: 8,
      radius: '50%',
      axisLine: {
        lineStyle: {
          width: 14,
          color: [[1, '#000']]
        }
      },
      splitLine: {
        show: false
      },
      axisTick: {
        show: false
      },
      axisLabel: {
        show: false
      },
      anchor: {},
      pointer: {
        show: false
      },
      title: {
        show: false
      },
      detail: {
        offsetCenter: ['25%', '50%'],
        formatter: '{a|{value}}{b|km/h}',
        rich: {
          a: {
            fontSize: 60,
            fontWeight: 800,
            fontFamily: 'Arial',
            color: '#fff',
            align: 'center',
            padding: [0, 5, 0, 0]
          },
          b: {
            fontSize: 14,
            fontWeight: 800,
            fontFamily: 'Arial',
            color: '#fff',
            padding: [0, 0, 20, 0]
          }
        }
      },
      // value is speed
      data: [
        {
          value: 0,
          name: ''
        }
      ]
    },
    // right
    {
      name: 'gauge 4',
      type: 'gauge',
      min: 0,
      max: 8,
      startAngle: 135,
      endAngle: -150,
      splitNumber: 8,
      radius: '35%',
      center: ['79%', '55%'],
      axisLine: {
        lineStyle: {
          color: [[1, '#AE96A6']]
        }
      },
      splitLine: {
        show: false
      },
      axisTick: {
        show: false
      },
      axisLabel: {
        show: false
      },
      anchor: {},
      pointer: {
        show: false
      },
      title: {},
      detail: {
        offsetCenter: ['-15%', 0],
        formatter: [
          '{a|                  00:00}',
          '{a|行驶时间       0:00}{b| h}',
          '{a|行驶距离        0.0}{b| km}',
          '{a|平均耗能        ---}{b| 1/100km}',
          '{a|平均速度        ---}{b| km/h}'
        ].join('\n'),
        rich: {
          a: {
            fontSize: 14,
            fontWeight: 800,
            fontFamily: 'Arial',
            lineHeight: 22,
            color: '#fff',
            align: 'left'
          },
          b: {
            fontWeight: 600,
            fontFamily: 'Arial',
            fontSize: 12,
            lineHeight: 22,
            color: '#fff',
            align: 'left'
          }
        }
      },
      progress: {
        show: true,
        width: 3,
        itemStyle: {
          color: '#fff'
        }
      },
      data: [
        {
          value: 250,
          name: ''
        }
      ]
    },
    {
      name: 'gauge 5',
      type: 'gauge',
      min: 0,
      max: 1,
      startAngle: 125,
      endAngle: 55,
      splitNumber: 2,
      radius: '34%',
      center: ['79%', '55.3%'],
      axisLine: {
        lineStyle: {
          width: 9,
          color: [
            [0.15, '#f00'],
            [1, 'rgba(255, 0, 0, 0)']
          ]
        }
      },
      splitLine: {
        distance: -14,
        length: 16,
        lineStyle: {
          color: '#fff',
          width: 4
        }
      },
      axisTick: {
        distance: -14,
        length: 10,
        lineStyle: {
          color: '#fff',
          width: 2
        }
      },
      axisLabel: {
        distance: 12,
        fontSize: 18,
        fontWeight: 800,
        fontFamily: 'Arial',
        color: '#fff',
        formatter: function (value) {
          if (value === 0.5) {
            return '2/4';
          }
          if (value === 1) {
            return '4/4';
          }
          return value + '';
        }
      },
      progress: {
        show: true,
        width: 5,
        itemStyle: {
          color: '#fff'
        }
      },
      anchor: {
        show: true,
        itemStyle: {},
        offsetCenter: ['-22%', '-57%'],
        size: 18,
        icon: 'path://M1.11979167,1.11111112 C1.11979167,0.497461393 1.61725306,0 2.23090279,0 L12.2309028,0 C12.8445525,1.43824153e-08 13.3420139,0.497461403 13.3420139,1.11111112 L13.3420139,10 L15.5642361,10 C16.7915356,10 17.7864583,10.9949228 17.7864583,12.2222222 L17.7864583,16.6666667 C17.7865523,17.28025 18.2839861,17.7776077 18.8975694,17.7776077 C19.5111527,17.7776077 20.0085866,17.28025 20.0086805,16.6666667 L20.0086805,8.88888888 L17.7864583,8.88888888 C17.1728086,8.88888888 16.6753472,8.3914275 16.6753472,7.77777779 L16.6753472,3.79333333 L15.6197917,2.73777777 C15.1859413,2.30392741 15.1859413,1.60051702 15.6197917,1.16666667 L15.6197917,1.16666667 C16.053642,0.732816318 16.7570524,0.732816318 17.1909028,1.16666667 L21.9053472,5.88111112 C22.1140468,6.08922811 22.2312072,6.37193273 22.2309028,6.66666667 L22.2309028,16.6666667 C22.2309028,18.5076158 20.7385186,20 18.8975695,20 C17.0566203,20 15.5642361,18.5076158 15.5642361,16.6666667 L15.5642361,12.2222222 L13.3420139,12.2222222 L13.3420139,17.7777778 L13.3420139,17.7777778 C13.9556636,17.7777778 14.453125,18.2752392 14.453125,18.8888889 L14.453125,18.8888889 C14.453125,19.5025386 13.9556636,20 13.3420139,20 L1.11979165,20 C0.506141934,20 0.00868054688,19.5025386 0.00868054687,18.8888889 L0.00868054687,18.8888889 C0.00868054688,18.2752392 0.506141934,17.7777778 1.11979165,17.7777778 L1.11979167,17.7777778 L1.11979167,1.11111112 Z M3.34201388,2.22222221 L3.34201388,8.88888888 L11.1197917,8.88888888 L11.1197917,2.22222221 L3.34201388,2.22222221 Z'
      },
      pointer: {
        show: false
      },
      title: {},
      detail: {
        offsetCenter: ['10%', '-56%'],
        formatter: '{a|831}{b| km}',
        rich: {
          a: {
            fontSize: 15,
            fontWeight: 800,
            fontFamily: 'Arial',
            color: '#fff'
          },
          b: {
            fontWeight: 600,
            fontFamily: 'Arial',
            fontSize: 12,
            color: '#fff'
          }
        }
      },
      data: [
        {
          value: 0.85,
          name: ''
        }
      ]
    },
    {
      name: 'gauge 6',
      type: 'gauge',
      min: -120,
      max: -60,
      startAngle: 230,
      endAngle: 310,
      clockwise: false,
      splitNumber: 2,
      radius: '35%',
      center: ['79%', '55%'],
      axisLine: {
        lineStyle: {
          color: [
            [1, '#AE96A6'],
            [1.1, '#f00']
          ]
        }
      },
      splitLine: {
        distance: -8,
        length: 12,
        lineStyle: {
          color: '#fff',
          width: 4
        }
      },
      axisTick: {
        splitNumber: 3,
        length: 8,
        distance: -8,
        lineStyle: {
          color: '#fff',
          width: 2
        }
      },
      axisLabel: {
        distance: 14,
        fontSize: 18,
        fontWeight: 800,
        fontFamily: 'Arial',
        color: '#fff',
        formatter: function (value) {
          return -value + '';
        }
      },
      anchor: {
        show: true,
        itemStyle: {},
        offsetCenter: [0, '55%'],
        size: 20,
        icon: 'path://M-34.1-1.1L-34.1-1.1c0-0.3-0.3-0.6-0.6-0.6h-3.6v-1.5c0-0.5-0.2-0.9-0.6-1.1s-0.9-0.2-1.3,0c-0.4,0.2-0.6,0.7-0.6,1.1V7.9c0,0,0,0.1,0,0.1c-0.8,0.5-1.2,1.5-0.9,2.5c0.3,0.9,1.1,1.6,2.1,1.6c1,0,1.8-0.6,2.1-1.5c0.3-0.9,0-1.9-0.8-2.5V6.3h3.5c0.4,0,0.7-0.3,0.7-0.7l0,0c0-0.4-0.3-0.7-0.7-0.7h-3.5V2.9h3.5c0.4,0,0.7-0.3,0.7-0.7l0,0c0-0.4-0.3-0.7-0.7-0.7h-3.5v-2.1h3.6C-34.4-0.5-34.1-0.8-34.1-1.1z M-44.9,11.6c-0.7,0-1.4-0.2-2-0.6c-0.4-0.3-0.9-0.4-1.4-0.4c-0.4,0-0.9,0.2-1.2,0.4c-0.4,0.2-1.4-0.9-0.9-1.3c0.6-0.4,1.3-0.6,2-0.7c0.8,0,1.5,0.2,2.2,0.5c0.4,0.3,0.9,0.4,1.3,0.4c0.6,0,1.1-0.2,1.5-0.6s1.6,0.7,0.9,1.3S-44,11.6-44.9,11.6L-44.9,11.6z M-34.3,11.6c-0.7,0-1.4-0.3-2-0.7c-0.6-0.4,0.5-1.6,0.9-1.3s0.8,0.4,1.2,0.4c0.5,0,1-0.1,1.4-0.4c0.6-0.3,1.3-0.5,2-0.6h0c0.9,0,1.7,0.3,2.4,0.9c0.7,0.5-0.5,1.6-0.9,1.3c-0.4-0.3-1-0.6-1.5-0.6h0c-0.5,0-0.9,0.2-1.3,0.4c-0.6,0.3-1.3,0.5-2,0.6H-34.3z M-33.5,16.3c-0.7,0-1.4-0.3-1.9-0.8c-0.4-0.3-0.6-0.5-1-0.5c-0.4,0-0.7,0.2-1,0.4c-0.6,0.5-1.3,0.7-2,0.7c-0.7,0-1.4-0.3-1.9-0.8c-0.2-0.3-0.6-0.4-0.9-0.4c-0.4,0-0.7,0.1-1.1,0.5c-0.6,0.5-1.3,0.7-2.1,0.7c-0.7-0.1-1.4-0.4-1.9-0.9c-0.4-0.3-0.6-0.5-1-0.5c-0.3,0-0.6,0.2-0.9,0.4s-1.6-0.7-1.1-1.2c0.5-0.5,1.2-0.8,1.9-0.9c1-0.1,1.6,0.4,2.1,0.8c0.3,0.3,0.6,0.5,1,0.5c0.4,0,0.6-0.1,1-0.4c0.6-0.5,1.4-0.8,2.1-0.8c0.7,0,1.4,0.3,1.9,0.8c0.2,0.2,0.6,0.4,0.9,0.4c0.4,0,0.6-0.1,1-0.4c0.6-0.5,1.3-0.7,2-0.7c0.8,0,1.5,0.3,2,0.9c0.4,0.3,0.6,0.4,0.9,0.4c0.3,0,0.7-0.2,1.1-0.5c0.5-0.4,1.2-0.9,2.3-0.8c0.7,0,1.4,0.3,1.9,0.7c0.5,0.4-0.7,1.5-1,1.3s-0.6-0.4-1-0.4c-0.4,0-0.7,0.2-1.2,0.5C-32,15.9-32.7,16.2-33.5,16.3L-33.5,16.3z'
      },
      pointer: {
        icon: 'path://M2.9,0.7L2.9,0.7c1.4,0,2.6,1.2,2.6,2.6v115c0,1.4-1.2,2.6-2.6,2.6l0,0c-1.4,0-2.6-1.2-2.6-2.6V3.3C0.3,1.9,1.4,0.7,2.9,0.7z',
        width: 15,
        length: '4',
        offsetCenter: [0, '-90%'],
        itemStyle: {
          color: '#f00'
        }
      },
      title: {},
      detail: {
        show: false
      },
      data: [
        {
          value: -120,
          name: ''
        }
      ]
    }
  ]
};
```
