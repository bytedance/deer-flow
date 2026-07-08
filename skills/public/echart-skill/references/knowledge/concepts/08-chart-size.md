# Chart Container & Sizing 图表容器及大小

> **Source:** `echarts-docs/handbook/zh/concepts/chart-size.md`

## Initialization Methods

### Method 1 (Recommended): CSS-defined Container
```html
<div id="main" style="width: 600px; height: 400px;"></div>
<script>
  var chart = echarts.init(document.getElementById('main'));
</script>
```

### Method 2: Init-Time Dimensions
```javascript
var chart = echarts.init(document.getElementById('main'), null, {
  width: 600,
  height: 400
});
```
Use this when the container has no dimensions yet at init time.

## Responsive Resizing

```javascript
// Listen to window resize
window.addEventListener('resize', function() {
  chart.resize();
});

// Specific dimensions (different from container)
chart.resize({ width: 800, height: 400 });

// Silently (no events)
chart.resize({ width: 800, height: 400, silent: true });

// With animation
chart.resize({
  width: 800,
  height: 400,
  animation: { duration: 300, easing: 'linear' }
});
```

## Hidden Container Problem

If a chart is initialized in a hidden tab/container, it can't determine dimensions. Solutions:

1. Set explicit `width`/`height` in init options
2. Call `resize()` when the container becomes visible
3. Use `ResizeObserver` for dynamic containers:
```javascript
const observer = new ResizeObserver(() => chart.resize());
observer.observe(containerEl);
```

## Memory Management

**CRITICAL:** Always dispose instances when the container is destroyed:

```javascript
// Before destroying the container DOM element
chart.dispose();

// Also available as static method
echarts.dispose(document.getElementById('main'));
```

For tab switching: dispose old instance → create new one. Do NOT reuse disposed instances.

## Full Init Options

```javascript
echarts.init(dom, theme, {
  devicePixelRatio: 2,       // Default: window.devicePixelRatio
  renderer: 'canvas',        // 'canvas' or 'svg'
  useDirtyRect: false,       // Dirty rectangle rendering (canvas only)
  useCoarsePointer: null,    // null=auto(mobile on), true=on, false=off
  pointerSize: 44,           // Hit area size for coarse pointer
  ssr: false,                // Server-side rendering mode
  width: 600,                // Explicit width
  height: 400,               // Explicit height
  locale: 'ZH'               // 'ZH' or 'EN' (requires import)
});
```
