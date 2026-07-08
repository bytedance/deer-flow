# Pie Chart 饼图

> **Source:** `echarts-docs/handbook/zh/how-to/chart-types/pie/*.md`

## Basic Pie Chart

```javascript
option = {
  series: [{
    type: 'pie',
    data: [
      { value: 335, name: 'Direct' },
      { value: 310, name: 'Email' },
      { value: 234, name: 'Affiliate' },
      { value: 135, name: 'Video Ads' },
      { value: 1548, name: 'Search' }
    ]
  }]
};
// No axes needed! value is NOT a percentage — ECharts auto-calculates proportions.
```

## Radius Control

```javascript
series: {
  type: 'pie',
  radius: '60%',            // Single value = outer radius (% of smaller container dimension)
  // OR
  radius: 200,              // Fixed pixels
}
```

**Note:** Percentage radius is relative to the **smaller** of container width/height.

## Doughnut (Ring) Chart

```javascript
series: {
  type: 'pie',
  radius: ['40%', '70%'],   // [inner, outer]
  label: {
    show: false,
    position: 'center'       // Center label inside the ring
  },
  emphasis: {
    label: {
      show: true,
      fontSize: 30,
      fontWeight: 'bold'
    }
  }
}
```

**CRITICAL:** When showing a center label, MUST set `avoidLabelOverlap: false`:

```javascript
series: {
  type: 'pie',
  radius: ['40%', '70%'],
  avoidLabelOverlap: false,   // <-- REQUIRED for center label
  label: { show: false, position: 'center' },
  emphasis: { label: { show: true } }
}
```

## Rose (Nightingale) Chart

```javascript
series: {
  type: 'pie',
  roseType: 'area',          // All sectors share same angle, radius proportional to value
  radius: ['20%', '80%'],
  data: [...]
}
```

## Label Customization

```javascript
series: {
  label: {
    show: true,
    position: 'outside',      // 'inside', 'outside', 'center', 'inner'
    formatter: '{b}: {c} ({d}%)',  // {a}=name, {b}=dataName, {c}=value, {d}=percentage
    alignTo: 'labelLine'      // Align labels to their label lines
  },
  labelLine: {
    show: true,
    length: 15,
    length2: 30,
    smooth: true
  }
}
```

## Zero-Sum Behavior

```javascript
series: {
  type: 'pie',
  stillShowZeroSum: true,   // default: show evenly-divided sectors when sum=0
  // set to false: show nothing when sum=0
}
```

## Important Notes

1. `radius` percentage is relative to the **smaller dimension** of the container
2. `radius` array can mix numbers and percentages (e.g., `['40%', 200]`) but be careful — ECharts auto-swaps so the smaller is always inner
3. `avoidLabelOverlap: false` is required for center-positioned labels in doughnut charts
4. Pie charts do NOT need `xAxis`/`yAxis` or grids
5. `data` items should be `{ value, name }` objects (not arrays)
