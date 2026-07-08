# bar-brush

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=bar-brush
**Chart Type:** `bar`

## ⚠️ Data generated via loop — NOT static arrays

Official code uses `let data1=[]; for(...){data1.push(...)}`. The option references VARIABLES (`data: data1`), not literals (`data: [...]`). Standard bracket-counting won't work.

## Fix: Replace variable references with real array literals

In the option block, replace:
- `data: data1` → `data: [real_values_1]`
- `data: data2` → `data: [real_values_2]`
- `data: data3` → `data: [real_values_3]`
- `data: data4` → `data: [real_values_4]`
- `data: xAxisData` → `data: ["cat1","cat2",...]`

Remove the `for` loop and variable declarations (`let data1=[];`) — no longer needed.

## Reference Code
```javascript
let xAxisData = []; let data1 = []; let data2 = []; let data3 = []; let data4 = [];
for (let i = 0; i < 10; i++) {
  xAxisData.push('Class' + i);
  data1.push(+(Math.random() * 2).toFixed(2));
  data2.push(+(Math.random() * 5).toFixed(2));
  data3.push(+(Math.random() + 0.3).toFixed(2));
  data4.push(+Math.random().toFixed(2));
}
option = {
  legend: { data: ['bar','bar2','bar3','bar4'], left: '10%' },
  brush: { toolbox: ['rect','polygon','clear'], xAxisIndex: 0 },
  toolbox: { feature: { brush: { type: ['rect','polygon','clear'] } } },
  xAxis: { data: xAxisData, name: 'X' },
  yAxis: {},
  series: [
    { name: 'bar', type: 'bar', data: data1 },
    { name: 'bar2', type: 'bar', data: data2 },
    { name: 'bar3', type: 'bar', data: data3 },
    { name: 'bar4', type: 'bar', data: data4 }
  ]
};
```

## Agent Workflow
1. Query DuckDB for 4 numeric columns + category labels
2. Use string replace: `data: data1` → `data: [1.2, 3.4, ...]`
3. Remove the `for` loop and `let data1=[]` lines
4. Wrap in HTML → validate
