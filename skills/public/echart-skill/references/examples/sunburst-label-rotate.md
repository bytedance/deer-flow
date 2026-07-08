# sunburst-label-rotate

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=sunburst-label-rotate
**Chart Type:** `sunburst`

## User Data Requirements

Columns needed: need nested **name+value+children**

## Data Arrays — Complete Replacement Guide

**9 array(s)** to replace with real data:

### [0] `data` (context: series)
```
data: 
```

### [1] `children` (context: series)
```
children: [
            {
              value: 4,
              children: [
                {
                  value: 2
                },
          ...
```

### [2] `children` (context: root)
```
children: [
                {
                  value: 2
                },
                {
                  value: 1
                },
          ...
```

### [3] `children` (context: root)
```
children: [
            {
              children: [
                {
                  value: 2
                }
              ]
            }
     ...
```

### [4] `children` (context: root)
```
children: [
                {
                  value: 2
                }
              ]
```

### [5] `children` (context: root)
```
children: [
            {
              children: [
                {
                  value: 2
                }
              ]
            }
     ...
```

### [6] `children` (context: root)
```
children: [
                {
                  value: 2
                }
              ]
```

### [7] `children` (context: root)
```
children: [
            {
              children: [
                {
                  value: 1
                }
              ]
            }
     ...
```

### [8] `children` (context: root)
```
children: [
                {
                  value: 1
                }
              ]
```

## Agent Workflow

1. **Analyze** user table → identify columns matching the required format above
2. **Query DuckDB** → transform to match each data array's format
3. **Replace**: use **bracket-counting** to find each `data: [...]` → replace with real data
4. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: Sunburst Label Rotate
category: sunburst
titleCN: 旭日图标签旋转
difficulty: 2
*/
option = {
  silent: true,
  series: [
    {
      radius: ['15%', '80%'],
      type: 'sunburst',
      sort: undefined,
      emphasis: {
        focus: 'ancestor'
      },
      data: [
        {
          value: 8,
          children: [
            {
              value: 4,
              children: [
                {
                  value: 2
                },
                {
                  value: 1
                },
                {
                  value: 1
                },
                {
                  value: 0.5
                }
              ]
            },
            {
              value: 2
            }
          ]
        },
        {
          value: 4,
          children: [
            {
              children: [
                {
                  value: 2
                }
              ]
            }
          ]
        },
        {
          value: 4,
          children: [
            {
              children: [
                {
                  value: 2
                }
              ]
            }
          ]
        },
        {
          value: 3,
          children: [
            {
              children: [
                {
                  value: 1
                }
              ]
            }
          ]
        }
      ],
      label: {
        color: '#000',
        textBorderColor: '#fff',
        textBorderWidth: 2,
        formatter: function (param) {
          var depth = param.treePathInfo.length;
          if (depth === 2) {
            return 'radial';
          } else if (depth === 3) {
            return 'tangential';
          } else if (depth === 4) {
            return '0';
          }
          return '';
        }
      },
      levels: [
        {},
        {
          itemStyle: {
            color: '#CD4949'
          },
          label: {
            rotate: 'radial'
          }
        },
        {
          itemStyle: {
            color: '#F47251'
          },
          label: {
            rotate: 'tangential'
          }
        },
        {
          itemStyle: {
            color: '#FFC75F'
          },
          label: {
            rotate: 0
          }
        }
      ]
    }
  ]
};
```
