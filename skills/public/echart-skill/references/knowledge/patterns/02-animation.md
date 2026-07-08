# Pattern: Animation Configuration

> **Source:** `echarts-docs/handbook/zh/how-to/animation/transition.md`

## Animation Types

### Entry Animation (new data)
```javascript
series: {
  animation: true,                       // Enable/disable
  animationDuration: 1000,               // Duration in ms
  animationEasing: 'cubicOut',           // Easing function name
  animationDelay: function(idx) {
    return idx * 10;                     // Staggered delay
  }
}
```

### Update Animation (data changes)
```javascript
series: {
  animationDurationUpdate: 500,
  animationEasingUpdate: 'cubicInOut',
  animationDelayUpdate: function(idx) {
    return idx * 10;
  }
}
```

## Easing Functions

Built-in easing names (use as strings):
`'linear'`, `'quadraticIn'`, `'quadraticOut'`, `'quadraticInOut'`,
`'cubicIn'`, `'cubicOut'`, `'cubicInOut'`,
`'quarticIn'`, `'quarticOut'`, `'quarticInOut'`,
`'quinticIn'`, `'quinticOut'`, `'quinticInOut'`,
`'sinusoidalIn'`, `'sinusoidalOut'`, `'sinusoidalInOut'`,
`'exponentialIn'`, `'exponentialOut'`, `'exponentialInOut'`,
`'circularIn'`, `'circularOut'`, `'circularInOut'`,
`'elasticIn'`, `'elasticOut'`, `'elasticInOut'`,
`'backIn'`, `'backOut'`, `'backInOut'`,
`'bounceIn'`, `'bounceOut'`, `'bounceInOut'`

## Performance: animationThreshold

```javascript
series: {
  animationThreshold: 2000   // Default: 2000. Disable animation when data count exceeds this
}
```
When a chart has more than `animationThreshold` elements, animations are **automatically disabled** for performance.

## Disabling Animation
```javascript
series: { animation: false }
// or globally:
option = { animation: false, ... }
```

## Capturing Post-Animation State

```javascript
// Method 1: setTimeout matching animationDuration
chart.setOption(option);
setTimeout(() => {
  var img = chart.getDataURL({ type: 'png' });  // Captures final state
}, animationDuration);

// Method 2: Listen for 'rendered' event (clean up after)
chart.on('rendered', function onRendered() {
  var img = chart.getDataURL({ type: 'png' });
  chart.off('rendered', onRendered);  // Remove listener
});
```

## Bar Race Animation Pattern

See [chart-types/01-bar.md](../chart-types/01-bar.md) for the complete bar race configuration.

## Important Notes

1. Update detection: ECharts compares old/new data by `name`, classifying each item as: added (entry animation), updated (update animation), removed (remove animation)
2. `getDataURL` during animation captures the current (possibly mid-animation) frame — wait for animation to finish
3. For bar race: `animationDuration: 0` avoids initial grow-from-zero, `animationDurationUpdate` controls the race speed
