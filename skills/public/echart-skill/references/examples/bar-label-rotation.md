# bar-label-rotation

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=bar-label-rotation
**Chart Type:** `bar`

## ⚠️ CLEANED FOR STANDALONE — app.config values inlined

## Data Arrays — Replacement Guide

This chart has **3 data arrays** to build from DuckDB:

| Variable | Context | Format | Example |
|----------|---------|--------|---------|
| `legendData` | legend data | string array | `["Email","Ads","Video","Direct"]` |
| `categories` | xAxis data | string array | `["Mon","Tue","Wed","Thu","Fri"]` |
| `series` | series array | object array with nested data | see below |

### SERIES format
```json
[{
  "name": "Email",
  "type": "bar",
  "barGap": 0,
  "label": {
    "show": true, "position": "insideBottom", "distance": 15,
    "align": "left", "verticalAlign": "middle", "rotate": 90,
    "formatter": "{c}  {name|{a}}", "fontSize": 16, "rich": {"name": {}}
  },
  "emphasis": {"focus": "series"},
  "data": [120, 132, 101, 134, 90]
}]
```

## Reference Code (replace data arrays)

```javascript
const posList = ['left','right','top','bottom','inside','insideTop','insideLeft','insideRight','insideBottom','insideTopLeft','insideTopRight','insideBottomLeft','insideBottomRight'];

const labelOption = { show: true, position: 'insideBottom', distance: 15, align: 'left', verticalAlign: 'middle', rotate: 90, formatter: '{c}  {name|{a}}', fontSize: 16, rich: { name: {} } };

option = {
  tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
  legend: { data: legendData },
  toolbox: { show: true, orient: 'vertical', left: 'right', top: 'center',
    feature: { mark: { show: true }, dataView: { show: true, readOnly: false },
      magicType: { show: true, type: ['line','bar','stack'] },
      restore: { show: true }, saveAsImage: { show: true } } },
  xAxis: [{ type: 'category', axisTick: { show: false }, data: categories }],
  yAxis: [{ type: 'value' }],
  series: series
};
```

## Agent Workflow
1. Query DuckDB for 4+ numeric columns + category labels
2. Build `legendData`, `categories`, `series` arrays from query results
3. Replace data arrays in the reference code above using bracket-counting
4. Wrap in self-contained HTML shell (div#main + echarts.init + setOption)
5. `validate_chart.py` → verify
