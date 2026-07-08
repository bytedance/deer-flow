# matrix-confusion

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=matrix-confusion
**Chart Type:** `custom`

## User Data Requirements

Columns needed: check data arrays in reference code for required format

## Data Arrays — Complete Replacement Guide

**3 array(s)** to replace with real data:

### [0] `data` (context: root)
```
data: ['Positive', 'Negative']
```

### [1] `data` (context: root)
```
data: ['Positive', 'Negative']
```

### [2] `data` (context: series)
```
data: [
      ['Positive', 'Positive', 10],
      ['Positive', 'Negative', 2],
      ['Negative', 'Positive', 3],
      ['Negative', 'Negative', 5]
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
title: Confusion Matrix
category: matrix
titleCN: 混淆矩阵
difficulty: 3
since: 6.0.0
*/
const label = {
  fontSize: 16,
  color: '#555'
};
option = {
  matrix: {
    x: {
      data: ['Positive', 'Negative'],
      label
    },
    y: {
      data: ['Positive', 'Negative'],
      label
    },
    top: 80,
    width: 600,
    left: 'center'
  },
  series: {
    type: 'custom',
    coordinateSystem: 'matrix',
    data: [
      ['Positive', 'Positive', 10],
      ['Positive', 'Negative', 2],
      ['Negative', 'Positive', 3],
      ['Negative', 'Negative', 5]
    ],
    label: {
      show: true,
      formatter: (params) => {
        const value = params.value[2];
        return (
          '{name|' +
          (params.value[0] === params.value[1] ? 'True ' : 'False ') +
          params.value[1] +
          '}\n{value|' +
          value +
          '}'
        );
      },
      rich: {
        name: {
          color: '#fff',
          backgroundColor: '#999',
          textBorderColor: '#333',
          padding: 5,
          fontSize: 18
        },
        value: {
          color: '#444',
          textBorderWidth: 0,
          padding: 5,
          fontSize: 16,
          align: 'center'
        }
      }
    },
    renderItem: function (params, api) {
      const x = api.value(0);
      const y = api.value(1);
      const rect = api.layout([x, y]).rect;
      return {
        type: 'rect',
        shape: {
          x: rect.x,
          y: rect.y,
          width: rect.width,
          height: rect.height
        },
        style: api.style({
          fill: x === y ? '#8f8' : '#f88'
        })
      };
    }
  },
  graphic: {
    elements: [
      {
        type: 'text',
        style: {
          text: 'True Class',
          fill: '#333',
          font: 'bold 24px serif',
          textAlign: 'center'
        },
        x: (window.innerWidth - 600) / 2 + (600 / 6) * 4,
        y: 40
      },
      {
        type: 'text',
        style: {
          text: 'Predicted Class',
          fill: '#333',
          font: 'bold 24px serif',
          textAlign: 'center'
        },
        x: (window.innerWidth - 600) / 2 - 50,
        y: 270,
        rotation: Math.PI / 2
      }
    ]
  }
};
```
