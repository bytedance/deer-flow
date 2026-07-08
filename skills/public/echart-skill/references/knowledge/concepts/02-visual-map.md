# Visual Map 视觉映射组件

> **Source:** `echarts-docs/handbook/zh/concepts/visual-map.md`

## Purpose

`visualMap` maps data dimensions to visual elements (color, size, opacity, etc.).

## Two Types

| Type | When to Use |
|------|-------------|
| `'continuous'` | Data values are continuous numbers |
| `'piecewise'` | Data is divided into discrete segments or categories |

## Continuous Visual Map

```javascript
visualMap: {
  type: 'continuous',
  min: 0,
  max: 5000,
  dimension: 3,       // Use the 4th data dimension
  seriesIndex: 4,      // Apply to the 5th series
  inRange: {
    color: ['blue', '#121122', 'red'],  // Color gradient
    symbolSize: [30, 100]               // Size range
  },
  outOfRange: {
    symbolSize: [30, 100]  // Style for data outside range
  }
}
```

## Piecewise Visual Map

### Mode 1: Auto-split (`splitNumber`)
```javascript
visualMap: {
  type: 'piecewise',
  min: 0,
  max: 5000,
  splitNumber: 5   // Auto-divide into 5 equal segments
}
```

### Mode 2: Custom pieces (`pieces`)
```javascript
visualMap: {
  type: 'piecewise',
  pieces: [
    { min: 1500 },                           // >= 1500
    { min: 900, max: 1500, label: '900-1500' },
    { min: 310, max: 1000 },
    { lt: 310, label: '< 310' }              // < 310
  ]
}
```

### Mode 3: Categories (`categories`)
```javascript
visualMap: {
  type: 'piecewise',
  categories: ['Category A', 'Category B', 'Category C'],
  inRange: { color: ['#ff0000', '#00ff00', '#0000ff'] }
}
```

## Mappable Visual Properties

- `symbol` — Shape type
- `symbolSize` — Shape size
- `color` — Fill color
- `opacity`, `colorAlpha` — Transparency
- `colorLightness` — Lightness (HSL)
- `colorSaturation` — Saturation (HSL)
- `colorHue` — Hue (HSL)

## Important Notes

1. `inRange` specifies style when data IS in the mapping range
2. `outOfRange` specifies style when data is OUTSIDE the range
3. You can define multiple visualMap components in one option
4. Most common use case: scatter plots using radius for a 3rd dimension
5. `visualMap` also works with `series.encode` for dataset-based charts
