# chord-lineStyle-color

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=chord-lineStyle-color
**Chart Type:** `chord`

## User Data Requirements

Columns needed: check data arrays in reference code for required format

## Data Arrays — Complete Replacement Guide

**2 array(s)** to replace with real data:

### [0] `data` (context: root)
```
data: [{ name: 'A' }, { name: 'B' }, { name: 'C' }, { name: 'D' }]
```

### [1] `links` (context: root)
```
links: [
      { source: 'A', target: 'B', value: 30 },
      { source: 'A', target: 'C', value: 20 },
      { source: 'B', target: 'D', value: 10 },
...
```

## Agent Workflow

1. **Analyze** user table → identify columns matching the required format above
2. **Query DuckDB** → transform to match each data array's format
3. **Replace**: use **bracket-counting** to find each `data: [...]` → replace with real data
4. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: Chord lineStyle.color
category: chord
titleCN: 和弦图边的颜色
difficulty: 3
since: 6.0.0
*/
function generateSeries(id, lineColor) {
  return {
    type: 'chord',
    label: { show: true },
    center: [((id * 2 + 1) / 6) * 100 + '%', '50%'],
    radius: ['28%', '32%'],
    lineStyle: {
      color: lineColor
    },
    data: [{ name: 'A' }, { name: 'B' }, { name: 'C' }, { name: 'D' }],
    links: [
      { source: 'A', target: 'B', value: 30 },
      { source: 'A', target: 'C', value: 20 },
      { source: 'B', target: 'D', value: 10 },
      { source: 'C', target: 'A', value: 15 },
      { source: 'D', target: 'A', value: 25 }
    ]
  };
}
function generateTitle(id, text) {
  return {
    text,
    left: ((id * 2 + 1) / 6) * 100 + '%',
    top: '25%',
    textAlign: 'center',
    padding: 0
  };
}
option = {
  tooltip: {},
  legend: {},
  series: [
    generateSeries(0, 'source'),
    generateSeries(1, 'target'),
    generateSeries(2, 'gradient')
  ],
  title: [
    {
      text: 'lineStyle.color',
      textStyle: {
        fontSize: 24
      }
    },
    generateTitle(0, 'source'),
    generateTitle(1, 'target'),
    generateTitle(2, 'gradient')
  ]
};
```
