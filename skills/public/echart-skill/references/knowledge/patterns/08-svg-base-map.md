# Pattern: SVG Base Map

> **Source:** `echarts-docs/handbook/zh/how-to/component-types/geo/svg-base-map.md`

Available since ECharts v5.1.0. Use SVG as base maps for `geo` and `map` series (alternative to GeoJSON).

## Registration

```javascript
const svgString = '<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" ...>';
echarts.registerMap('customMap', { svg: svgString });
```

## Usage

```javascript
// In geo component
option = {
  geo: {
    map: 'customMap',
    roam: true     // Enable zoom/pan
  }
};

// Or as map series
option = {
  series: [{
    type: 'map',
    map: 'customMap',
    roam: true
  }]
};
```

## Interactive Elements

SVG elements with a `name` attribute become interactive regions:

```xml
<svg>
  <path name="region1" d="M 0,0 L 100,0 L 100,100 L 0,100 Z" fill="#ccc"/>
  <path name="region2" d="M 100,0 L 200,0 L 200,100 L 100,100 Z" fill="#ddd"/>
</svg>
```

These named elements support: `select`, `emphasis`, `focus-blur`, `label`, `tooltip`.

## Which SVG Elements Can Be Named
`rect`, `circle`, `line`, `ellipse`, `polygon`, `polyline`, `path`, `text`, `tspan`, `g`

## Which SVG Elements Support itemStyle
`rect`, `circle`, `line`, `ellipse`, `polygon`, `polyline`, `path` (not `text`, `tspan`, `g`)

## Selection

```javascript
geo: {
  map: 'customMap',
  selectedMode: 'single'   // 'single' | 'multiple'
}

// Listen for selection
chart.on('geoselectchanged', function(params) {
  console.log('Selected regions:', params.allSelected);
});
```

## Tooltip

```javascript
geo: {
  map: 'customMap',
  tooltip: {
    show: true,
    formatter: function(params) {
      return 'Region: ' + params.name;
    }
    // Can be per-region:
    // [{ name: 'region1', tooltip: { formatter: ... } }]
  }
}
```

## Click Events

```javascript
chart.on('click', { geoIndex: 0, name: 'region1' }, function(params) {
  // Clicked on 'region1'
});

// Get SVG coordinates from click
chart.on('click', function(params) {
  var svgCoords = chart.convertFromPixel(
    { geoIndex: 0 },
    [params.event.offsetX, params.event.offsetY]
  );
});
```

## Overlaying Series on SVG Map

```javascript
series: [{
  type: 'scatter',
  coordinateSystem: 'geo',
  geoIndex: 0,
  data: [[100, 200], [300, 400]]  // Coordinates in SVG units
}]
```

## Layout Control

```javascript
geo: {
  map: 'customMap',
  layoutCenter: ['50%', '50%'],   // Center position
  layoutSize: '80%'               // Size
}
// OR use: top/right/bottom/left
```

## Bounding Rect Resolution Order
1. `geo.boundingCoords` (explicit)
2. `<svg width="" height="">`
3. `<svg viewBox="">`
4. Union of all element bounding rects

## Unsupported SVG Features

- ❌ `transform: skew(...)` and matrices containing skew
- ❌ `rotate` + different `scale` (positive vs negative)
- ❌ `<style>` tags (inline styles work)
- ❌ Non-`px` units (`mm`, percentages in `<svg width="30%">`)
- ❌ `<defs>` only supports `<linearGradient>`, `<radialGradient>`
- ❌ Gradient `fx`, `fy`, `gradientTransform`
- ❌ `fill:url(..)` only supports `url(#someId)` — no external URLs or data URIs
- ❌ `<switch>` tag
- ❌ `<text>` `textPath` and Addressable characters
