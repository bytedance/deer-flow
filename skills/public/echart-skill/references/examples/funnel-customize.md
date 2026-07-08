# funnel-customize

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=funnel-customize
**Chart Type:** `funnel`

## User Data Requirements

Columns needed: need **stage** + **count** columns

## Data Arrays — Complete Replacement Guide

**3 array(s)** to replace with real data:

### [0] `data` (context: legend)
```
data: ['Show', 'Click', 'Visit', 'Inquiry', 'Order']
```

### [1] `data` (context: root)
```
data: [
        { value: 60, name: 'Visit' },
        { value: 40, name: 'Inquiry' },
        { value: 20, name: 'Order' },
        { value: 80, name:...
```

### [2] `data` (context: root)
```
data: [
        { value: 30, name: 'Visit' },
        { value: 10, name: 'Inquiry' },
        { value: 5, name: 'Order' },
        { value: 50, name: ...
```

## Agent Workflow

1. **Analyze** user table → identify columns matching the required format above
2. **Query DuckDB** → transform to match each data array's format
3. **Replace**: use **bracket-counting** to find each `data: [...]` → replace with real data
4. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: Customized Funnel
category: funnel
titleCN: 漏斗图
*/
option = {
  title: {
    text: 'Funnel'
  },
  tooltip: {
    trigger: 'item',
    formatter: '{a} <br/>{b} : {c}%'
  },
  toolbox: {
    feature: {
      dataView: { readOnly: false },
      restore: {},
      saveAsImage: {}
    }
  },
  legend: {
    data: ['Show', 'Click', 'Visit', 'Inquiry', 'Order']
  },
  series: [
    {
      name: 'Expected',
      type: 'funnel',
      left: '10%',
      width: '80%',
      label: {
        formatter: '{b}Expected'
      },
      labelLine: {
        show: false
      },
      itemStyle: {
        opacity: 0.7
      },
      emphasis: {
        label: {
          position: 'inside',
          formatter: '{b}Expected: {c}%'
        }
      },
      data: [
        { value: 60, name: 'Visit' },
        { value: 40, name: 'Inquiry' },
        { value: 20, name: 'Order' },
        { value: 80, name: 'Click' },
        { value: 100, name: 'Show' }
      ]
    },
    {
      name: 'Actual',
      type: 'funnel',
      left: '10%',
      width: '80%',
      maxSize: '80%',
      label: {
        position: 'inside',
        formatter: '{c}%',
        color: '#fff'
      },
      itemStyle: {
        opacity: 0.5,
        borderColor: '#fff',
        borderWidth: 2
      },
      emphasis: {
        label: {
          position: 'inside',
          formatter: '{b}Actual: {c}%'
        }
      },
      data: [
        { value: 30, name: 'Visit' },
        { value: 10, name: 'Inquiry' },
        { value: 5, name: 'Order' },
        { value: 50, name: 'Click' },
        { value: 80, name: 'Show' }
      ],
      // Ensure outer shape will not be over inner shape when hover.
      z: 100
    }
  ]
};
```
