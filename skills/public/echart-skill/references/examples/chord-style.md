# chord-style

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=chord-style
**Chart Type:** `chord`

## User Data Requirements

Columns needed: check data arrays in reference code for required format

## Data Arrays — Complete Replacement Guide

**2 array(s)** to replace with real data:

### [0] `data` (context: series)
```
data: [
        { name: 'A' },
        { name: 'B' },
        { name: 'C' },
        { name: 'D' },
        { name: 'E' },
        { name: 'F' },
    ...
```

### [1] `links` (context: root)
```
links: 
```

## Agent Workflow

1. **Analyze** user table → identify columns matching the required format above
2. **Query DuckDB** → transform to match each data array's format
3. **Replace**: use **bracket-counting** to find each `data: [...]` → replace with real data
4. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: Chord Style
category: chord
titleCN: 和弦图样式
difficulty: 10
since: 6.0.0
*/
option = {
  tooltip: {},
  legend: {},
  series: [
    {
      type: 'chord',
      padAngle: 1,
      center: ['50%', '48%'],
      radius: ['70%', '80%'],
      data: [
        { name: 'A' },
        { name: 'B' },
        { name: 'C' },
        { name: 'D' },
        { name: 'E' },
        { name: 'F' },
        { name: 'G' }
      ],
      itemStyle: {
        borderRadius: [0, 15],
        borderWidth: 2,
        borderColor: '#fff'
      },
      lineStyle: {
        opacity: 0.3,
        color: 'gradient' // or 'source' (default), 'target'
      },
      emphasis: {
        focus: 'self' // or 'none', 'adjacency' (default)
      },
      label: {
        show: true,
        position: 'inside',
        color: '#fff',
        fontWeight: 'bold'
      },
      links: [
        { source: 'A', target: 'B', value: 14 },
        { source: 'A', target: 'C', value: 8 },
        { source: 'B', target: 'C', value: 20 },
        { source: 'B', target: 'E', value: 15 },
        { source: 'C', target: 'B', value: 8 },
        { source: 'C', target: 'E', value: 3 },
        { source: 'D', target: 'A', value: 12 },
        { source: 'D', target: 'B', value: 3 },
        { source: 'E', target: 'A', value: 15 },
        { source: 'E', target: 'C', value: 5 },
        { source: 'F', target: 'C', value: 5 },
        { source: 'G', target: 'A', value: 6 },
        { source: 'G', target: 'B', value: 8 },
        { source: 'G', target: 'D', value: 4 }
      ]
    }
  ]
};
```
