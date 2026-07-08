# Style 样式系统

> **Source:** `echarts-docs/handbook/zh/concepts/style.md`

## Four Ways to Set Styles

1. **Color Theme** — `echarts.init(dom, 'dark')`
2. **Color Palette** — `option.color: [...]`
3. **Direct Style** — `itemStyle`, `lineStyle`, `areaStyle`, `label`
4. **Visual Mapping** — `visualMap` component

## Color Theme

```javascript
// Built-in themes: 'default', 'dark'
echarts.init(dom, 'dark');

// Custom theme: download from theme editor, then register
echarts.registerTheme('myTheme', themeObject);
echarts.init(dom, 'myTheme');
```

## Color Palette

```javascript
// Global (applies to all series)
option = {
  color: ['#c23531', '#2f4554', '#61a0a8', '#d48265', '#91c7ae']
};

// Per-series
series: [{
  type: 'bar',
  color: ['#ff0000', '#00ff00', '#0000ff']
}]
```

## Direct Style Configuration

### Hierarchy
```
itemStyle       — Graph shapes (bars, points, sectors)
├── color, borderColor, borderWidth
├── barBorderRadius (bar charts)
├── shadowBlur, shadowColor, shadowOffsetX, shadowOffsetY
└── opacity

lineStyle       — Lines (line charts, connections)
├── color, width, type ('solid'|'dashed'|'dotted')
├── cap, join
└── shadow*

areaStyle       — Area fills
├── color, opacity
└── shadow*

label           — Data labels
├── show, position, distance
├── color, fontSize, fontWeight
├── formatter, rotate
└── rich (rich text)
```

### Gradients
```javascript
// Linear gradient
itemStyle: {
  color: {
    type: 'linear',
    x: 0, y: 0, x2: 0, y2: 1,
    colorStops: [
      { offset: 0, color: 'red' },
      { offset: 1, color: 'blue' }
    ]
  }
}

// Radial gradient
itemStyle: {
  color: {
    type: 'radial',
    x: 0.5, y: 0.5, r: 0.5,
    colorStops: [
      { offset: 0, color: '#fff' },
      { offset: 1, color: '#000' }
    ]
  }
}

// Background gradient
backgroundColor: {
  type: 'radial',
  x: 0.5, y: 0.5, r: 0.5,
  colorStops: [...]
}
```

### Shadows
```javascript
itemStyle: {
  shadowBlur: 10,
  shadowColor: 'rgba(0, 0, 0, 0.5)',
  shadowOffsetX: 2,
  shadowOffsetY: 2
}
```

## Three-State Interaction Model (ECharts 5+)

| State | Trigger | Config |
|-------|---------|--------|
| `emphasis` | Mouse hover | `emphasis: { itemStyle: {...} }` |
| `blur` | Other elements when one is hovered | `blur: { itemStyle: {...} }` |
| `select` | Click (when `selectedMode` is set) | `select: { itemStyle: {...} }` |

```javascript
series: {
  itemStyle: { color: '#5470c6' },       // Normal state
  emphasis: { itemStyle: { color: '#91cc75' } },  // Hover state
  blur: { itemStyle: { opacity: 0.3 } },          // Dimmed state
  select: { itemStyle: { borderWidth: 3 } }       // Selected state
}
```

## Important Notes

1. **Flat style is preferred** (ECharts 4+). Old `normal: { itemStyle: {...} }` pattern is still supported but deprecated
2. Hover (`emphasis`) styles are auto-generated from normal styles if not specified
3. `visualMap` also controls styles — see visual-map concept
4. Rich text labels need the `rich` property — see patterns/03-rich-text.md
