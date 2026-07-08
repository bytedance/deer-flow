# custom-hexbin

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=custom-hexbin
**Chart Type:** `group`

## User Data Requirements

Columns needed: check data arrays in reference code for required format

## Data Arrays — Complete Replacement Guide

**4 array(s)** to replace with real data:

### [0] `data` (context: legend)
```
data: ['bar', 'error']
```

### [1] `data` (context: root)
```
data: [0]
```

### [2] `dimensions` (context: series)
```
dimensions: [
          null,
          null,
          'Field Goals Attempted (hexagon size)',
          'Field Goal Percentage (color)'
        ]
```

### [3] `children` (context: root)
```