# Legend 图例配置

> **Source:** `echarts-docs/handbook/zh/concepts/legend.md`

## Layout

```javascript
legend: {
  orient: 'vertical',   // or 'horizontal' (default)
  right: 10,
  top: 'center'
}

// Alternative: bottom placement
legend: {
  orient: 'horizontal',
  bottom: 10,
  left: 'center'
}
```

## Scrollable Legend

When there are many legend items:

```javascript
legend: {
  type: 'scroll',       // Enables scroll with page buttons
  orient: 'vertical',
  right: 10,
  top: 20,
  bottom: 20,
  width: 120            // Fixed width
}
```

## Styling

```javascript
legend: {
  backgroundColor: 'rgba(255, 255, 255, 0.7)',  // Semi-transparent bg on dark charts
  textStyle: {
    color: '#333',
    fontSize: 12
  },
  icon: 'rect'   // Legend marker shape: 'circle', 'rect', 'roundRect', 'triangle', 'diamond', 'pin', 'arrow', 'none'
}
```

## Initial Selection State

```javascript
legend: {
  data: ['Series A', 'Series B', 'Series C'],
  selected: {
    'Series A': true,    // Visible initially
    'Series B': false,   // Hidden initially
    'Series C': true
  }
}
```

Clicking a legend item toggles its series visibility.

## Per-Item Icon

```javascript
legend: {
  data: [
    { name: 'Series A', icon: 'rect' },
    { name: 'Series B', icon: 'circle' },
    { name: 'Series C', icon: 'roundRect' }
  ]
}
```

## Best Practices

1. **Placement:** Right-top or bottom-center; keep consistent across pages
2. **Vertical space constrained:** Place below the chart (bottom)
3. **Dual-axis chart with multiple chart types:** Use different legend icon shapes for different series types
4. **Single data series:** Use the title for description instead of adding a legend — skip legend entirely
