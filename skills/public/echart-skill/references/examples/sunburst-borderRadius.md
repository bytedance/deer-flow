# sunburst-borderRadius

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=sunburst-borderRadius
**Chart Type:** `sunburst`

## User Data Requirements

Columns needed: need nested **name+value+children**

## Data Arrays — Complete Replacement Guide

**6 array(s)** to replace with real data:

### [0] `children` (context: root)
```
children: 
```

### [1] `children` (context: root)
```
children: [
          {
            name: 'Cousin Jack',
            value: 2
          },
          {
            name: 'Cousin Mary',
            va...
```

### [2] `children` (context: root)
```
children: [
              {
                name: 'Jackson',
                value: 2
              }
            ]
```

### [3] `children` (context: root)
```
children: [
          {
            name: 'Me',
            value: 5
          },
          {
            name: 'Brother Peter',
            value: 1
...
```

### [4] `children` (context: root)
```
children: [
      {
        name: 'Uncle Nike',
        children: [
          {
            name: 'Cousin Betty',
            value: 1
          },
  ...
```

### [5] `children` (context: root)
```
children: [
          {
            name: 'Cousin Betty',
            value: 1
          },
          {
            name: 'Cousin Jenny',
            ...
```

## Agent Workflow

1. **Analyze** user table → identify columns matching the required format above
2. **Query DuckDB** → transform to match each data array's format
3. **Replace**: use **bracket-counting** to find each `data: [...]` → replace with real data
4. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: Sunburst with Rounded Corner
category: sunburst
titleCN: 圆角旭日图
difficulty: 2
*/
var data = [
  {
    name: 'Grandpa',
    children: [
      {
        name: 'Uncle Leo',
        value: 15,
        children: [
          {
            name: 'Cousin Jack',
            value: 2
          },
          {
            name: 'Cousin Mary',
            value: 5,
            children: [
              {
                name: 'Jackson',
                value: 2
              }
            ]
          },
          {
            name: 'Cousin Ben',
            value: 4
          }
        ]
      },
      {
        name: 'Father',
        value: 10,
        children: [
          {
            name: 'Me',
            value: 5
          },
          {
            name: 'Brother Peter',
            value: 1
          }
        ]
      }
    ]
  },
  {
    name: 'Nancy',
    children: [
      {
        name: 'Uncle Nike',
        children: [
          {
            name: 'Cousin Betty',
            value: 1
          },
          {
            name: 'Cousin Jenny',
            value: 2
          }
        ]
      }
    ]
  }
];
option = {
  series: {
    type: 'sunburst',
    data: data,
    radius: [60, '90%'],
    itemStyle: {
      borderRadius: 7,
      borderWidth: 2
    },
    label: {
      show: false
    }
  }
};
```
