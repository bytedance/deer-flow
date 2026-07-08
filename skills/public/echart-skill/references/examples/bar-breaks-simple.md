# bar-breaks-simple

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=bar-breaks-simple
**Chart Type:** `shadow`

## User Data Requirements

Columns needed: check data arrays in reference code for required format

## Data Arrays — Complete Replacement Guide

**5 array(s)** to replace with real data:

### [0] `data` (context: xAxis)
```
data: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
```

### [1] `data` (context: series)
```
data: [1500, 2032, 2001, 3154, 2190, 4330, 2410]
```

### [2] `data` (context: root)
```
data: [1200, 1320, 1010, 1340, 900, 2300, 2100]
```

### [3] `data` (context: root)
```
data: [103200, 100320, 103010, 102340, 103900, 103300, 103200]
```

### [4] `data` (context: root)
```
data: [3106212, 3102118, 3102643, 3104631, 3106679, 3100130, 3107022]
```

## Agent Workflow

1. **Analyze** user table → identify columns matching the required format above
2. **Query DuckDB** → transform to match each data array's format
3. **Replace**: use **bracket-counting** to find each `data: [...]` → replace with real data
4. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: Bar Chart with Axis Breaks
titleCN: 断轴上的柱状图
category: bar
difficulty: 3
since: 6.0.0
*/
var _currentAxisBreaks = [
  {
    start: 5000,
    end: 100000,
    gap: '1.5%'
  },
  {
    // `start` and `end` are also used as the identifier for a certain axis break.
    start: 105000,
    end: 3100000,
    gap: '1.5%'
  }
];
option = {
  title: {
    text: 'Bar Chart with Axis Breaks',
    subtext: 'Click the break area to expand it',
    left: 'center',
    textStyle: {
      fontSize: 20
    },
    subtextStyle: {
      color: '#175ce5',
      fontSize: 15,
      fontWeight: 'bold'
    }
  },
  tooltip: {
    trigger: 'axis',
    axisPointer: {
      type: 'shadow'
    }
  },
  legend: {},
  grid: {
    top: 120
  },
  xAxis: [
    {
      type: 'category',
      data: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    }
  ],
  yAxis: [
    {
      type: 'value',
      breaks: _currentAxisBreaks,
      breakArea: {
        itemStyle: {
          opacity: 1
        },
        zigzagZ: 200
      }
    }
  ],
  series: [
    {
      name: 'Data A',
      type: 'bar',
      emphasis: {
        focus: 'series'
      },
      data: [1500, 2032, 2001, 3154, 2190, 4330, 2410]
    },
    {
      name: 'Data B',
      type: 'bar',
      emphasis: {
        focus: 'series'
      },
      data: [1200, 1320, 1010, 1340, 900, 2300, 2100]
    },
    {
      name: 'Data C',
      type: 'bar',
      emphasis: {
        focus: 'series'
      },
      data: [103200, 100320, 103010, 102340, 103900, 103300, 103200]
    },
    {
      name: 'Data D',
      type: 'bar',
      data: [3106212, 3102118, 3102643, 3104631, 3106679, 3100130, 3107022],
      emphasis: {
        focus: 'series'
      }
    }
  ]
};
/**
 * This is some interaction logic with axis break:
 *  - Click to expand and reset button.
 *
 * You can ignore this part if you do not need it.
 */
function initAxisBreakInteraction() {
  myChart.on('axisbreakchanged', function (params) {
    updateCollapseButton(params);
  });
  myChart.on('click', function (params) {
    if (params.name === 'collapseAxisBreakBtn') {
      collapseAxisBreak();
    }
  });
  function updateCollapseButton(params) {
    // If there is any axis break expanded, we need to show the collapse button.
    var needReset = false;
    for (let i = 0; i < params.breaks.length; i++) {
      const changedBreakItem = params.breaks[i];
      if (changedBreakItem.isExpanded) {
        needReset = true;
        break;
      }
    }
    myChart.setOption({
      // Draw the collapse button.
      graphic: [
        {
          elements: [
            {
              type: 'rect',
              ignore: !needReset,
              name: 'collapseAxisBreakBtn',
              top: 5,
              left: 5,
              shape: { r: 3, width: 140, height: 24 },
              style: { fill: '#eee', stroke: '#999', lineWidth: 1 },
              textContent: {
                type: 'text',
                style: {
                  text: 'Collapse Axis Breaks',
                  fontSize: 13,
                  fontWeight: 'bold'
                }
              },
              textConfig: { position: 'inside' }
            }
          ]
        }
      ]
    });
  }
  function collapseAxisBreak() {
    myChart.dispatchAction({
      type: 'collapseAxisBreak',
      yAxisIndex: 0,
      breaks: _currentAxisBreaks
    });
  }
} // End of initAxisBreakInteraction
setTimeout(initAxisBreakInteraction, 0);
```
