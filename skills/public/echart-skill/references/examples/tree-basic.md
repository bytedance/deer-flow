# tree-basic

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=tree-basic
**Chart Type:** `tree`

## User Data Requirements

Columns needed: need nested **name+children** tree structure

## Data Arrays — Complete Replacement Guide

**1 array** to replace with real data:

### [0] `treeData` — Nested tree structure (name + children)

```javascript
var treeData = {
  name: 'root',
  children: [
    { name: 'Child A', children: [{ name: 'Leaf A1' }, { name: 'Leaf A2' }] },
    { name: 'Child B', children: [{ name: 'Leaf B1' }] }
  ]
};
```

> **DuckDB query tip**: Use recursive CTE to build parent-child hierarchy, then assemble nested JSON.

## Agent Workflow

1. **Query DuckDB** → recursive CTE for parent-child relationships
2. **Build nested JSON**: assemble `{name, children: [...]}` structure from query results
3. **Replace treeData**: find `var treeData = {...}` → replace with generated nested data
4. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
// ⚠️ Agent: replace this sample tree with real DuckDB data
var treeData = {
  name: 'Root',
  children: [
    {
      name: 'Branch A',
      children: [
        { name: 'Leaf A1' },
        { name: 'Leaf A2' },
        { name: 'Leaf A3' }
      ]
    },
    {
      name: 'Branch B',
      children: [
        { name: 'Leaf B1' },
        {
          name: 'Sub-branch B2',
          children: [
            { name: 'Leaf B2a' },
            { name: 'Leaf B2b' }
          ]
        }
      ]
    },
    {
      name: 'Branch C',
      children: [
        { name: 'Leaf C1' }
      ]
    }
  ]
};

var myChart = echarts.init(document.getElementById('main'));

var option = {
  tooltip: {
    trigger: 'item',
    triggerOn: 'mousemove'
  },
  series: [
    {
      type: 'tree',
      data: [treeData],
      top: '1%',
      left: '7%',
      bottom: '1%',
      right: '20%',
      symbolSize: 7,
      label: {
        position: 'left',
        verticalAlign: 'middle',
        align: 'right',
        fontSize: 9
      },
      leaves: {
        label: {
          position: 'right',
          verticalAlign: 'middle',
          align: 'left'
        }
      },
      emphasis: {
        focus: 'descendant'
      },
      expandAndCollapse: true,
      animationDuration: 550,
      animationDurationUpdate: 750
    }
  ]
};

myChart.setOption(option);

window.addEventListener('resize', function() { myChart.resize(); });
```
