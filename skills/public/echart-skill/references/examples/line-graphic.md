# line-graphic

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=line-graphic
**Chart Type:** `value`

## User Data Requirements

Columns needed: check data arrays in reference code for required format

## Data Arrays — Complete Replacement Guide

**5 array(s)** to replace with real data:

### [0] `data` (context: legend)
```
data: ['Altitude (km) vs Temperature (°C)']
```

### [1] `data` (context: yAxis)
```
data: ['0', '10', '20', '30', '40', '50', '60', '70', '80']
```

### [2] `data` (context: series)
```
data: [15, -50, -56.5, -46.5, -22.1, -2.5, -27.7, -55.7, -76.5]
```

### [3] `children` (context: root)
```
children: 
```

### [4] `children` (context: root)
```
children: 
```

## Agent Workflow

1. **Analyze** user table → identify columns matching the required format above
2. **Query DuckDB** → transform to match each data array's format
3. **Replace**: use **bracket-counting** to find each `data: [...]` → replace with real data
4. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: Custom Graphic Component
titleCN: 自定义图形组件
category: line, graphic
difficulty: 9
*/
option = {
  legend: {
    data: ['Altitude (km) vs Temperature (°C)']
  },
  tooltip: {
    trigger: 'axis',
    formatter: 'Temperature : <br/>{b}km : {c}°C'
  },
  grid: {
    left: '3%',
    right: '4%',
    bottom: '3%',
    containLabel: true
  },
  xAxis: {
    type: 'value',
    axisLabel: {
      formatter: '{value} °C'
    }
  },
  yAxis: {
    type: 'category',
    axisLine: { onZero: false },
    axisLabel: {
      formatter: '{value} km'
    },
    boundaryGap: true,
    data: ['0', '10', '20', '30', '40', '50', '60', '70', '80']
  },
  graphic: [
    {
      type: 'group',
      rotation: Math.PI / 4,
      bounding: 'raw',
      right: 110,
      bottom: 110,
      z: 100,
      children: [
        {
          type: 'rect',
          left: 'center',
          top: 'center',
          z: 100,
          shape: {
            width: 400,
            height: 50
          },
          style: {
            fill: 'rgba(0,0,0,0.3)'
          }
        },
        {
          type: 'text',
          left: 'center',
          top: 'center',
          z: 100,
          style: {
            fill: '#fff',
            text: 'ECHARTS LINE CHART',
            font: 'bold 26px sans-serif'
          }
        }
      ]
    },
    {
      type: 'group',
      left: '10%',
      top: 'center',
      children: [
        {
          type: 'rect',
          z: 100,
          left: 'center',
          top: 'middle',
          shape: {
            width: 240,
            height: 90
          },
          style: {
            fill: '#fff',
            stroke: '#555',
            lineWidth: 1,
            shadowBlur: 8,
            shadowOffsetX: 3,
            shadowOffsetY: 3,
            shadowColor: 'rgba(0,0,0,0.2)'
          }
        },
        {
          type: 'text',
          z: 100,
          left: 'center',
          top: 'middle',
          style: {
            fill: '#333',
            width: 220,
            overflow: 'break',
            text: 'xAxis represents temperature in °C, yAxis represents altitude in km, An image watermark in the upper right, This text block can be placed in any place',
            font: '14px Microsoft YaHei'
          }
        }
      ]
    }
  ],
  series: [
    {
      name: '高度(km)与气温(°C)变化关系',
      type: 'line',
      smooth: true,
      data: [15, -50, -56.5, -46.5, -22.1, -2.5, -27.7, -55.7, -76.5]
    }
  ]
};
```
