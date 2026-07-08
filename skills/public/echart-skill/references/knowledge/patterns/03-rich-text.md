# Pattern: Rich Text Labels

> **Source:** `echarts-docs/handbook/zh/how-to/label/rich-text.md`

## Basic Rich Text

```javascript
label: {
  formatter: [
    '{title|Chart Title}',
    '{value|1234}',
    '{unit|万元}'
  ].join('\n'),
  rich: {
    title: {
      color: '#333',
      fontSize: 18,
      fontWeight: 'bold',
      align: 'center',
      padding: [5, 10]
    },
    value: {
      color: '#c23531',
      fontSize: 24,
      fontWeight: 'bold',
      lineHeight: 40
    },
    unit: {
      color: '#999',
      fontSize: 12
    }
  }
}
```

## Text Fragment Properties

Each `rich` style block (e.g., `{styleName|text}`) supports:

```javascript
rich: {
  styleName: {
    // Font
    fontStyle: 'normal',       // 'normal' | 'italic' | 'oblique'
    fontWeight: 'bold',        // 'normal' | 'bold' | 'bolder' | 'lighter' | number
    fontFamily: 'sans-serif',
    fontSize: 14,

    // Color
    color: '#333',
    textBorderColor: '#fff',
    textBorderWidth: 1,
    textShadowColor: 'rgba(0,0,0,0.3)',
    textShadowBlur: 2,
    textShadowOffsetX: 1,
    textShadowOffsetY: 1,

    // Layout (only available in rich — NOT on plain labels)
    width: 100,               // Fragment width
    height: 30,               // Fragment height
    padding: [5, 10, 5, 10],   // [top, right, bottom, left]
    align: 'center',           // Horizontal: 'left', 'center', 'right'
    verticalAlign: 'middle',   // Vertical in line: 'top', 'middle', 'bottom'
    lineHeight: 20,

    // Box styling
    backgroundColor: '#f0f0f0',
    borderColor: '#ccc',
    borderWidth: 1,
    borderRadius: 5,

    // Or image background
    backgroundColor: { image: 'url_to_icon.png' }
  }
}
```

## Label Positioning

```javascript
label: {
  position: 'top',     // 'left', 'right', 'top', 'bottom', 'inside',
                       // 'insideLeft', 'insideRight', 'insideTop', 'insideBottom',
                       // 'insideTopLeft', 'insideBottomLeft', etc.
  distance: 5,         // Distance from graphic element
  rotate: 45           // Rotation in degrees
}
```

## Visual Separator Lines

Use a fragment with `width: '100%'` and `height: 0` + border:

```javascript
rich: {
  divider: {
    width: '100%',
    height: 0,
    borderColor: '#ccc',
    borderWidth: 0.5
  }
}
// In formatter:
formatter: '{title|Title}\n{divider|}\n{value|100}'
```

## Important Notes

1. Only `'\n'` causes line breaks in rich text
2. Rich text fragments behave like CSS `inline-block`
3. `verticalAlign` controls position **within the current line** (not within the bounding box)
4. `align` controls **horizontal** position among fragments
5. Chinese text + English numbers may need explicit `width`/`height` to align properly
6. `width` and `height` only work when `rich` is defined (not on plain labels)
7. Label rotation: `align`/`verticalAlign` is applied first, then the label is rotated
