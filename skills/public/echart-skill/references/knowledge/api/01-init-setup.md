# API: Init, Connect, Dispose (Static Methods)

> **Source:** `echarts-api-docs/echarts/`

## echarts.init(dom, theme?, opts?)

Creates an ECharts instance.

```javascript
const chart = echarts.init(document.getElementById('main'), null, {
  // All optional:
  devicePixelRatio: 2,       // Default: window.devicePixelRatio
  renderer: 'canvas',        // 'canvas' (default) or 'svg'
  useDirtyRect: false,       // Dirty rectangle rendering (Canvas only)
  useCoarsePointer: null,    // null=auto(mobile on), true, false — expand hit area
  pointerSize: 44,           // Hit area px size for coarse pointer
  ssr: false,                // Server-side rendering mode (SVG only)
  width: 600,                // Explicit width (auto-detect if omitted)
  height: 400,               // Explicit height (auto-detect if omitted)
  locale: 'ZH'               // 'ZH' (Chinese) or 'EN' (English)
});
```

**Key notes:**
- Container DOM must have dimensions (CSS or explicit `width`/`height` in opts)
- Cannot init multiple instances on the same DOM element
- For SSR: enable `ssr: true`, set explicit `width`/`height`, then call `renderToSVGString()`
- For hidden containers: set explicit dimensions or call `resize()` after showing

### Theme usage
```javascript
// Built-in theme
echarts.init(dom, 'dark');

// Registered theme (v6+)
echarts.registerTheme('myTheme', themeObj);
echarts.init(dom, 'myTheme');

// Inline theme object
echarts.init(dom, { backgroundColor: '#f4f4f4' });
```

---

## echarts.connect(group)

Links chart instances for synchronized tooltip, zoom, selection.

```javascript
chart1.group = 'group1';
chart2.group = 'group1';
echarts.connect('group1');

// Or directly:
echarts.connect([chart1, chart2]);
```

---

## echarts.disconnect(group)

Removes chart group linkage.

```javascript
echarts.disconnect('group1');

// Remove single chart from group:
chart1.group = '';
```

---

## echarts.dispose(target)

Destroys instance, freeing all resources. After disposal, instance is dead.

```javascript
echarts.dispose(chart);                           // By instance
echarts.dispose(document.getElementById('main'));  // By DOM element
```

**CRITICAL:** Always dispose when the container DOM is being removed — prevents memory leaks.

---

## echarts.getInstanceByDom(dom)

Retrieves the chart instance attached to a DOM element.

```javascript
const chart = echarts.getInstanceByDom(document.getElementById('main'));
```

---

## echarts.setPlatformAPI(api) — v5.3+

For non-browser environments (Node.js SSR):

```javascript
echarts.setPlatformAPI({
  createCanvas() { /* return canvas */ },
  measureText(text, font) { return { width: number }; },
  loadImage(src, onload, onerror) { /* return image */ }
});
```

All methods are optional — implement only what the platform needs.
