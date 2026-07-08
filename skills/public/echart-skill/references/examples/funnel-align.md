# funnel-align

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=funnel-align
**Chart Type:** `funnel`

## User Data Requirements

Columns needed: need **stage** + **count** columns

## Data Arrays — Complete Replacement Guide

**5 array(s)** to replace with real data:

### [0] `data` (context: legend)
```
data: ['Prod A', 'Prod B', 'Prod C', 'Prod D', 'Prod E']
```

### [1] `data` (context: series)
```
data: [
        { value: 60, name: 'Prod C' },
        { value: 30, name: 'Prod D' },
        { value: 10, name: 'Prod E' },
        { value: 80, name...
```

### [2] `data` (context: root)
```
data: [
        { value: 60, name: 'Prod C' },
        { value: 30, name: 'Prod D' },
        { value: 10, name: 'Prod E' },
        { value: 80, name...
```

### [3] `data` (context: root)
```
data: [
        { value: 60, name: 'Prod C' },
        { value: 30, name: 'Prod D' },
        { value: 10, name: 'Prod E' },
        { value: 80, name...
```

### [4] `data` (context: root)
```
data: [
        { value: 60, name: 'Prod C' },
        { value: 30, name: 'Prod D' },
        { value: 10, name: 'Prod E' },
        { value: 80, name...
```

## Agent Workflow

1. **Analyze** user table → identify columns matching the required format above
2. **Query DuckDB** → transform to match each data array's format
3. **Replace**: use **bracket-counting** to find each `data: [...]` → replace with real data
4. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: Funnel Compare
category: funnel
titleCN: 漏斗图(对比)
*/
option = {
  title: {
    text: 'Funnel Compare',
    subtext: 'Fake Data',
    left: 'left',
    top: 'bottom'
  },
  tooltip: {
    trigger: 'item',
    formatter: '{a} <br/>{b} : {c}%'
  },
  toolbox: {
    show: true,
    orient: 'vertical',
    top: 'center',
    feature: {
      dataView: { readOnly: false },
      restore: {},
      saveAsImage: {}
    }
  },
  legend: {
    orient: 'vertical',
    left: 'left',
    data: ['Prod A', 'Prod B', 'Prod C', 'Prod D', 'Prod E']
  },
  series: [
    {
      name: 'Funnel',
      type: 'funnel',
      width: '40%',
      height: '45%',
      left: '5%',
      top: '50%',
      funnelAlign: 'right',
      data: [
        { value: 60, name: 'Prod C' },
        { value: 30, name: 'Prod D' },
        { value: 10, name: 'Prod E' },
        { value: 80, name: 'Prod B' },
        { value: 100, name: 'Prod A' }
      ]
    },
    {
      name: 'Pyramid',
      type: 'funnel',
      width: '40%',
      height: '45%',
      left: '5%',
      top: '5%',
      sort: 'ascending',
      funnelAlign: 'right',
      data: [
        { value: 60, name: 'Prod C' },
        { value: 30, name: 'Prod D' },
        { value: 10, name: 'Prod E' },
        { value: 80, name: 'Prod B' },
        { value: 100, name: 'Prod A' }
      ]
    },
    {
      name: 'Funnel',
      type: 'funnel',
      width: '40%',
      height: '45%',
      left: '55%',
      top: '5%',
      funnelAlign: 'left',
      data: [
        { value: 60, name: 'Prod C' },
        { value: 30, name: 'Prod D' },
        { value: 10, name: 'Prod E' },
        { value: 80, name: 'Prod B' },
        { value: 100, name: 'Prod A' }
      ]
    },
    {
      name: 'Pyramid',
      type: 'funnel',
      width: '40%',
      height: '45%',
      left: '55%',
      top: '50%',
      sort: 'ascending',
      funnelAlign: 'left',
      data: [
        { value: 60, name: 'Prod C' },
        { value: 30, name: 'Prod D' },
        { value: 10, name: 'Prod E' },
        { value: 80, name: 'Prod B' },
        { value: 100, name: 'Prod A' }
      ]
    }
  ]
};
```
