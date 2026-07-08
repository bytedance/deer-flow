# Pattern: Accessibility (ARIA & Decal)

> **Source:** `echarts-docs/handbook/zh/best-practices/aria.md`

## Enable Accessibility

```javascript
import { AriaComponent } from 'echarts/components';
echarts.use(AriaComponent);

option = {
  aria: {
    show: true
  },
  // ... rest of chart config
};
```

**CRITICAL:** `AriaComponent` must be explicitly imported (since ECharts 5). Setting `aria.show: true` without importing has NO effect.

## Auto-Generated Description

When enabled, ECharts auto-generates `aria-label` descriptions. Example for a pie chart titled "User Sources":

> "This is a chart about 'User Sources'. The chart type is a pie chart showing access sources. The data is — Direct Access: 335, Email Marketing: 310, ..."

## Custom Description

```javascript
aria: {
  show: true,
  description: 'This chart shows monthly sales data for 2023 with a clear upward trend in Q4.'
}
```

## Custom Template Variables

```javascript
aria: {
  show: true,
  general: {
    withTitle: 'The chart title is: {title}.',
    withoutTitle: 'This is a chart.'
  },
  series: {
    maxCount: 10,            // Max series to describe (default: 10)
    single: '{name}: {value}',
    multiple: {
      prefix: 'It consists of {seriesCount} series.',
      withName: 'The {name} series has data: {data}.',
      withoutName: 'Data: {data}.'
    }
  },
  data: {
    maxCount: 10,            // Max data items per series
    allData: 'Data is: {data}.',
    separator: ', '
  }
}
```

## Decal Patterns (Texture)

Helps color-blind users distinguish data series and enables monochrome printing:

```javascript
aria: {
  show: true,
  decal: {
    show: true    // Uses default decal patterns
  }
}

// Custom decals
aria: {
  decal: {
    show: true,
    decals: [
      { color: '#5470c6', dashArrayX: [0, 0], dashArrayY: [0, 0] },  // Solid
      { color: '#91cc75', dashArrayX: [5, 5], dashArrayY: [5, 5] },    // Dots
      { color: '#fac858', dashArrayX: [2, 2], rotation: Math.PI / 4 }  // Diagonal stripes
    ]
  }
}
```

## Best Practices

1. **Always enable `aria.show: true`** for production charts
2. **Import `AriaComponent`** explicitly when using tree-shaking
3. **Provide custom `aria.description`** for complex charts (scatter plots, large datasets) where auto-generated per-point descriptions aren't useful
4. **Use decals alongside colors** for accessibility and monochrome printing
5. **High-contrast theme**: ECharts provides a built-in high-contrast theme option
