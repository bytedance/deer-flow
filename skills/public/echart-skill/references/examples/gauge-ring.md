# gauge-ring

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=gauge-ring
**Chart Type:** `gauge`

## User Data Requirements

Columns needed: need **3 values** (e.g., categories with percentages)

## Data Arrays — Complete Replacement Guide

**1 array** to replace with real data:

### [0] `gaugeData` — Ring gauge data (3 items, each with value + name + layout)

```javascript
const gaugeData = [
  { value: 20, name: 'Perfect',  title: { offsetCenter: ['0%', '-30%'] }, detail: { valueAnimation: true, offsetCenter: ['0%', '-20%'] } },
  { value: 40, name: 'Good',     title: { offsetCenter: ['0%', '0%'] },   detail: { valueAnimation: true, offsetCenter: ['0%', '10%'] } },
  { value: 60, name: 'Commonly', title: { offsetCenter: ['0%', '30%'] },  detail: { valueAnimation: true, offsetCenter: ['0%', '40%'] } }
];
```

> **Note**: Values are percentages (0-100). The gauge `max` defaults to 100 — no need to change unless your data exceeds 100.

## Agent Workflow

1. **Query DuckDB** → 3 values (e.g., 3 category percentages that sum to ~100)
2. **Replace gaugeData**: replace the entire `const gaugeData = [...]` array
3. **Remove setInterval** if using static data (or update random range)
4. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
const gaugeData = [
  {
    value: 20, name: 'Perfect',
    title: { offsetCenter: ['0%', '-30%'] },
    detail: { valueAnimation: true, offsetCenter: ['0%', '-20%'] }
  },
  {
    value: 40, name: 'Good',
    title: { offsetCenter: ['0%', '0%'] },
    detail: { valueAnimation: true, offsetCenter: ['0%', '10%'] }
  },
  {
    value: 60, name: 'Commonly',
    title: { offsetCenter: ['0%', '30%'] },
    detail: { valueAnimation: true, offsetCenter: ['0%', '40%'] }
  }
];

option = {
  series: [{
    type: 'gauge',
    startAngle: 90,
    endAngle: -270,
    pointer: { show: false },
    progress: {
      show: true, overlap: false, roundCap: true, clip: false,
      itemStyle: { borderWidth: 1, borderColor: '#464646' }
    },
    axisLine: { lineStyle: { width: 40 } },
    splitLine: { show: false, distance: 0, length: 10 },
    axisTick: { show: false },
    axisLabel: { show: false, distance: 50 },
    data: gaugeData,
    title: { fontSize: 14 },
    detail: {
      width: 50, height: 14, fontSize: 14, color: 'inherit',
      borderColor: 'inherit', borderRadius: 20, borderWidth: 1,
      formatter: '{value}%'
    }
  }]
};

// Optional live update — remove if static
setInterval(function () {
  gaugeData[0].value = +(Math.random() * 100).toFixed(2);
  gaugeData[1].value = +(Math.random() * 100).toFixed(2);
  gaugeData[2].value = +(Math.random() * 100).toFixed(2);
  myChart.setOption({ series: [{ data: gaugeData, pointer: { show: false } }] });
}, 2000);
```
