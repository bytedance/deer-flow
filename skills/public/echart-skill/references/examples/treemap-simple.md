# treemap-simple

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=treemap-simple
**Chart Type:** `treemap`

## User Data Requirements

Columns needed: need nested **name+value** or **name+children** tree structure

## Data Arrays — Replacement Guide

**1 data array** — the entire `data: [...]` block inside series:

Each node: `{name, value, children?}`. `value` at parent level = sum of children values.

```javascript
data: [
  { name: 'nodeA', value: 10, children: [
    { name: 'nodeAa', value: 4 },
    { name: 'nodeAb', value: 6 }
  ]},
  { name: 'nodeB', value: 20, children: [{
    name: 'nodeBa', value: 20, children: [
      { name: 'nodeBa1', value: 20 }
    ]
  }]}
]
```

## Agent Workflow

1. **Query DuckDB** → recursive CTE for parent-child hierarchy
2. **Build nested tree**: `{name, value, children: [{...}, ...]}` — value at each parent = sum of direct children
3. **Replace data block**: find `data: [` inside `type: 'treemap'` → bracket-counting → replace entire tree
4. **Wrap HTML** + validate_chart.py
5. **⚠️ VERIFY**: `parent.value == sum(children.values)` at every level

## Reference Code

```javascript
option = {
  series: [
    {
      type: 'treemap',
      data: [
        {
          name: 'nodeA',
          value: 10,
          children: [
            {
              name: 'nodeAa',
              value: 4
            },
            {
              name: 'nodeAb',
              value: 6
            }
          ]
        },
        {
          name: 'nodeB',
          value: 20,
          children: [
            {
              name: 'nodeBa',
              value: 20,
              children: [
                {
                  name: 'nodeBa1',
                  value: 20
                }
              ]
            }
          ]
        }
      ]
    }
  ]
};
```
