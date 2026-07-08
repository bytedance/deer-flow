# API: Coordinate Conversion & Graphic Utils

> **Source:** `echarts-api-docs/echartsInstance/convertToPixel.md`, `echartsInstance/convertFromPixel.md`, `echarts/graphic.md`

## convertToPixel(finder, coord)

Converts data/logical coordinates to pixel coordinates (relative to chart DOM's top-left).

```javascript
// Cartesian (grid)
chart.convertToPixel({ xAxisIndex: 0 }, [200, 300]);         // [xValue, yValue]
chart.convertToPixel({ gridId: 'g1' }, [200, 300]);

// Category axes: use string names
chart.convertToPixel({ xAxisId: 'x0' }, ['Category A', 300]);

// Time axes: use timestamps
chart.convertToPixel({ xAxisIndex: 0 }, [1609459200000, 300]);

// Single axis (returns single number)
chart.convertToPixel({ xAxisId: 'x0' }, 3000);

// Geo
chart.convertToPixel({ geoIndex: 0 }, [128.3324, 89.5344]);  // [lng, lat]
chart.convertToPixel({ geoId: 'bb' }, 'Bern');               // Region name → center point

// Calendar
chart.convertToPixel({ calendarIndex: 0 }, '2021-01-01');

// Matrix (v6)
chart.convertToPixel({ matrixIndex: 0 }, [0, 1]);
```

### finder Object Properties
`xAxisIndex`/`xAxisId`/`xAxisName`, `yAxisIndex`/`yAxisId`/`yAxisName`,
`gridIndex`/`gridId`/`gridName`, `polarIndex`/`polarId`/`polarName`,
`geoIndex`/`geoId`/`geoName`, `singleAxisIndex`/`singleAxisId`/`singleAxisName`,
`calendarIndex`/`calendarId`/`calendarName`, `matrixIndex`/`matrixId`/`matrixName`,
`seriesIndex`/`seriesId`/`seriesName`

---

## convertFromPixel(finder, value)

Inverse of `convertToPixel` — pixel coordinates → data/logical coordinates.

```javascript
chart.convertFromPixel({ gridIndex: 0 }, [100, 200]);
// Returns [xDataValue, yDataValue]
```

---

## containPixel(finder, value)

Check if a pixel point is within a coordinate system.

```javascript
chart.containPixel({ geoIndex: 0 }, [23, 44]);              // true/false
chart.containPixel({ seriesIndex: [1, 4, 5] }, [23, 44]);  // Check multiple series
```

Supported: grid, polar, geo, matrix, series-map, series-graph, series-pie.

---

## convertToLayout(finder, coord) — v6.0

Convert calendar or matrix coordinates to layout rectangles (positions + sizes).

```javascript
// Calendar
var layout = chart.convertToLayout({ calendarIndex: 0 }, '2021-01-01');
// Returns: { rect: {x, y, width, height}, contentRect: {x, y, width, height} }

// Matrix
var layout = chart.convertToLayout({ matrixIndex: 0 }, [0, 1]);
// Returns: { rect: {...}, matrixXYLocatorRange: [[minX, maxX], [minY, maxY]] }
```

---

## Graphic Utilities

### graphic.extendShape(opts)
Create a custom shape class (extends zrender.graphic.Path):
```javascript
var MyShape = echarts.graphic.extendShape({
  shape: { x: 0, y: 0, width: 0, height: 0 },
  buildPath: function(ctx, shape) {
    ctx.moveTo(shape.x, shape.y);
    ctx.lineTo(shape.x + shape.width, shape.y + shape.height);
    // ...
  }
});
```

### graphic.registerShape(name, ShapeClass)
Register for use in custom series and graphic components:
```javascript
echarts.graphic.registerShape('myShape', MyShape);
// Use in custom series: renderItem returns { type: 'myShape', ... }
```

### graphic.getShapeClass(name)
```javascript
var Circle = echarts.graphic.getShapeClass('circle');
```
Built-in shapes: `'circle'`, `'sector'`, `'ring'`, `'polygon'`, `'polyline'`, `'rect'`, `'line'`, `'bezierCurve'`, `'arc'`

### graphic.clipPointsByRect(points, rect)
Clip an array of `[x, y]` points by a rectangular boundary:
```javascript
var clipped = echarts.graphic.clipPointsByRect(
  [[0, 0], [100, 100]],
  { x: 10, y: 10, width: 50, height: 50 }
);
```

### graphic.clipRectByRect(targetRect, rect)
Compute rectangle intersection:
```javascript
var intersection = echarts.graphic.clipRectByRect(
  { x: 0, y: 0, width: 100, height: 100 },
  { x: 50, y: 50, width: 100, height: 100 }
);
// → { x: 50, y: 50, width: 50, height: 50 }
// Returns undefined if no overlap
```
