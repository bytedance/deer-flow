# matrix-mini-bar-data-collection

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=matrix-mini-bar-data-collection
**Chart Type:** `group`

## User Data Requirements

Columns needed: check data arrays in reference code for required format

## Data Arrays — Complete Replacement Guide

**2 array(s)** to replace with real data:

### [0] `source` (context: dataset)
```
source: 
```

### [1] `children` (context: root)
```
children: [
        {
          type: 'rect',
          shape: { x: barX, y: barY, width, height },
          style: api.style({
            fill: '#0...
```

## Agent Workflow

1. **Analyze** user table → identify columns matching the required format above
2. **Query DuckDB** → transform to match each data array's format
3. **Replace**: use **bracket-counting** to find each `data: [...]` → replace with real data
4. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: Matrix Header Data Collection (Mini Bar)
category: matrix
titleCN: 矩阵坐标系表头数据自动收集（以微型条形图为例）
noExplore: true
difficulty: 3
since: 6.0.0
*/
/**
 * Each section contain some charts and components.
 */
function makeRenderItem(xDim, yDim, valDim, dataExtent) {
  return function (params, api) {
    const xval = api.value(xDim);
    const yval = api.value(yDim);
    const labelVal = api.value(valDim);
    const rect = api.layout([xval, yval]).rect;
    if (!rect) {
      return;
    }
    const height = rect.height * 0.2;
    const barY = rect.y + ((rect.height - height) / 4) * 3;
    const barX = rect.x + rect.width * 0.15;
    const widthMax = rect.width * 0.5;
    const width = linearMap(labelVal, dataExtent, [0, widthMax]);
    return {
      type: 'group',
      children: [
        {
          type: 'rect',
          shape: { x: barX, y: barY, width, height },
          style: api.style({
            fill: '#0ca8df'
          })
        },
        {
          type: 'text',
          x: barX,
          y: rect.y + (rect.height / 4) * 1.5,
          style: {
            text: labelVal + '',
            fill: '#333',
            align: 'left',
            verticalAlign: 'middle'
          }
        }
      ]
    };
  };
}
function linearMap(val, domain, range) {
  const d0 = domain[0];
  const d1 = domain[1];
  const r0 = range[0];
  const r1 = range[1];
  const subDomain = d1 - d0;
  const subRange = r1 - r0;
  return subDomain === 0
    ? subRange === 0
      ? r0
      : (r0 + r1) / 2
    : val === d0
    ? r0
    : val === d1
    ? r1
    : ((val - d0) / subDomain) * subRange + r0;
}
const _dataExtent = [0, 10000];
option = {
  dataset: {
    source: [
      ['2021-02-01', 'amount', 1212, 'file', 2321, 'Q', 1412],
      ['2021-02-02', 'amount', 7181, 'file', 2114, 'Q', 1402],
      ['2021-02-03', 'amount', 2763, 'file', 4212, 'Q', 8172],
      ['2021-02-04', 'amount', 6122, 'file', 2942, 'Q', 6121],
      ['2021-02-05', 'amount', 4221, 'file', 3411, 'Q', 1987],
      ['2021-02-06', 'amount', 7221, 'file', 5121, 'Q', 1303],
      ['2021-02-07', 'amount', 5121, 'file', 4121, 'Q', 1819],
      ['2021-02-08', 'amount', 6121, 'file', 3121, 'Q', 2303],
      ['2021-02-09', 'amount', 7121, 'file', 2121, 'Q', 3303],
      ['2021-02-10', 'amount', 8121, 'file', 1121, 'Q', 4303]
    ]
  },
  matrix: {
    // matrix.x/y.data is not specified, which means they will be collected from
    // `dataset.source` (or `series.data`, if any).
    // All of values under the dimensions specified by `series.encode.x/y` will be
    // auto-collected as `matrix.x/y.data`.
    x: {
      levelSize: 50,
      itemStyle: { color: '#f0f8ff' },
      label: { fontWeight: 'bold' }
    }
  },
  series: [
    {
      type: 'custom',
      coordinateSystem: 'matrix',
      encode: { x: 1, y: 0 },
      renderItem: makeRenderItem(1, 0, 2, _dataExtent)
    },
    {
      type: 'custom',
      coordinateSystem: 'matrix',
      encode: { x: 3, y: 0 },
      renderItem: makeRenderItem(3, 0, 4, _dataExtent)
    },
    {
      type: 'custom',
      coordinateSystem: 'matrix',
      encode: { x: 5, y: 0 },
      renderItem: makeRenderItem(5, 0, 6, _dataExtent)
    }
  ]
};
```
