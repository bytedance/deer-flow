# graph-force2

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=graph-force2
**Chart Type:** `graph`

## User Data Requirements

Columns needed: need **nodes** [{name,...}] + **links/edges** [{source,target}]

## Data Arrays — Replacement Guide

The code contains **0 data array(s)** to replace:

## Agent Workflow

1. **Analyze** user table → identify columns matching the required format above
2. **Query DuckDB** → transform to match each data array's format
3. **Replace**: use **bracket-counting** to find each `data: [...]` → replace with real data
4. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: Force Layout
category: graph
titleCN: 力引导布局
difficulty: 1
*/
function createNodes(count) {
  var nodes = [];
  for (var i = 0; i < count; i++) {
    nodes.push({
      id: i + ''
    });
  }
  return nodes;
}
function createEdges(count) {
  var edges = [];
  if (count === 2) {
    return [[0, 1]];
  }
  for (var i = 0; i < count; i++) {
    edges.push([i, (i + 1) % count]);
  }
  return edges;
}
var datas = [];
for (var i = 0; i < 16; i++) {
  datas.push({
    nodes: createNodes(i + 2),
    edges: createEdges(i + 2)
  });
}
option = {
  series: datas.map(function (item, idx) {
    return {
      type: 'graph',
      layout: 'force',
      animation: false,
      data: item.nodes,
      left: (idx % 4) * 25 + '%',
      top: Math.floor(idx / 4) * 25 + '%',
      width: '25%',
      height: '25%',
      force: {
        // initLayout: 'circular'
        // gravity: 0
        repulsion: 60,
        edgeLength: 2
      },
      edges: item.edges.map(function (e) {
        return {
          source: e[0] + '',
          target: e[1] + ''
        };
      })
    };
  })
};
```
