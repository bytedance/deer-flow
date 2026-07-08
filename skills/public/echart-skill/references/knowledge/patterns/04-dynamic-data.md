# Pattern: Dynamic Data Loading & Updates

> **Source:** `echarts-docs/handbook/zh/how-to/data/dynamic-data.md`

## Async Data Loading

```javascript
var chart = echarts.init(document.getElementById('main'));

// 1. Show empty chart first (optional — shows axes while loading)
chart.setOption({
  xAxis: { data: [] },
  yAxis: {},
  series: [{ type: 'bar', data: [] }]
});

// 2. Show loading animation
chart.showLoading();

// 3. Fetch data
fetch('/api/data')
  .then(res => res.json())
  .then(data => {
    chart.hideLoading();
    chart.setOption({
      xAxis: { data: data.categories },
      series: [{ data: data.values }]
    });
  });
```

## Dynamic Updates (Polling)

```javascript
function fetchAndUpdate() {
  fetch('/api/realtime')
    .then(res => res.json())
    .then(data => {
      chart.setOption({
        series: [{
          name: 'Sales',            // Match by name (reliable — recommended)
          data: data.values
        }]
      });
    });
}

// Poll every 3 seconds
setInterval(fetchAndUpdate, 3000);
```

## Update Methods

### By Name (Recommended)
```javascript
chart.setOption({
  series: [{ name: 'Sales', data: newData }]
});
```

### By Index (Fallback)
```javascript
chart.setOption({
  series: [{ data: newData }]  // Updates series[0]
});
```

## Data Update Detection

When `setOption` is called, ECharts:
1. Compares old data items with new data items **by `name`**
2. Classifies each item as:
   - **Added** (new, not in old data) → entry animation
   - **Updated** (exists in both) → update animation
   - **Removed** (in old, not in new) → remove animation
3. Animates the transitions

## Adding a Single Data Point

```javascript
// Using dataset (one-time option):
// Not directly supported — use series.data + appendData for incremental

// Using series.data approach:
var currentData = chart.getOption().series[0].data;
currentData.push(newValue);
chart.setOption({ series: [{ data: currentData }] });
```

## Performance Tips for Real-Time Data

1. **Use `appendData`** for million+ data streaming (see [api/02-instance-methods.md](../api/02-instance-methods.md))
2. **Disable animation** for high-frequency updates: `series: { animation: false }`
3. **Set `animationThreshold`** appropriately
4. **Use `lazyUpdate: true`** to batch multiple `setOption` calls into one frame
5. **Use `silent: true`** to suppress event dispatching during batch updates
