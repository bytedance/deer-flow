# Dataset 数据集组件

> **Source:** `echarts-docs/handbook/zh/concepts/dataset.md`

## Purpose

The `dataset` component (ECharts 4+) centralizes data management, separating data from chart configuration. Instead of putting data inside each `series`, declare it once in `dataset`.

## Data Formats

`dataset.source` accepts three formats:

### 1. 二维数组 (2D Array) — Most Common
```javascript
dataset: {
  source: [
    ['product', '2015', '2016', '2017'],  // Header row (optional)
    ['Matcha Latte', 43.3, 85.8, 93.7],
    ['Milk Tea', 83.1, 73.4, 55.1],
    ['Cheese Cocoa', 86.4, 65.2, 82.5]
  ]
}
```

### 2. 对象数组 (Array of Objects)
```javascript
dataset: {
  source: [
    { product: 'Matcha Latte', count: 823, score: 95.8 },
    { product: 'Milk Tea', count: 235, score: 81.4 }
  ]
}
```

### 3. 按列键值对 (Columnar / Key-Value)
```javascript
dataset: {
  source: {
    product: ['Matcha Latte', 'Milk Tea'],
    count: [823, 235],
    score: [95.8, 81.4]
  }
}
```
⚠️ This format does NOT support `seriesLayoutBy`.

## seriesLayoutBy

Controls how series map to rows vs columns:

- `'column'` (default) — Each column after the first becomes a series
- `'row'` — Each row becomes a series

## encode: Data-to-Visual Mapping

`series.encode` maps data dimensions to chart visual properties:

```javascript
// Cartesian (直角坐标系)
encode: { x: 'amount', y: 'product' }

// Polar (极坐标系)
encode: { radius: 3, angle: 2 }

// Geo (地理坐标系)
encode: { lng: 3, lat: 2 }

// Non-coordinate charts (pie, funnel — 无坐标系图表)
encode: { value: 3 }

// Universal properties
encode: { tooltip: [1, 2], seriesName: 0, itemId: 3 }
```

## Dimensions

Define dimension names and types for type safety:

```javascript
dataset: {
  dimensions: [
    { name: 'score', type: 'number' },
    { name: 'product', type: 'ordinal' },  // category/text
    { name: 'date', type: 'time' },
    { name: 'value', type: 'float' }       // performance optimization
  ],
  source: [...]
}
```

Dimension types: `'number'` (default), `'ordinal'`, `'time'`, `'float'`, `'int'`

## Multiple Datasets

```javascript
dataset: [
  { source: [...] },    // index 0
  { source: [...] }     // index 1
],
series: [
  { type: 'bar', datasetIndex: 0 },
  { type: 'line', datasetIndex: 1 }
]
```

## Important Notes

1. **Dimension index starts from 0** — the first column is dimension index 0
2. `series.data` still works and takes priority over `dataset`
3. **NOT supported by**: treemap, graph, lines — these still need `series.data`
4. **NOT supported by** `appendData` (incremental rendering)
5. `series.dimensions` overrides `dataset.dimensions`; set to `null` to skip a dimension
6. In `label.formatter`, reference dimension values as `'{@score}'` (by name) or `'{@[4]}'` (by index)

## Common Mistakes

- Misspelling dimension names (e.g., `'Life Expectancy'` vs `'Life Expectency'`)
- Forgetting that `seriesLayoutBy: 'row'` does NOT work with columnar format
- Using `dataset` with treemap/graph/lines charts
