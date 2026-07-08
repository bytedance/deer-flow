# Data Transform 数据转换

> **Source:** `echarts-docs/handbook/zh/concepts/data-transform.md`

## Purpose

ECharts 5+ declarative data transforms. Formula: `outData = f(inputData)`.
Define transforms in `dataset`, reference with `fromDatasetIndex`/`fromDatasetId`.

## Basic Usage

```javascript
dataset: [
  { source: [...] },  // index 0: raw data
  {                     // index 1: filtered result
    transform: {
      type: 'filter',
      config: { dimension: 'Year', value: 2011 }
    }
  }
],
series: [{ datasetIndex: 1 }]
```

## Chaining Transforms

```javascript
dataset: [{
  source: [...],
  transform: [
    { type: 'filter', config: { dimension: 'Product', value: 'Tofu' } },
    { type: 'sort', config: { dimension: 'Year', order: 'desc' } }
  ]
}]
```

## Built-in Transforms

### 1. `filter` — Data Filtering

```javascript
// Simple equality
config: { dimension: 'Year', value: 2011 }

// Comparison operators
config: { dimension: 'Price', '>=': 20, '<': 30 }  // AND logic

// Logical operators (AND/OR/NOT)
config: {
  dimension: '',
  reg: /^some/i,
  and: [{ dimension: 'X', gt: 10 }, { dimension: 'Y', lt: 50 }],
  or: [{ dimension: 'A', eq: 1 }, { dimension: 'B', ne: 2 }]
}
```

**Operators:** `>` (gt), `>=` (gte), `<` (lt), `<=` (lte), `=` (eq), `!=` (ne/<>), `reg` (regex)

**Parsers:**
- `parser: 'time'` — Time comparison
- `parser: 'trim'` — Trim whitespace
- `parser: 'number'` — Force numeric parse (handles `'33%'`, `'12px'`)

### 2. `sort` — Data Sorting

```javascript
config: {
  dimension: 'score',
  order: 'asc'  // or 'desc'
}

// Multi-dimension sort
config: [
  { dimension: 'year', order: 'desc' },
  { dimension: 'score', order: 'asc' }
]

// Handle incomparable values (null, undefined, NaN)
incomparable: 'min'  // or 'max'
```

## External Transforms (ecStat)

Register custom transforms via `echarts.registerTransform()`:

```javascript
// Install ecStat first, then:
dataset: {
  transform: {
    type: 'ecStat:regression',
    config: { method: 'linear' }
  }
}
```

Common ecStat transforms: regression, clustering, histogram, aggregation

## Debugging

```javascript
transform: {
  type: 'filter',
  config: { ... },
  print: true  // Output result to console.log
}
```

## Important Notes

1. Must import `DatasetComponent` and `TransformComponent` in on-demand mode
2. Chained transforms: each transform only gets the first output of the previous one; only passes its first output to the next
3. Multi-output transforms (e.g., boxplot): use `fromTransformResult` to access specific outputs
4. `fromTransformResult` and `transform` can coexist in one dataset
