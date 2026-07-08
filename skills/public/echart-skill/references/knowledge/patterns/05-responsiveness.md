# Pattern: Responsiveness & Container Sizing

> **Source:** `echarts-docs/handbook/zh/concepts/chart-size.md`

## Window Resize

```javascript
window.addEventListener('resize', function() {
  chart.resize();
});
```

For performance, debounce the resize:

```javascript
var resizeTimer;
window.addEventListener('resize', function() {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => chart.resize(), 100);
});
```

## Container Resize (ResizeObserver)

When the container changes size without a window resize event (CSS changes, flex layouts, sidebar toggle, etc.):

```javascript
if (window.ResizeObserver) {
  new ResizeObserver(() => {
    chart.resize();
  }).observe(document.getElementById('main'));
}
```

## Hidden Container / Tab Switching

**Problem:** Charts in hidden tabs/containers can't detect their dimensions.

**Solutions:**

### Solution 1: Set explicit dimensions on init
```javascript
echarts.init(dom, null, { width: 600, height: 400 });
```

### Solution 2: Call resize() on visibility change
```javascript
// Tab switch handler
function onTabActivated() {
  chart.resize();
}

// or with visibility API
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) {
    chart.resize();
  }
});
```

## Memory Management — CRITICAL

### Single Page App (SPA) / Tab Switching
```javascript
// When removing a chart:
chart.dispose();  // MUST call this before removing the DOM element

// NEVER do this:
container.innerHTML = '';  // LEAKS memory — chart instance not destroyed!
```

### Re-creating after dispose
```javascript
// Tab switch away:
chart.dispose();

// Tab switch back — create NEW instance:
chart = echarts.init(document.getElementById('main'));
chart.setOption(option);
```

**Do NOT reuse a disposed instance — it will not work.**

## resize() Options

```javascript
chart.resize({
  width: 800,        // Explicit width (null = auto from container)
  height: 400,       // Explicit height (null = auto from container)
  silent: false,     // true = suppress events
  animation: {
    duration: 300,   // Resize animation duration (default: 0 = no animation)
    easing: 'linear'
  }
});
```

## Multiple Charts on One Page

When resizing affects all charts:

```javascript
var charts = [chart1, chart2, chart3];
window.addEventListener('resize', function() {
  charts.forEach(c => c.resize());
});
```

## Common Pitfalls

1. **Forgetting to call `dispose()`** — memory leak
2. **Reusing disposed instance** — create a new one
3. **Charts in hidden containers** — set explicit dimensions or call `resize()`
4. **Not debouncing resize** — performance hit on rapid resize
