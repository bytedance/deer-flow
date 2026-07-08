# sunburst-monochrome

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=sunburst-monochrome
**Chart Type:** `sunburst`

## User Data Requirements

Columns needed: need nested **name+value+children**

## Data Arrays — Complete Replacement Guide

**22 array(s)** to replace with real data:

### [0] `children` (context: root)
```
children: 
```

### [1] `children` (context: root)
```
children: [
          {
            value: 1,
            itemStyle: item1
          },
          {
            value: 2,
            children: [
    ...
```

### [2] `children` (context: root)
```
children: [
              {
                value: 1,
                itemStyle: item2
              }
            ]
```

### [3] `children` (context: root)
```
children: [
              {
                value: 1
              }
            ]
```

### [4] `children` (context: root)
```
children: 
```

### [5] `children` (context: root)
```
children: [
              {
                value: 1,
                itemStyle: item1
              },
              {
                value: 1
     ...
```

### [6] `children` (context: root)
```
children: [
              {
                value: 1
              }
            ]
```

### [7] `children` (context: root)
```
children: [
              {
                value: 1,
                itemStyle: item2
              }
            ]
```

### [8] `children` (context: root)
```
children: 
```

### [9] `children` (context: root)
```
children: [
          {
            value: 2,
            itemStyle: item2
          },
          {
            children: [
              {
          ...
```

### [10] `children` (context: root)
```
children: [
              {
                value: 1,
                itemStyle: item1
              }
            ]
```

### [11] `children` (context: root)
```
children: [
          {
            value: 3,
            children: [
              {
                value: 1
              },
              {
      ...
```

### [12] `children` (context: root)
```
children: [
              {
                value: 1
              },
              {
                value: 1,
                itemStyle: item2
     ...
```

### [13] `children` (context: root)
```
children: 
```

### [14] `children` (context: root)
```
children: 
```

### [15] `children` (context: root)
```
children: [
              {
                value: 1,
                itemStyle: item2
              },
              {
                value: 1
     ...
```

### [16] `children` (context: root)
```
children: [
              {
                value: 1
              },
              {
                value: 1,
                itemStyle: item1
     ...
```

### [17] `children` (context: root)
```
children: 
```

### [18] `children` (context: root)
```
children: [
          {
            value: 1,
            itemStyle: item2
          },
          {
            value: 2,
            children: [
    ...
```

### [19] `children` (context: root)
```
children: [
              {
                value: 2,
                itemStyle: item2
              }
            ]
```

### [20] `children` (context: root)
```
children: [
          {
            value: 1
          },
          {
            children: [
              {
                value: 1,
              ...
```

### [21] `children` (context: root)
```
children: [
              {
                value: 1,
                itemStyle: item2
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
title: Monochrome Sunburst
category: sunburst
titleCN: 单色旭日图
difficulty: 3
*/
const item1 = {
  color: '#F54F4A'
};
const item2 = {
  color: '#FF8C75'
};
const item3 = {
  color: '#FFB499'
};
const data = [
  {
    children: [
      {
        value: 5,
        children: [
          {
            value: 1,
            itemStyle: item1
          },
          {
            value: 2,
            children: [
              {
                value: 1,
                itemStyle: item2
              }
            ]
          },
          {
            children: [
              {
                value: 1
              }
            ]
          }
        ],
        itemStyle: item1
      },
      {
        value: 10,
        children: [
          {
            value: 6,
            children: [
              {
                value: 1,
                itemStyle: item1
              },
              {
                value: 1
              },
              {
                value: 1,
                itemStyle: item2
              },
              {
                value: 1
              }
            ],
            itemStyle: item3
          },
          {
            value: 2,
            children: [
              {
                value: 1
              }
            ],
            itemStyle: item3
          },
          {
            children: [
              {
                value: 1,
                itemStyle: item2
              }
            ]
          }
        ],
        itemStyle: item1
      }
    ],
    itemStyle: item1
  },
  {
    value: 9,
    children: [
      {
        value: 4,
        children: [
          {
            value: 2,
            itemStyle: item2
          },
          {
            children: [
              {
                value: 1,
                itemStyle: item1
              }
            ]
          }
        ],
        itemStyle: item1
      },
      {
        children: [
          {
            value: 3,
            children: [
              {
                value: 1
              },
              {
                value: 1,
                itemStyle: item2
              }
            ]
          }
        ],
        itemStyle: item3
      }
    ],
    itemStyle: item2
  },
  {
    value: 7,
    children: [
      {
        children: [
          {
            value: 1,
            itemStyle: item3
          },
          {
            value: 3,
            children: [
              {
                value: 1,
                itemStyle: item2
              },
              {
                value: 1
              }
            ],
            itemStyle: item2
          },
          {
            value: 2,
            children: [
              {
                value: 1
              },
              {
                value: 1,
                itemStyle: item1
              }
            ],
            itemStyle: item1
          }
        ],
        itemStyle: item3
      }
    ],
    itemStyle: item1
  },
  {
    children: [
      {
        value: 6,
        children: [
          {
            value: 1,
            itemStyle: item2
          },
          {
            value: 2,
            children: [
              {
                value: 2,
                itemStyle: item2
              }
            ],
            itemStyle: item1
          },
          {
            value: 1,
            itemStyle: item3
          }
        ],
        itemStyle: item3
      },
      {
        value: 3,
        children: [
          {
            value: 1
          },
          {
            children: [
              {
                value: 1,
                itemStyle: item2
              }
            ]
          },
          {
            value: 1
          }
        ],
        itemStyle: item3
      }
    ],
    itemStyle: item1
  }
];
option = {
  series: {
    radius: ['15%', '80%'],
    type: 'sunburst',
    sort: undefined,
    emphasis: {
      focus: 'ancestor'
    },
    data: data,
    label: {
      rotate: 'radial'
    },
    levels: [],
    itemStyle: {
      color: '#ddd',
      borderWidth: 2
    }
  }
};
```
