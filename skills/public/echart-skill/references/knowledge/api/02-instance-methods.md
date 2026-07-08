# API: Instance Methods

> **Source:** `echarts-api-docs/echartsInstance/`

## setOption(option, opts?)

The universal interface for setting/updating chart configuration and data.

```javascript
// Basic
chart.setOption(option);

// With merge control
chart.setOption(option, { notMerge: true });  // Full replacement

// Object opts form (recommended)
chart.setOption(option, {
  notMerge: false,        // true = replace all; false = merge (default)
  replaceMerge: ['xAxis', 'series'],  // Replace-merge specific component types
  lazyUpdate: false,      // true = defer to next animation frame
  silent: false           // true = suppress events
});
```

### Merge Modes Explained

| Mode | Trigger | Behavior |
|------|---------|----------|
| **Full Replace** | `notMerge: true` | Delete all old components, create new |
| **Normal Merge** | Default | Match by id/name, never delete, only add/update |
| **Replace Merge** | `replaceMerge: ['xAxis', ...]` | Match by id first, then by index. Unmatched old components of the specified types are deleted |

### Deleting Components
- Delete ALL: `notMerge: true`
- Delete SOME: `replaceMerge: ['xAxis']` — unmatched old x-axes are deleted

### Common Pitfall
```javascript
// BAD: getOption returns merged-with-defaults values, then mutating and resubmitting them can break things
var opt = chart.getOption();
opt.visualMap[0].inRange.color = 'red';
chart.setOption(opt);  // May cause unexpected behavior!

// GOOD: set only what changed
chart.setOption({
  visualMap: { inRange: { color: 'red' } }
});
```

---

## getOption()

Returns current option (merged with defaults). All component properties are returned as **arrays** (even if set as objects).

```javascript
var opt = chart.getOption();
// opt.title  =>  [{...}]   (always array)
// opt.series =>  [{...}, {...}]
```

---

## resize(opts?)

Must be called when container size changes.

```javascript
// Basic
chart.resize();

// Explicit dimensions
chart.resize({ width: 800, height: 400 });

// With options
chart.resize({
  width: 800,
  height: 400,
  silent: false,
  animation: { duration: 300, easing: 'linear' }
});
```

**Hidden container fix:** Call `resize()` after the container becomes visible (tab switch, accordion expand, etc.).

---

## getWidth() / getHeight() / getDom()

```javascript
chart.getWidth();   // number — pixel width
chart.getHeight();  // number — pixel height
chart.getDom();     // HTMLDivElement | HTMLCanvasElement
```

---

## showLoading(type?, opts?) / hideLoading()

```javascript
chart.showLoading('default', {
  text: 'Loading...',
  color: '#c23531',
  maskColor: 'rgba(255, 255, 255, 0.8)',
  textColor: '#000',
  fontSize: 12,
  showSpinner: true,
  spinnerRadius: 10,
  lineWidth: 5,
  fontWeight: 'normal',
  fontStyle: 'normal',
  fontFamily: 'sans-serif'
});
// ... load data ...
chart.hideLoading();
```

---

## getDataURL(opts)

Export chart as base64 image:

```javascript
var img = new Image();
img.src = chart.getDataURL({
  type: 'png',              // 'png', 'jpg' (canvas only), 'svg' (SVG renderer only)
  pixelRatio: 2,
  backgroundColor: '#fff',
  excludeComponents: ['toolbox']
});
```

---

## getConnectedDataURL(opts)

Same as `getDataURL` but for connected chart groups — combines all linked charts into one image.

---

## appendData(opts)

Incremental rendering for millions of data points:

```javascript
chart.appendData({
  seriesIndex: 0,
  data: new Float64Array([1, 2, 3, ...])
});
```

**Limitations:**
- Only for: scatter, lines (base ECharts); scatterGL, linesGL, polygons3D (ECharts GL)
- Does NOT work with `dataset` — only with `series.data`
- Not for all chart types

---

## setTheme(theme, opts?) — v6.0

Dynamic theme switching after initialization:

```javascript
echarts.registerTheme('myTheme', themeObj);
chart.setTheme('myTheme');

// Anonymous theme
chart.setTheme({ backgroundColor: '#f4f4f4' });

// Silent (no events)
chart.setTheme('dark', { silent: true });
```

**CRITICAL CAVEAT:** `setTheme` does NOT work correctly with normal merge-mode `setOption`. All previously merged options are discarded — only the LAST `setOption` call's option survives.

```javascript
// BAD — options 1 and 2 are lost after setTheme:
chart.setOption(opt1);
chart.setOption(opt2);      // merge mode
chart.setTheme('dark');     // opt1 is gone!

// GOOD — use notMerge with full options:
chart.setOption(fullOption, { notMerge: true });
chart.setTheme('dark');     // fullOption survives intact
```

---

## Lifecycle Methods

```javascript
chart.clear();           // Remove all components, instance remains usable
chart.dispose();         // Destroy instance permanently (for memory cleanup)
chart.isDisposed();      // boolean — check if disposed
chart.group;             // property — group ID for connect()
```

---

## renderToSVGString(opts?) — v5.3

SVG renderer only. Returns SVG string.

```javascript
var svg = chart.renderToSVGString({ useViewBox: true });
```

Required for SSR mode.
