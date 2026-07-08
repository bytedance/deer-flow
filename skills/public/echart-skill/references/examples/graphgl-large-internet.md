# graphgl-large-internet

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=graphgl-large-internet
**Chart Type:** `graphGL`

## User Data Requirements

Columns needed: check data arrays in reference code for required format

## Data Arrays — Replacement Guide

The code contains **0 data array(s)** to replace:


## External Data Format

This example uses external data. Format from `internet.graph.json`:

```json
[
  [
    249,
    -33,
    4,
    4
  ],
  [
    251,
    -143,
    4,
    4
  ],
  [
    -715,
    234,
    4,
    0
  ]
]
```

Agent: build DuckDB query to produce matching data structure.
## Agent Workflow

1. **Analyze** user table → identify columns matching the required format above
2. **Query DuckDB** → transform to match each data array's format
3. **Replace**: use **bracket-counting** to find each `data: [...]` → replace with real data
4. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: GraphGL - Large Internet
category: graphGL
theme: dark
titleCN: GraphGL - å¤§è§æ¨¡äºèç½å¾è°±
shotDelay: 10000
shotWidth: 1920
*/
var graph = {
  "nodes": [
    [249, -33, 4, 4],
    [251, -143, 4, 4],
    [-715, 234, 4, 0],
    [-717, 290, 4, 0],
    [308, 1190, 4, 13],
    [-227, 1474, 4, 13],
    [143, 502, 4, 15],
    [738, -1719, 4, 5],
    // ... (22962 total entries — truncated, keep first 8 as sample. Agent: query DuckDB)
      ],
  "edges": [
    [1, 0],
    [2, 0],
    [3, 2],
    [4, 3],
    [5, 4],
    [6, 2],
    [6, 3],
    [6, 4],
    // ... (48435 total entries — truncated, keep first 8 as sample. Agent: query DuckDB)
      ]
};
var edges = graph.edges.map(function (edge) {
      return {
        source: edge[0],
        target: edge[1],
        value: 2
      };
    });
    var categories = [];
    var categoriesMap = {};
    var nodes = graph.nodes.map(function (node) {
      if (!categoriesMap[node[3]]) {
        categories.push({
          name: node[3]
        });
        categoriesMap[node[3]] = true;
      }
      return {
        x: Math.random() * window.innerWidth,
        y: Math.random() * window.innerHeight,
        // x: node[0],
        // y: node[1],
        symbolSize: node[2],
        category: node[3],
        value: 1
      };
    });
    myChart.setOption({
      color: [
        'rgb(203,239,15)',
        'rgb(73,15,239)',
        'rgb(239,231,15)',
        'rgb(15,217,239)',
        'rgb(30,15,239)',
        'rgb(15,174,239)',
        'rgb(116,239,15)',
        'rgb(239,15,58)',
        'rgb(15,239,174)',
        'rgb(239,102,15)',
      // ... (30 total entries — truncated, Agent: query DuckDB)
      ],
      series: [
        {
          type: 'graphGL',
          nodes: nodes,
          edges: edges,
          categories: categories.sort(function (a, b) {
            return a.name - b.name;
          }),
          lineStyle: {
            color: 'rgba(255,255,255,0.2)'
          },
          itemStyle: {
            opacity: 1
          },
          forceAtlas2: {
            steps: 1,
            stopThreshold: 1,
            jitterTolerence: 10,
            edgeWeight: [0.2, 1],
            gravity: 0,
            edgeWeightInfluence: 1,
            scaling: 0.2
          }
        }
      ]
    });

        // ... (31 total entries — truncated, keep first 8 as sample. Agent: query DuckDB)
          ]
```
