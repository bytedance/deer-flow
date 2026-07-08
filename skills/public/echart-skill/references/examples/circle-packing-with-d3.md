# circle-packing-with-d3

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=circle-packing-with-d3
**Chart Type:** `circle`

## User Data Requirements

Columns needed: check data arrays in reference code for required format

## Data Arrays — Replacement Guide

The code contains **0 data array(s)** to replace:


## External Data Format

This example uses external data. Format from `option-view.json`:

```json
{
  "dataZoom": {
    "$count": 6229
  },
  "legend": {
    "$count": 9273,
    "align": {
      "$count": 942
    },
    "right": {
      "$count": 634
    },
    "z": {
      "$count": 567
    },
    "orient": {
      "$count": 1356
    },
    "show": {
      "$count": 1181
    },
    "zlevel": {
      "$count": 634
    },
    "left": {
      "$count": 1137
    },
    "itemHeight": {
      "$count": 455
    },
    "bottom": {
      "$count": 788
    },
    "itemGap": {
      "$count": 761
    
...
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
title: Circle Packing with d3
category: custom
titleCN: 基于 d3 的圆形包络图
difficulty: 11
*/
var res = {
  "dataZoom": {
    "$count": 6229
  },
  "legend": {
    "$count": 9273,
    "align": {
      "$count": 942
    },
    "right": {
      "$count": 634
    },
    "z": {
      "$count": 567
    },
    "orient": {
      "$count": 1356
    },
    "show": {
      "$count": 1181
    },
    "zlevel": {
      "$count": 634
    },
    "left": {
      "$count": 1137
    },
    "itemHeight": {
      "$count": 455
    },
    "bottom": {
      "$count": 788
    },
    "itemGap": {
      "$count": 761
    },
    "formatter": {
      "$count": 935
    },
    "selectedMode": {
      "$count": 937
    },
    "selected": {
      "$count": 1038
    },
    "shadowBlur": {
      "$count": 199
    },
    "shadowColor": {
      "$count": 189
    },
    "shadowOffsetX": {
      "$count": 180
    },
    "shadowOffsetY": {
      "$count": 142
    },
    "backgroundColor": {
      "$count": 471
    },
    "data": {
      "$count": 1430,
      "icon": {
        "$count": 882
      },
      "name": {
        "$count": 660
      },
      "textStyle": {
        "$count": 798
      }
    },
    "top": {
      "$count": 831
    },
    "padding": {
      "$count": 706
    },
    "itemWidth": {
      "$count": 603
    },
    "textStyle": {
      "$count": 849,
      "fontSize": {
        "$count": 150
      },
      "color": {
        "$count": 237
      },
      "fontStyle": {
        "$count": 113
      },
      "fontWeight": {
        "$count": 101
      },
      "fontFamily": {
        "$count": 91
      }
    },
    "borderColor": {
      "$count": 318
    },
    "borderWidth": {
      "$count": 233
    },
    "height": {
      "$count": 64
    },
    "width": {
      "$count": 83
    }
  },
  "dataZoom-inside": {
    "$count": 1250,
    "yAxisIndex": {
      "$count": 221
    },
    "startValue": {
      "$count": 264
    },
    "endValue": {
      "$count": 136
    },
    "xAxisIndex": {
      "$count": 388
    },
    "angleAxisIndex": {
      "$count": 161
    },
    "filterMode": {
      "$count": 288
    },
    "type": {
      "$count": 639
    },
    "start": {
      "$count": 449
    },
    "orient": {
      "$count": 210
    },
    "radiusAxisIndex": {
      "$count": 141
    },
    "throttle": {
      "$count": 171
    },
    "end": {
      "$count": 191
    },
    "zoomLock": {
      "$count": 168
    }
  },
  "xAxis": {
    "$count": 10643,
    "gridIndex": {
      "$count": 1840
    },
    "splitLine": {
      "$count": 1235,
      "show": {
        "$count": 156
      },
      "lineTyle": {
        "$count": 17,
        "shadowBlur": {
          "$count": 8
        },
        "shadowColor": {
          "$count": 7
        },
        "shadowOffsetX": {
          "$count": 6
        },
        "opacity": {
          "$count": 7
        },
        "width": {
          "$count": 9
        },
        "color": {
          "$count": 11
        },
        "shadowOffsetY": {
          "$count": 5
        },
        "type": {
          "$count": 12
        }
      },
      "interval": {
        "$count": 198
      },
      "lineStyle": {
        "color": {
          "$count": 81
        },
        "$count": 185,
        "type": {
          "$count": 49
        },
        "width": {
          "$count": 33
        },
        "shadowBlur": {
          "$count": 28
        },
        "opacity": {
          "$count": 29
        },
        "shadowColor": {
          "$count": 27
        },
        "shadowOffsetX": {
          "$count": 16
        },
        "shadowOffsetY": {
          "$count": 14
        }
      }
    },
    "axisTick": {
      "$count": 1461,
      "interval": {
        "$count": 345
      },
      "inside": {
        "$count": 195
      },
      "show": {
        "$count": 250
      },
      "length": {
        "$count": 211
      },
      "lineStyle": {
        "$count": 249,
        "color": {
          "$count": 87
        },
        "shadowColor": {
          "$count": 38
        },
        "width": {
          "$count": 42
        },
        "type": {
          "$count": 50
        },
        "opacity": {
          "$count": 29
        },
        "shadowBlur": {
          "$count": 39
        },
        "shadowOffsetX": {
          "$count": 26
        },
        "shadowOffsetY": {
          "$count": 19
        }
      }
    },
    "type": {
      "$count": 2888
    },
    "axisLabel": {
      "$count": 1980,
      "interval": {
        "$count": 695
      },
      "rotate": {
        "$count": 399
      },
      "show": {
        "$count": 343
      },
      "inside": {
        "$count": 303
      },
      "margin": {
        "$count": 337
      },
      "formatter": {
        "$count": 836
      },
      "textStyle": {
        "$count": 417,
        "fontSize": {
          "$count": 97
        },
        "color": {
          "$count": 136
        },
        "fontStyle": {
          "$count": 84
        },
        "fontWeight": {
          "$count": 68
        },
        "fontFamily": {
          "$count": 55
        }
      }
    },
    "position": {
      "$count": 1812
    },
    "nameTextStyle": {
      "$count": 1593,
      "fontStyle": {
        "$count": 192
      },
      "color": {
        "$count": 329
      },
      "fontFamily": {
        "$count": 143
      },
      "fontWeight": {
        "$count": 138
      },
      "fontSize": {
        "$count": 194
      }
    },
    "nameGap": {
      "$count": 1258
    },
    "interval": {
      "$count": 1363
    },
    "boundaryGap": {
      "$count": 1812
    },
    "scale": {
      "$count": 1195
    },
    "inverse": {
      "$count": 1017
    },
    "data": {
      "$count": 1546,
      "textStyle": {
        "baseline": {
          "$count": 155
        },
        "$count": 429,
        "color": {
          "$count": 161
        },
        "align": {
          "$count": 147
        },
        "fontStyle": {
          "$count": 97
        },
        "fontWeight": {
          "$count": 74
        },
        "fontFamily": {
          "$count": 65
        },
        "fontSize": {
          "$count": 76
        }
      },
      "value": {
        "$count": 715
      }
    },
    "nameLocation": {
      "$count": 1310
    },
    "name": {
      "$count": 1396
    },
    "splitNumber": {
      "$count": 1367
    },
    "min": {
      "$count": 1112
    },
    "axisLine": {
      "lineStyle": {
        "$count": 563,
        "type": {
          "$count": 156
        },
        "color": {
          "$count": 257
        },
        "shadowColor": {
          "$count": 113
        },
        "shadowBlur": {
          "$count": 124
        },
        "shadowOffsetX": {
          "$count": 70
        },
        "width": {
          "$count": 138
        },
        "opacity": {
          "$count": 104
        },
        "shadowOffsetY": {
          "$count": 56
        }
      },
      "show": {
        "$count": 449
      },
      "$count": 1822,
      "onZero": {
        "$count": 394
      }
    },
    "splitArea": {
      "$count": 795,
      "show": {
        "$count": 95
      },
      "interval": {
        "$count": 152
      },
      "areaStyle": {
        "$count": 187,
        "color": {
          "$count": 150
        },
        "shadowBlur": {
          "$count": 57
        },
        "shadowColor": {
          "$count": 52
        },
        "shadowOffsetX": {
          "$count": 30
        },
        "opacity": {
          "$count": 39
        },
        "shadowOffsetY": {
          "$count": 19
        }
      }
    },
    "max": {
      "$count": 707
    }
  },
  "radiusAxis": {
    "$count": 4587,
    "data": {
      "value": {
        "$count": 16
      },
      "$count": 64,
      "textStyle": {
        "$count": 15,
        "color": {
          "$count": 3
        },
        "baseline": {
          "$count": 2
        }
      }
    },
    "interval": {
      "$count": 33
    },
    "min": {
      "$count": 43
    },
    "axisLabel": {
      "formatter": {
        "$count": 63
      },
      "$count": 53,
      "show": {
        "$count": 10
      },
      "interval": {
        "$count": 9
      },
      "inside": {
        "$count": 5
      },
      "rotate": {
        "$count": 8
      },
      "margin": {
        "$count": 6
      },
      "textStyle": {
        "$count": 10,
        "color": {
          "$count": 5
        },
        "fontStyle": {
          "$count": 1
        },
        "fontWeight": {
          "$count": 1
        },
        "fontSize": {
          "$count": 1
        },
        "fontFamily": {
          "$count": 1
        }
      }
    },
    "splitArea": {
      "areaStyle": {
        "color": {
          "$count": 12
        },
        "shadowColor": {
          "$count": 2
        },
        "$count": 13
      },
      "$count": 36,
      "show": {
        "$count": 4
      },
      "interval": {
        "$count": 3
      }
    },
    "polarIndex": {
      "$count": 139
    },
    "type": {
      "$count": 104
    },
    "name": {
      "$count": 65
    },
    "nameLocation": {
      "$count": 62
    },
    "nameTextStyle": {
      "$count": 50,
      "color": {
        "$count": 18
      },
      "fontStyle": {
        "$count": 4
      },
      "fontSize": {
        "$count": 3
      },
      "fontWeight": {
        "$count": 4
      },
      "fontFamily": {
        "$count": 2
      }
    },
    "nameGap": {
      "$count": 32
    },
    "inverse": {
      "$count": 29
    },
    "max": {
      "$count": 40
    },
    "axisLine": {
      "$count": 45,
      "show": {
        "$count": 12
      },
      "lineStyle": {
        "color": {
          "$count": 19
        },
        "$count": 10,
        "width": {
          "$count": 7
        },
        "shadowBlur": {
          "$count": 7
        },
        "shadowColor": {
          "$count": 5
        },
        "shadowOffsetX": {
          "$count": 2
        },
        "type": {
          "$count": 8
        },
        "opacity": {
          "$count": 5
        },
        "shadowOffsetY": {
          "$count": 2
        }
      }
    },
    "splitLine": {
      "$count": 44,
      "lineStyle": {
        "type": {
          "$count": 1
        },
        "width": {
          "$count": 1
        },
        "$count": 8,
        "color": {
          "$count": 6
        },
        "shadowColor": {
          "$count": 3
        },
        "shadowBlur": {
          "$count": 1
        }
      },
      "interval": {
        "$count": 4
      },
      "show": {
        "$count": 4
      }
    },
    "splitNumber": {
      "$count": 42
    },
    "boundaryGap": {
      "$count": 51
    },
    "scale": {
      "$count": 40
    },
    "axisTick": {
      "$count": 34,
      "interval": {
        "$count": 5
      },
      "inside": {
        "$count": 3
      },
      "lineStyle": {
        "type": {
          "$count": 1
        },
        "$count": 7,
        "color": {
          "$count": 2
        }
      },
      "length": {
        "$count": 2
      },
      "show": {
        "$count": 2
      }
    }
  },
  "yAxis": {
    "$count": 7115,
    "splitNumber": {
      "$count": 1005
    },
    "gridIndex": {
      "$count": 1161
    },
    "axisLabel": {
      "$count": 1068,
      "textStyle": {
        "$count": 186,
        "fontFamily": {
          "$count": 30
        },
        "fontWeight": {
          "$count": 34
        },
        "color": {
          "$count": 63
        },
        "fontSize": {
          "$count": 39
        },
        "fontStyle": {
          "$count": 33
        }
      },
      "inside": {
        "$count": 161
      },
      "formatter": {
        "$count": 519
      },
      "interval": {
        "$count": 255
      },
      "margin": {
        "$count": 166
      },
      "rotate": {
        "$count": 137
      },
      "show": {
        "$count": 164
      }
    },
    "nameTextStyle": {
      "$count": 970,
      "color": {
        "$count": 139
      },
      "fontStyle": {
        "$count": 85
      },
      "fontSize": {
        "$count": 91
      },
      "fontFamily": {
        "$count": 57
      },
      "fontWeight": {
        "$count": 61
      }
    },
    "nameLocation": {
      "$count": 886
    },
    "axisTick": {
      "$count": 710,
      "inside": {
        "$count": 73
      },
      "interval": {
        "$count": 124
      },
      "length": {
        "$count": 83
      },
      "lineStyle": {
        "color": {
          "$count": 31
        },
        "shadowColor": {
          "$count": 12
        },
        "$count": 91,
        "opacity": {
          "$count": 12
        },
        "width": {
          "$count": 16
        },
        "type": {
          "$count": 17
        },
        "shadowBlur": {
          "$count": 8
        },
        "shadowOffsetX": {
          "$count": 11
        },
        "shadowOffsetY": {
          "$count": 11
        }
      },
      "show": {
        "$count": 108
      }
    },
    "data": {
      "$count": 757,
      "value": {
        "$count": 327
      },
      "textStyle": {
        "$count": 215,
        "align": {
          "$count": 67
        },
        "fontWeight": {
          "$count": 22
        },
        "baseline": {
          "$count": 57
        },
        "fontSize": {
          "$count": 31
        },
        "fontStyle": {
          "$count": 29
        },
        "color": {
          "$count": 57
        },
        "fontFamily": {
          "$count": 16
        }
      }
    },
    "axisLine": {
      "$count": 999,
      "lineStyle": {
        "$count": 233,
        "color": {
          "$count": 104
        },
        "width": {
          "$count": 46
        },
        "shadowBlur": {
          "$count": 43
        },
        "opacity": {
          "$count": 37
        },
        "type": {
          "$count": 46
        },
        "shadowColor": {
          "$count": 38
        },
        "shadowOffsetX": {
          "$count": 20
        },
        "shadowOffsetY": {
          "$count": 14
        }
      },
      "onZero": {
        "$count": 187
      },
      "show": {
        "$count": 231
      }
    },
    "type": {
      "$count": 1527
    },
    "min": {
      "$count": 845
    },
    "interval": {
      "$count": 904
    },
    "name": {
      "$count": 924
    },
    "inverse": {
      "$count": 727
    },
    "boundaryGap": {
      "$count": 971
    },
    "scale": {
      "$count": 892
    },
    "max": {
      "$count": 667
    },
    "position": {
      "$count": 1257
    },
    "nameGap": {
      "$count": 808
    },
    "splitArea": {
      "$count": 427,
      "interval": {
        "$count": 104
      },
      "show": {
        "$count": 56
      },
      "areaStyle": {
        "$count": 79,
        "shadowOffsetX": {
          "$count": 11
        },
        "shadowOffsetY": {
          "$count": 11
        },
        "shadowColor": {
          "$count": 14
        },
        "shadowBlur": {
          "$count": 16
        },
        "color": {
          "$count": 68
        },
        "opacity": {
          "$count": 17
        }
      }
    },
    "splitLine": {
      "$count": 625,
      "lineTyle": {
        "$count": 8,
        "type": {
          "$count": 7
        },
        "color": {
          "$count": 4
        },
        "opacity": {
          "$count": 1
        },
        "shadowOffsetX": {
          "$count": 1
        },
        "shadowOffsetY": {
          "$count": 1
        },
        "shadowColor": {
          "$count": 1
        },
        "shadowBlur": {
          "$count": 1
        },
        "width": {
          "$count": 3
        }
      },
      "show": {
        "$count": 104
      },
      "interval": {
        "$count": 102
      },
      "lineStyle": {
        "color": {
          "$count": 43
        },
        "$count": 106,
        "opacity": {
          "$count": 16
        },
        "shadowOffsetY": {
          "$count": 9
        },
        "shadowOffsetX": {
          "$count": 11
        },
        "shadowColor": {
          "$count": 24
        },
        "shadowBlur": {
          "$count": 21
        },
        "width": {
          "$count": 17
        },
        "type": {
          "$count": 37
        }
      }
    }
  },
  "parallel": {
    "$count": 3187,
    "layout: 'horizontal'": {
      "$count": 32
    },
    "zlevel": {
      "$count": 44
    },
    "parallelAxisDefault": {
      "$count": 41,
      "inverse": {
        "$count": 6
      },
      "axisLabel": {
        "$count": 11,
        "show": {
          "$count": 4
        },
        "formatter": {
          "$count": 18
        },
        "rotate": {
          "$count": 4
        },
        "textStyle": {
          "color": {
            "$count": 2
          },
          "$count": 2,
          "fontStyle": {
            "$count": 1
          }
        },
        "inside": {
          "$count": 1
        },
        "margin": {
          "$count": 2
        }
      },
      "nameTextStyle": {
        "color": {
          "$count": 4
        },
        "fontSize": {
          "$count": 2
        },
        "$count": 5,
        "fontStyle": {
          "$count": 3
        },
        "fontFamily": {
          "$count": 3
        }
      },
      "axisLine": {
        "$count": 6,
        "show": {
          "$count": 3
        },
        "lineStyle": {
          "color": {
            "$count": 2
          },
          "shadowBlur": {
            "$count": 1
          },
          "$count": 2,
          "type": {
            "$count": 1
          }
        }
      },
      "nameLocation": {
        "$count": 6
      },
      "data": {
        "$count": 10,
        "textStyle": {
          "$count": 1,
          "align": {
            "$count": 2
          },
          "color": {
            "$count": 2
          },
          "baseline": {
            "$count": 1
          },
          "fontStyle": {
            "$count": 1
          }
        },
        "value": {
          "$count": 5
        }
      },
      "type": {
        "$count": 6
      },
      "name": {
        "$count": 5
      },
      "nameGap": {
        "$count": 4
      },
      "boundaryGap": {
        "$count": 6
      },
      "scale": {
        "$count": 5
      },
      "splitNumber": {
        "$count": 3
      },
      "interval": {
        "$count": 7
      },
      "axisTick": {
        "$count": 4,
        "length": {
          "$count": 3
        },
        "lineStyle": {
          "color": {
            "$count": 2
          },
          "$count": 2,
          "type": {
            "$count": 1
          }
        },
        "show": {
          "$count": 2
        },
        "interval": {
          "$count": 2
        },
        "inside": {
          "$count": 2
        }
      },
      "max": {
        "$count": 4
      },
      "min": {
        "$count": 2
      }
    },
    "height": {
      "$count": 17
    },
    "width": {
      "$count": 13
    },
    "z": {
      "$count": 12
    },
    "top": {
      "$count": 12
    },
    "left": {
      "$count": 12
    },
    "bottom": {
      "$count": 14
    },
    "right": {
      "$count": 10
    }
  },
  "tooltip": {
    "$count": 8112,
    "trigger": {
      "$count": 2127
    },
    "triggerOn": {
      "$count": 1027
    },
    "showContent": {
      "$count": 1075
    },
    "axisPointer": {
      "type": {
        "$count": 355
      },
      "$count": 1098,
      "lineStyle": {
        "$count": 167,
        "color": {
          "$count": 54
        },
        "shadowColor": {
          "$count": 15
        },
        "type": {
          "$count": 47
        },
        "opacity": {
          "$count": 25
        },
        "shadowBlur": {
          "$count": 29
        },
        "width": {
          "$count": 27
        },
        "shadowOffsetY": {
          "$count": 11
        },
        "shadowOffsetX": {
          "$count": 10
        }
      },
      "shadowStyle": {
        "$count": 81,
        "opacity": {
          "$count": 20
        },
        "color": {
          "$count": 31
        },
        "shadowBlur": {
          "$count": 22
        },
        "shadowColor": {
          "$count": 18
        },
        "shadowOffsetY": {
          "$count": 13
        },
        "shadowOffsetX": {
          "$count": 16
        }
      },
      "axis": {
        "$count": 266
      },
      "animation": {
        "$count": 178
      },
      "animationDuration": {
        "$count": 92
      },
      "animationEasing": {
        "$count": 82
      },
      "animationDurationUpdate": {
        "$count": 69
      },
      "animationEasingUpdate": {
        "$count": 75
      },
      "crossStyle": {
        "$count": 130,
        "textStyle": {
          "$count": 33,
          "color": {
            "$count": 9
          },
          "fontSize": {
            "$count": 4
          },
          "fontStyle": {
            "$count": 10
          },
          "fontWeight": {
            "$count": 8
          },
          "fontFamily": {
            "$count": 9
          }
        },
        "shadowOffsetX": {
          "$count": 20
        },
        "shadowBlur": {
          "$count": 21
        },
        "opacity": {
          "$count": 32
        },
        "color": {
          "$count": 30
        },
        "shadowColor": {
          "$count": 18
        },
        "width": {
          "$count": 21
        },
        "type": {
          "$count": 34
        },
        "shadowOffsetY": {
          "$count": 13
        }
      }
    },
    "formatter": {
      "$count": 2620
    },
    "show": {
      "$count": 1334
    },
    "backgroundColor": {
      "$count": 479
    },
    "textStyle": {
      "$count": 519,
      "color": {
        "$count": 94
      },
      "fontStyle": {
        "$count": 68
      },
      "fontWeight": {
        "$count": 52
      },
      "fontSize": {
        "$count": 72
      },
      "fontFamily": {
        "$count": 48
      }
    },
    "borderColor": {
      "$count": 331
    },
    "alwaysShowContent": {
      "$count": 760
    },
    "hideDelay": {
      "$count": 565
    },
    "enterable": {
      "$count": 586
    },
    "position": {
      "$count": 956
    },
    "transitionDuration": {
      "$count": 584
    },
    "borderWidth": {
      "$count": 303
    },
    "padding": {
      "$count": 358
    }
  },
  "visualMap": {
    "$count": 5807
  },
  "visualMap-continuous": {
    "$count": 1010,
    "dimension": {
      "$count": 250
    },
    "outOfRange": {
      "$count": 230
    },
    "inRange": {
      "$count": 503
    },
    "type": {
      "$count": 496
    },
    "min": {
      "$count": 234
    },
    "max": {
      "$count": 157
    },
    "calculable": {
      "$count": 572
    },
    "realtime": {
      "$count": 185
    },
    "inverse": {
      "$count": 207
    },
    "precision": {
      "$count": 181
    },
    "itemWidth": {
      "$count": 151
    },
    "itemHeight": {
      "$count": 112
    },
    "align: 'auto'": {
      "$count": 121
    },
    "text": {
      "$count": 119
    },
    "textGap": {
      "$count": 116
    },
    "handlePosition": {
      "$count": 148
    },
    "show": {
      "$count": 124
    },
    "seriesIndex": {
      "$count": 290
    },
    "zlevel": {
      "$count": 86
    },
    "z": {
      "$count": 59
    },
    "left": {
      "$count": 116
    },
    "top": {
      "$count": 69
    },
    "right": {
      "$count": 54
    },
    "bottom": {
      "$count": 57
    },
    "orient": {
      "$count": 122
    },
    "color": {
      "$count": 235
    },
    "formatter": {
      "$count": 171
    },
    "padding": {
      "$count": 71
    },
    "textStyle": {
      "$count": 88,
      "color": {
        "$count": 17
      },
      "fontStyle": {
        "$count": 6
      },
      "fontWeight": {
        "$count": 5
      },
      "fontFamily": {
        "$count": 5
      },
      "fontSize": {
        "$count": 5
      }
    },
    "backgroundColor": {
      "$count": 102
    },
    "borderColor": {
      "$count": 60
    },
    "borderWidth": {
      "$count": 56
    }
  },
  "visualMap-piecewise": {
    "$count": 755,
    "align: 'auto'": {
      "$count": 46
    },
    "itemSymbol": {
      "$count": 183
    },
    "itemGap = 10": {
      "$count": 48
    },
    "pieces": {
      "$count": 274
    },
    "splitNumber": {
      "$count": 216
    },
    "type": {
      "$count": 317
    },
    "inRange": {
      "$count": 154
    },
    "dimension": {
      "$count": 80
    },
    "categories": {
      "$count": 260
    },
    "seriesIndex": {
      "$count": 64
    },
    "color": {
      "$count": 81
    },
    "precision": {
      "$count": 72
    },
    "formatter": {
      "$count": 86
    },
    "textStyle": {
      "$count": 39,
      "color": {
        "$count": 13
      },
      "fontStyle": {
        "$count": 8
      },
      "fontWeight": {
        "$count": 8
      },
      "fontFamily": {
        "$count": 7
      },
      "fontSize": {
        "$count": 9
      }
    },
    "outOfRange": {
      "$count": 66
    },
    "itemWidth": {
      "$count": 51
    },
    "inverse": {
      "$count": 50
    },
    "selectedMode": {
      "$count": 120
    },
    "min": {
      "$count": 69
    },
    "backgroundColor": {
      "$count": 26
    },
    "left": {
      "$count": 23
    },
    "itemHeight": {
      "$count": 41
    },
    "max": {
      "$count": 43
    },
    "text": {
      "$count": 39
    },
    "textGap": {
      "$count": 40
    },
    "show": {
      "$count": 46
    },
    "zlevel": {
      "$count": 24
    },
    "z": {
      "$count": 13
    },
    "top": {
      "$count": 18
    },
    "right": {
      "$count": 18
    },
    "bottom": {
      "$count": 12
    },
    "orient": {
      "$count": 26
    },
    "padding": {
      "$count": 21
    },
    "borderColor": {
      "$count": 15
    },
    "borderWidth": {
      "$count": 16
    }
  },
  "toolbox": {
    "$count": 5744,
    "feature": {
      "dataView": {
        "$count": 561,
        "textareaColor = '#fff'": {
          "$count": 39
        },
        "iconStyle": {
          "$count": 78,
          "normal": {
            "$count": 33,
            "color": {
              "$count": 9
            },
            "shadowBlur": {
              "$count": 6
            },
            "borderColor": {
              "$count": 9
            },
            "shadowOffsetY": {
              "$count": 6
            },
            "shadowOffsetX": {
              "$count": 4
            },
            "opacity": {
              "$count": 5
            },
            "borderWidth": {
              "$count": 7
            },
            "shadowColor": {
              "$count": 2
            }
          },
          "emphasis": {
            "$count": 23,
            "color": {
              "$count": 2
            },
            "borderColor": {
              "$count": 4
            },
            "borderWidth": {
              "$count": 3
            },
            "shadowBlur": {
              "$count": 4
            },
            "shadowOffsetX": {
              "$count": 1
            },
            "shadowColor": {
              "$count": 2
            },
            "opacity": {
              "$count": 2
            },
            "shadowOffsetY": {
              "$count": 1
            }
          }
        },
        "icon": {
          "$count": 77
        },
        "readOnly": {
          "$count": 67
        },
        "show": {
          "$count": 63
        },
        "title": {
          "$count": 63
        },
        "lang": {
          "$count": 77
        },
        "backgroundColor = '#fff'": {
          "$count": 53
        },
        "textareaBorderColor = '#333'": {
          "$count": 29
        },
        "textColor = '#000'": {
          "$count": 32
        },
        "buttonColor = '#c23531'": {
          "$count": 33
        },
        "buttonTextColor = '#fff'": {
          "$count": 31
        }
      },
      "dataZoom": {
        "$count": 757,
        "title": {
          "$count": 55,
          "zoom": {
            "$count": 23
          },
          "back": {
            "$count": 14
          }
        },
        "show": {
          "$count": 76
        },
        "iconStyle": {
          "normal": {
            "$count": 20,
            "shadowBlur": {
              "$count": 1
            },
            "color": {
              "$count": 1
            },
            "borderColor": {
              "$count": 1
            }
          },
          "$count": 38,
          "emphasis": {
            "$count": 11,
            "color": {
              "$count": 1
            }
          }
        },
        "yAxisIndex": {
          "$count": 43
        },
        "xAxisIndex": {
          "$count": 75
        },
        "icon": {
          "$count": 33,
          "zoom": {
            "$count": 26
          },
          "back": {
            "$count": 15
          }
        }
      },
      "saveAsImage": {
        "type": {
          "$count": 121
        },
        "$count": 692,
        "backgroundColor": {
          "$count": 99
        },
        "excludeComponents": {
          "$count": 125
        },
        "show": {
          "$count": 97
        },
        "title": {
          "$count": 98
        },
        "icon": {
          "$count": 128
        },
        "iconStyle": {
          "normal": {
            "$count": 52,
            "color": {
              "$count": 19
            },
            "opacity": {
              "$count": 7
            },
            "shadowOffsetY": {
              "$count": 3
            },
            "shadowOffsetX": {
              "$count": 7
            },
            "shadowBlur": {
              "$count": 12
            },
            "shadowColor": {
              "$count": 11
            },
            "borderColor": {
              "$count": 14
            },
            "borderWidth": {
              "$count": 5
            }
          },
          "emphasis": {
            "$count": 61,
            "color": {
              "$count": 10
            },
            "shadowBlur": {
              "$count": 3
            },
            "opacity": {
              "$count": 4
            },
            "borderColor": {
              "$count": 4
            },
            "shadowOffsetX": {
              "$count": 2
            },
            "shadowColor": {
              "$count": 3
            },
            "shadowOffsetY": {
              "$count": 1
            },
            "borderWidth": {
              "$count": 1
            }
          },
          "$count": 87
        },
        "pixelRatio": {
          "$count": 9
        },
        "name": {
          "$count": 14
        }
      },
      "$count": 849,
      "magicType": {
        "option": {
          "bar": {
            "$count": 82
          },
          "stack": {
            "$count": 104
          },
          "$count": 153,
          "line": {
            "$count": 107
          },
          "tiled": {
            "$count": 27
          }
        },
        "seriesIndex": {
          "bar": {
            "$count": 37
          },
          "stack": {
            "$count": 63
          },
          "line": {
            "$count": 43
          },
          "$count": 62,
          "tiled": {
            "$count": 13
          }
        },
        "$count": 681,
        "type": {
          "$count": 200
        },
        "title": {
          "$count": 78,
          "stack": {
            "$count": 111
          },
          "bar": {
            "$count": 53
          },
          "line": {
            "$count": 50
          },
          "tiled": {
            "$count": 33
          }
        },
        "icon": {
          "bar": {
            "$count": 34
          },
          "$count": 62,
          "stack": {
            "$count": 59
          },
          "line": {
            "$count": 45
          },
          "tiled": {
            "$count": 13
          }
        },
        "show": {
          "$count": 82
        },
        "iconStyle": {
          "normal": {
            "$count": 14,
            "color": {
              "$count": 5
            },
            "opacity": {
              "$count": 1
            },
            "borderColor": {
              "$count": 2
            },
            "borderWidth": {
              "$count": 1
            }
          },
          "emphasis": {
            "shadowBlur": {
              "$count": 1
            },
            "$count": 9,
            "borderColor": {
              "$count": 1
            },
            "opacity": {
              "$count": 1
            }
          },
          "$count": 48
        }
      },
      "restore": {
        "$count": 383,
        "iconStyle": {
          "normal": {
            "borderColor": {
              "$count": 7
            },
            "$count": 33,
            "color": {
              "$count": 12
            },
            "shadowColor": {
              "$count": 4
            },
            "opacity": {
              "$count": 7
            },
            "shadowOffsetX": {
              "$count": 3
            },
            "shadowBlur": {
              "$count": 6
            },
            "borderWidth": {
              "$count": 4
            },
            "shadowOffsetY": {
              "$count": 3
            }
          },
          "$count": 24,
          "emphasis": {
            "shadowBlur": {
              "$count": 1
            },
            "$count": 20,
            "color": {
              "$count": 1
            },
            "borderColor": {
              "$count": 1
            }
          }
        },
        "show": {
          "$count": 35
        },
        "title": {
          "$count": 24
        },
        "icon": {
          "$count": 35
        }
      }
    },
    "bottom": {
      "$count": 96
    },
    "zlevel": {
      "$count": 107
    },
    "right": {
      "$count": 124
    },
    "left": {
      "$count": 137
    },
    "itemSize": {
      "$count": 274
    },
    "orient": {
      "$count": 439
    },
    "showTitle": {
      "$count": 270
    },
    "show": {
      "$count": 610
    },
    "itemGap": {
      "$count": 231
    },
    "iconStyle": {
      "$count": 308,
      "normal": {
        "$count": 115,
        "borderColor": {
          "$count": 27
        },
        "color": {
          "$count": 43
        },
        "borderWidth": {
          "$count": 14
        },
        "shadowBlur": {
          "$count": 12
        },
        "shadowColor": {
          "$count": 8
        },
        "shadowOffsetX": {
          "$count": 7
        },
        "opacity": {
          "$count": 12
        },
        "shadowOffsetY": {
          "$count": 6
        }
      },
      "emphasis": {
        "$count": 87,
        "color": {
          "$count": 18
        },
        "opacity": {
          "$count": 5
        },
        "shadowOffsetY": {
          "$count": 2
        },
        "shadowOffsetX": {
          "$count": 2
        },
        "shadowColor": {
          "$count": 5
        },
        "shadowBlur": {
          "$count": 3
        },
        "borderWidth": {
          "$count": 6
        },
        "borderColor": {
          "$count": 10
        }
      }
    },
    "z": {
      "$count": 71
    },
    "top": {
      "$count": 101
    },
    "height": {
      "$count": 17
    },
    "width": {
      "$count": 14
    }
  },
  "geo": {
    "$count": 4989,
    "roam": {
      "$count": 512
    },
    "map": {
      "$count": 924
    },
    "itemStyle": {
      "$count": 628,
      "zlevel": {
        "$count": 74
      },
      "emphasis": {
        "$count": 167,
        "borderColor": {
          "$count": 24
        },
        "borderWidth": {
          "$count": 18
        },
        "shadowColor": {
          "$count": 18
        },
        "color": {
          "$count": 50
        },
        "opacity": {
          "$count": 28
        },
        "shadowOffsetX": {
          "$count": 14
        },
        "shadowBlur": {
          "$count": 21
        },
        "shadowOffsetY": {
          "$count": 14
        }
      },
      "normal": {
        "$count": 251,
        "color": {
          "$count": 173
        },
        "borderColor": {
          "$count": 94
        },
        "borderWidth": {
          "$count": 68
        },
        "shadowColor": {
          "$count": 48
        },
        "shadowOffsetY": {
          "$count": 38
        },
        "opacity": {
          "$count": 76
        },
        "shadowBlur": {
          "$count": 62
        },
        "shadowOffsetX": {
          "$count": 44
        }
      },
      "left": {
        "$count": 77
      },
      "z": {
        "$count": 54
      },
      "bottom": {
        "$count": 38
      },
      "right": {
        "$count": 23
      },
      "top": {
        "$count": 36
      }
    },
    "label": {
      "$count": 492,
      "normal": {
        "show": {
          "$count": 123
        },
        "$count": 225,
        "textStyle": {
          "$count": 108,
          "color": {
            "$count": 42
          },
          "fontStyle": {
            "$count": 23
          },
          "fontSize": {
            "$count": 14
          },
          "fontWeight": {
            "$count": 17
          },
          "fontFamily": {
            "$count": 13
          }
        }
      },
      "emphasis": {
        "$count": 158,
        "show": {
          "$count": 68
        },
        "textStyle": {
          "$count": 44,
          "fontWeight": {
            "$count": 11
          },
          "color": {
            "$count": 23
          },
          "fontStyle": {
            "$count": 11
          },
          "fontFamily": {
            "$count": 12
          },
          "fontSize": {
            "$count": 10
          }
        }
      }
    },
    "show": {
      "$count": 531
    },
    "zlevel": {
      "$count": 12
    },
    "z": {
      "$count": 11
    },
    "top": {
      "$count": 8
    },
    "left": {
      "$count": 15
    },
    "right": {
      "$count": 9
    },
    "bottom": {
      "$count": 10
    }
  },
  "series-scatter": {
    "$count": 1828,
    "symbol": {
      "$count": 195
    },
    "itemStyle": {
      "$count": 141,
      "normal": {
        "$count": 48,
        "opacity": {
          "$count": 20
        },
        "color": {
          "$count": 34
        },
        "borderColor": {
          "$count": 22
        },
        "borderWidth": {
          "$count": 21
        },
        "shadowBlur": {
          "$count": 21
        },
        "shadowColor": {
          "$count": 13
        },
        "shadowOffsetX": {
          "$count": 10
        },
        "shadowOffsetY": {
          "$count": 7
        }
      },
      "emphasis": {
        "$count": 19,
        "color": {
          "$count": 4
        },
        "borderWidth": {
          "$count": 5
        },
        "shadowBlur": {
          "$count": 5
        },
        "shadowColor": {
          "$count": 5
        },
        "shadowOffsetY": {
          "$count": 1
        },
        "opacity": {
          "$count": 1
        },
        "borderColor": {
          "$count": 2
        }
      }
    },
    "animation": {
      "$count": 26
    },
    "markLine": {
      "$count": 139,
      "label": {
        "$count": 22,
        "normal": {
          "formatter": {
            "$count": 16
          },
          "position": {
            "$count": 6
          },
          "show": {
            "$count": 2
          },
          "$count": 11
        },
        "emphasis": {
          "$count": 7,
          "formatter": {
            "$count": 3
          }
        }
      },
      "lineStyle": {
        "$count": 30,
        "normal": {
          "$count": 13,
          "color": {
            "$count": 9
          },
          "width": {
            "$count": 3
          },
          "shadowColor": {
            "$count": 1
          },
          "opacity": {
            "$count": 3
          },
          "curveness": {
            "$count": 5
          },
          "type": {
            "$count": 9
          },
          "shadowBlur": {
            "$count": 2
          },
          "shadowOffsetX": {
            "$count": 1
          }
        },
        "emphasis": {
          "$count": 7,
          "color": {
            "$count": 1
          },
          "opacity": {
            "$count": 1
          },
          "type": {
            "$count": 1
          }
        }
      },
      "symbol": {
        "$count": 36
      },
      "data": {
        "0": {
          "type": {
            "$count": 28
          },
          "valueIndex": {
            "$count": 15
          },
          "lineStyle": {
            "$count": 9,
            "normal": {
              "color": {
                "$count": 1
              },
              "$count": 4,
              "curveness": {
                "$count": 1
              },
              "type": {
                "$count": 1
              }
            }
          },
          "$count": 32,
          "coord": {
            "$count": 26
          },
          "symbol": {
            "$count": 14
          },
          "value": {
            "$count": 10
          },
          "label": {
            "normal": {
              "$count": 3,
              "formatter": {
                "$count": 3
              },
              "show": {
                "$count": 2
              },
              "position": {
                "$count": 1
              }
            },
            "emphasis": {
              "formatter": {
                "$count": 1
              }
            },
            "$count": 4
          },
          "x": {
            "$count": 8
          },
          "y": {
            "$count": 3
          },
          "symbolSize": {
            "$count": 4
          },
          "symbolOffset": {
            "$count": 3
          },
          "symbolRotate": {
            "$count": 1
          }
        },
        "1": {
          "label": {
            "$count": 4
          },
          "$count": 12,
          "valueIndex": {
            "$count": 3
          },
          "type": {
            "$count": 6
          },
          "symbol": {
            "$count": 4
          },
          "coord": {
            "$count": 6
          },
          "y": {
            "$count": 2
          },
          "lineStyle": {
            "normal": {
              "$count": 3,
              "color": {
                "$count": 2
              },
              "type": {
                "$count": 4
              },
              "shadowBlur": {
                "$count": 1
              },
              "shadowOffsetX": {
                "$count": 1
              },
              "curveness": {
                "$count": 1
              },
              "shadowColor": {
                "$count": 1
              },
              "width": {
                "$count": 1
              }
            },
            "emphasis": {
              "$count": 3,
              "color": {
                "$count": 2
              },
              "shadowColor": {
                "$count": 1
              },
              "curveness": {
                "$count": 1
              },
              "shadowOffsetX": {
                "$count": 1
              },
              "type": {
                "$count": 2
              },
              "width": {
                "$count": 1
              }
            },
            "$count": 2
          },
          "value": {
            "$count": 1
          },
          "x": {
            "$count": 1
          },
          "symbolOffset": {
            "$count": 1
          }
        },
        "$count": 57
      },
      "animationEasing": {
        "$count": 3
      },
      "symbolSize": {
        "$count": 16
      },
      "precision": {
        "$count": 16
      },
      "animation": {
        "$count": 7
      },
      "animationDurationUpdate": {
        "$count": 1
      },
      "animationEasingUpdate": {
        "$count": 2
      }
    },
    "data": {
      "$count": 308,
      "value": {
        "$count": 129
      },
      "symbolSize": {
        "$count": 39
      },
      "symbol": {
        "$count": 70
      },
      "symbolRotate": {
        "$count": 28
      },
      "symbolOffset": {
        "$count": 30
      },
      "itemStyle": {
        "$count": 38,
        "normal": {
          "$count": 17,
          "color": {
            "$count": 11
          },
          "borderColor": {
            "$count": 4
          },
          "borderWidth": {
            "$count": 4
          },
          "shadowBlur": {
            "$count": 2
          },
          "shadowColor": {
            "$count": 1
          },
          "shadowOffsetX": {
            "$count": 1
          },
          "shadowOffsetY": {
            "$count": 1
          },
          "opacity": {
            "$count": 4
          }
        },
        "emphasis": {
          "color": {
            "$count": 1
          },
          "shadowColor": {
            "$count": 1
          },
          "shadowBlur": {
            "$count": 1
          },
          "$count": 12,
          "opacity": {
            "$count": 1
          }
        }
      },
      "label": {
        "$count": 46,
        "normal": {
          "$count": 13,
          "textStyle": {
            "$count": 4,
            "color": {
              "$count": 2
            },
            "fontWeight": {
              "$count": 1
            },
            "fontStyle": {
              "$count": 1
            }
          },
          "position": {
            "$count": 9
          },
          "show": {
            "$count": 2
          }
        },
        "emphasis": {
          "$count": 6,
          "position": {
            "$count": 2
          },
          "show": {
            "$count": 1
          }
        }
      },
      "name": {
        "$count": 104
      }
    },
    "large": {
      "$count": 85
    },
    "markPoint": {
      "$count": 173,
      "data": {
        "$count": 44,
        "valueIndex": {
          "$count": 24
        },
        "coord": {
          "$count": 26
        },
        "symbolRotate": {
          "$count": 2
        },
        "symbolSize": {
          "$count": 7
        },
        "symbol": {
          "$count": 13
        },
        "value": {
          "$count": 19
        },
        "y": {
          "$count": 8
        },
        "x": {
          "$count": 16
        },
        "name": {
          "$count": 16
        },
        "type": {
          "$count": 36
        },
        "label": {
          "$count": 5,
          "normal": {
            "$count": 3
          },
          "emphasis": {
            "$count": 1
          }
        },
        "itemStyle": {
          "normal": {
            "$count": 2,
            "color": {
              "$count": 1
            },
            "borderColor": {
              "$count": 1
            },
            "borderWidth": {
              "$count": 1
            },
            "shadowColor": {
              "$count": 1
            },
            "shadowBlur": {
              "$count": 1
            },
            "opacity": {
              "$count": 1
            }
          },
          "$count": 5
        },
        "symbolOffset": {
          "$count": 3
        },
        "valueDim": {
          "$count": 5
        }
      },
      "symbol": {
        "$count": 67
      },
      "itemStyle": {
        "normal": {
          "$count": 6,
          "color": {
            "$count": 7
          },
          "borderColor": {
            "$count": 2
          },
          "shadowColor": {
            "$count": 4
          },
          "shadowOffsetY": {
            "$count": 3
          },
          "shadowBlur": {
            "$count": 2
          },
          "opacity": {
            "$count": 2
          },
          "borderWidth": {
            "$count": 1
          },
          "shadowOffsetX": {
            "$count": 2
          }
        },
        "$count": 18,
        "emphasis": {
          "color": {
            "$count": 2
          },
          "borderColor": {
            "$count": 2
          },
          "shadowColor": {
            "$count": 2
          },
          "shadowBlur": {
            "$count": 3
          },
          "borderWidth": {
            "$count": 2
          },
          "$count": 1,
          "shadowOffsetY": {
            "$count": 2
          },
          "shadowOffsetX": {
            "$count": 1
          },
          "opacity": {
            "$count": 1
          }
        }
      },
      "animation": {
        "$count": 10
      },
      "animationDuration": {
        "$count": 4
      },
      "symbolSize": {
        "$count": 28
      },
      "label": {
        "$count": 29,
        "normal": {
          "$count": 7,
          "formatter": {
            "$count": 5
          },
          "position": {
            "$count": 4
          },
          "textStyle": {
            "color": {
              "$count": 2
            },
            "$count": 1
          },
          "show": {
            "$count": 1
          }
        },
        "emphasis": {
          "$count": 3
        }
      },
      "animationEasing": {
        "$count": 4
      },
      "symbolOffset": {
        "$count": 11
      },
      "symbolRotate": {
        "$count": 11
      },
      "animationDurationUpdate": {
        "$count": 1
      },
      "animationEasingUpdate": {
        "$count": 1
      }
    },
    "symbolSize": {
      "$count": 180
    },
    "xAxisIndex": {
      "$count": 105
    },
    "polarIndex": {
      "$count": 51
    },
    "type": {
      "$count": 266
    },
    "label": {
      "normal": {
        "formatter": {
          "$count": 72
        },
        "show": {
          "$count": 20
        },
        "position": {
          "$count": 36
        },
        "$count": 49,
        "textStyle": {
          "color": {
            "$count": 3
          },
          "$count": 20,
          "fontStyle": {
            "$count": 4
          },
          "fontWeight": {
            "$count": 3
          },
          "fontFamily": {
            "$count": 1
          },
          "fontSize": {
            "$count": 2
          }
        }
      },
      "$count": 137,
      "emphasis": {
        "$count": 34,
        "textStyle": {
          "color": {
            "$count": 5
          },
          "$count": 3,
          "fontStyle": {
            "$count": 3
          },
          "fontFamily": {
            "$count": 3
          },
          "fontSize": {
            "$count": 3
          },
          "fontWeight": {
            "$count": 2
          }
        },
        "formatter": {
          "$count": 12
        },
        "position": {
          "$count": 7
        },
        "show": {
          "$count": 4
        }
      }
    },
    "geoIndex": {
      "$count": 84
    },
    "coordinateSystem": {
      "$count": 186
    },
    "symbolRotate": {
      "$count": 77
    },
    "symbolOffset": {
      "$count": 61
    },
    "name": {
      "$count": 103
    },
    "yAxisIndex": {
      "$count": 46
    },
    "hoverAnimation": {
      "$count": 100
    },
    "legendHoverLink": {
      "$count": 78
    },
    "largeThreshold": {
      "$count": 63
    },
    "animationEasing": {
      "$count": 11
    },
    "animationDuration": {
      "$count": 14
    },
    "animationDurationUpdate": {
      "$count": 15
    },
    "animationEasingUpdate": {
      "$count": 12
    },
    "zlevel": {
      "$count": 1
    },
    "z": {
      "$count": 1
    }
  },
  "title": {
    "$count": 6280,
    "show": {
      "$count": 1911
    },
    "text": {
      "$count": 1510
    },
    "link": {
      "$count": 964
    },
    "target": {
      "$count": 882
    },
    "bottom": {
      "$count": 464
    },
    "backgroundColor": {
      "$count": 511
    },
    "borderColor": {
      "$count": 370
    },
    "borderWidth": {
      "$count": 297
    },
    "top": {
      "$count": 600
    },
    "subtextStyle": {
      "$count": 780,
      "color": {
        "$count": 206
      },
      "fontStyle": {
        "$count": 109
      },
      "fontWeight": {
        "$count": 80
      },
      "fontFamily": {
        "$count": 83
      },
      "fontSize": {
        "$count": 76
      }
    },
    "textStyle": {
      "$count": 1560,
      "color": {
        "$count": 540
      },
      "fontWeight": {
        "$count": 380
      },
      "fontFamily": {
        "$count": 317
      },
      "fontSize": {
        "$count": 375
      },
      "fontStyle": {
        "$count": 420
      }
    },
    "itemGap": {
      "$count": 597
    },
    "padding": {
      "$count": 790
    },
    "subtarget": {
      "$count": 469
    },
    "sublink": {
      "$count": 484
    },
    "subtext": {
      "$count": 882
    },
    "zlevel": {
      "$count": 473
    },
    "left": {
      "$count": 1025
    },
    "shadowOffsetX": {
      "$count": 290
    },
    "shadowOffsetY": {
      "$count": 215
    },
    "shadowBlur": {
      "$count": 377
    },
    "shadowColor": {
      "$count": 332
    },
    "z": {
      "$count": 419
    },
    "right": {
      "$count": 369
    }
  },
  "grid": {
    "$count": 12086,
    "show": {
      "$count": 1631
    },
    "left": {
      "$count": 914
    },
    "borderWidth": {
      "$count": 541
    },
    "zlevel": {
      "$count": 721
    },
    "z": {
      "$count": 535
    },
    "top": {
      "$count": 710
    },
    "right": {
      "$count": 512
    },
    "bottom": {
      "$count": 491
    },
    "height": {
      "$count": 497
    },
    "width": {
      "$count": 735
    },
    "backgroundColor": {
      "$count": 768
    },
    "shadowColor": {
      "$count": 384
    },
    "borderColor": {
      "$count": 690
    },
    "containLabel": {
      "$count": 1072
    },
    "shadowOffsetX": {
      "$count": 362
    },
    "shadowOffsetY": {
      "$count": 281
    },
    "shadowBlur": {
      "$count": 426
    }
  },
  "polar": {
    "$count": 6459,
    "zlevel": {
      "$count": 340
    },
    "radius": {
      "$count": 418
    },
    "z": {
      "$count": 187
    },
    "center": {
      "$count": 334
    }
  },
  "angleAxis": {
    "$count": 4074,
    "startAngle": {
      "$count": 75
    },
    "type": {
      "$count": 70
    },
    "data": {
      "$count": 50,
      "value": {
        "$count": 17
      },
      "textStyle": {
        "$count": 9,
        "baseline": {
          "$count": 6
        },
        "color": {
          "$count": 3
        },
        "fontWeight": {
          "$count": 1
        }
      }
    },
    "axisLabel": {
      "formatter": {
        "$count": 53
      },
      "interval": {
        "$count": 5
      },
      "textStyle": {
        "$count": 8,
        "color": {
          "$count": 2
        },
        "fontSize": {
          "$count": 1
        }
      },
      "$count": 41,
      "margin": {
        "$count": 7
      },
      "show": {
        "$count": 4
      },
      "inside": {
        "$count": 4
      }
    },
    "axisLine": {
      "lineStyle": {
        "color": {
          "$count": 11
        },
        "shadowColor": {
          "$count": 4
        },
        "$count": 14,
        "width": {
          "$count": 5
        },
        "type": {
          "$count": 5
        },
        "shadowBlur": {
          "$count": 6
        },
        "shadowOffsetX": {
          "$count": 1
        },
        "shadowOffsetY": {
          "$count": 2
        },
        "opacity": {
          "$count": 2
        }
      },
      "$count": 56,
      "show": {
        "$count": 13
      }
    },
    "axisTick": {
      "lineStyle": {
        "color": {
          "$count": 2
        },
        "shadowColor": {
          "$count": 1
        },
        "$count": 7,
        "type": {
          "$count": 1
        }
      },
      "$count": 31,
      "show": {
        "$count": 9
      },
      "interval": {
        "$count": 3
      },
      "inside": {
        "$count": 3
      },
      "length": {
        "$count": 1
      }
    },
    "polarIndex": {
      "$count": 77
    },
    "clockwise": {
      "$count": 44
    },
    "splitArea": {
      "areaStyle": {
        "$count": 19,
        "color": {
          "$count": 14
        },
        "shadowBlur": {
          "$count": 3
        },
        "shadowColor": {
          "$count": 4
        },
        "shadowOffsetX": {
          "$count": 1
        },
        "shadowOffsetY": {
          "$count": 1
        },
        "opacity": {
          "$count": 2
        }
      },
      "$count": 31,
      "interval": {
        "$count": 6
      },
      "show": {
        "$count": 4
      }
    },
    "splitLine": {
      "$count": 35,
      "lineStyle": {
        "type": {
          "$count": 1
        },
        "shadowColor": {
          "$count": 1
        },
        "$count": 7,
        "shadowBlur": {
          "$count": 2
        },
        "color": {
          "$count": 1
        },
        "opacity": {
          "$count": 1
        }
      },
      "show": {
        "$count": 3
      },
      "interval": {
        "$count": 6
      }
    },
    "boundaryGap": {
      "$count": 50
    },
    "min": {
      "$count": 39
    },
    "scale": {
      "$count": 32
    },
    "interval": {
      "$count": 39
    },
    "max": {
      "$count": 28
    },
    "splitNumber": {
      "$count": 38
    }
  },
  "series-line": {
    "$count": 4196,
    "xAxisIndex": {
      "$count": 679
    },
    "symbol": {
      "$count": 1352
    },
    "smooth": {
      "$count": 544
    },
    "showAllSymbol": {
      "$count": 474
    },
    "symbolSize": {
      "$count": 799
    },
    "yAxisIndex": {
      "$count": 476
    },
    "coordinateSystem": {
      "$count": 955
    },
    "itemStyle": {
      "$count": 1086,
      "normal": {
        "$count": 450,
        "borderWidth": {
          "$count": 136
        },
        "color": {
          "$count": 335
        },
        "borderColor": {
          "$count": 161
        },
        "shadowBlur": {
          "$count": 80
        },
        "shadowColor": {
          "$count": 59
        },
        "opacity": {
          "$count": 114
        },
        "shadowOffsetX": {
          "$count": 49
        },
        "shadowOffsetY": {
          "$count": 42
        }
      },
      "emphasis": {
        "opacity": {
          "$count": 20
        },
        "$count": 217,
        "color": {
          "$count": 46
        },
        "borderColor": {
          "$count": 23
        },
        "borderWidth": {
          "$count": 24
        },
        "shadowBlur": {
          "$count": 19
        },
        "shadowColor": {
          "$count": 19
        },
        "shadowOffsetY": {
          "$count": 16
        },
        "shadowOffsetX": {
          "$count": 18
        }
      }
    },
    "data": {
      "symbol": {
        "$count": 282
      },
      "label": {
        "$count": 229,
        "emphasis": {
          "$count": 49,
          "position": {
            "$count": 9
          },
          "show": {
            "$count": 10
          },
          "textStyle": {
            "$count": 6,
            "color": {
              "$count": 5
            },
            "fontStyle": {
              "$count": 3
            },
            "fontWeight": {
              "$count": 2
            },
            "fontFamily": {
              "$count": 1
            },
            "fontSize": {
              "$count": 1
            }
          }
        },
        "normal": {
          "$count": 109,
          "position": {
            "$count": 66
          },
          "show": {
            "$count": 49
          },
          "textStyle": {
            "$count": 45,
            "color": {
              "$count": 22
            },
            "fontStyle": {
              "$count": 10
            },
            "fontWeight": {
              "$count": 11
            },
            "fontFamily": {
              "$count": 9
            },
            "fontSize": {
              "$count": 11
            }
          }
        }
      },
      "symbolSize": {
        "$count": 181
      },
      "value": {
        "$count": 498
      },
      "$count": 1065,
      "symbolOffset": {
        "$count": 114
      },
      "symbolRotate": {
        "$count": 112
      },
      "itemStyle": {
        "$count": 213,
        "emphasis": {
          "barBorderColor": {
            "$count": 4
          },
          "$count": 50,
          "color": {
            "$count": 14
          },
          "barBorderWidth": {
            "$count": 2
          },
          "opacity": {
            "$count": 3
          },
          "shadowOffsetX": {
            "$count": 2
          },
          "shadowColor": {
            "$count": 1
          }
        },
        "normal": {
          "color": {
            "$count": 66
          },
          "$count": 95,
          "barBorderColor": {
            "$count": 40
          },
          "barBorderWidth": {
            "$count": 24
          },
          "opacity": {
            "$count": 16
          },
          "shadowColor": {
            "$count": 12
          },
          "shadowBlur": {
            "$count": 12
          },
          "shadowOffsetY": {
            "$count": 7
          },
          "shadowOffsetX": {
            "$count": 8
          }
        }
      }
    },
    "markLine": {
      "$count": 1082,
      "symbol": {
        "$count": 357
      },
      "data": {
        "0": {
          "x": {
            "$count": 72
          },
          "$count": 166,
          "type": {
            "$count": 156
          },
          "label": {
            "emphasis": {
              "formatter": {
                "$count": 6
              },
              "$count": 5
            },
            "normal": {
              "$count": 11,
              "formatter": {
                "$count": 22
              },
              "position": {
                "$count": 9
              },
              "show": {
                "$count": 3
              }
            },
            "$count": 34
          },
          "coord": {
            "$count": 156
          },
          "valueIndex": {
            "$count": 109
          },
          "symbol": {
            "$count": 75
          },
          "symbolOffset": {
            "$count": 18
          },
          "value": {
            "$count": 95
          },
          "lineStyle": {
            "emphasis": {
              "$count": 10,
              "type": {
                "$count": 2
              },
              "shadowBlur": {
                "$count": 2
              },
              "color": {
                "$count": 2
              },
              "curveness": {
                "$count": 3
              },
              "opacity": {
                "$count": 2
              },
              "shadowOffsetY": {
                "$count": 2
              },
              "width": {
                "$count": 1
              },
              "shadowColor": {
                "$count": 1
              },
              "shadowOffsetX": {
                "$count": 1
              }
            },
            "$count": 40,
            "normal": {
              "$count": 19,
              "color": {
                "$count": 10
              },
              "width": {
                "$count": 6
              },
              "shadowOffsetX": {
                "$count": 2
              },
              "curveness": {
                "$count": 6
              },
              "type": {
                "$count": 4
              },
              "shadowBlur": {
                "$count": 1
              }
            }
          },
          "y": {
            "$count": 39
          },
          "symbolSize": {
            "$count": 30
          },
          "symbolRotate": {
            "$count": 21
          },
          "valueDim": {
            "$count": 6
          }
        },
        "1": {
          "$count": 75,
          "label": {
            "normal": {
              "formatter": {
                "$count": 6
              },
              "$count": 6,
              "position": {
                "$count": 4
              },
              "show": {
                "$count": 2
              }
            },
            "$count": 3,
            "emphasis": {
              "formatter": {
                "$count": 1
              },
              "show": {
                "$count": 1
              },
              "$count": 3,
              "position": {
                "$count": 1
              }
            }
          },
          "type": {
            "$count": 27
          },
          "valueIndex": {
            "$count": 12
          },
          "x": {
            "$count": 13
          },
          "y": {
            "$count": 10
          },
          "value": {
            "$count": 16
          },
          "coord": {
            "$count": 17
          },
          "lineStyle": {
            "normal": {
              "curveness": {
                "$count": 1
              },
              "$count": 3,
              "width": {
                "$count": 2
              }
            },
            "emphasis": {
              "$count": 3
            },
            "$count": 7
          },
          "symbol": {
            "$count": 12
          },
          "symbolRotate": {
            "$count": 2
          },
          "symbolSize": {
            "$count": 4
          },
          "symbolOffset": {
            "$count": 1
          },
          "valueDim": {
            "$count": 2
          }
        },
        "$count": 397
      },
      "lineStyle": {
        "$count": 220,
        "normal": {
          "$count": 88,
          "type": {
            "$count": 39
          },
          "color": {
            "$count": 52
          },
          "width": {
            "$count": 20
          },
          "shadowBlur": {
            "$count": 17
          },
          "curveness": {
            "$count": 32
          },
          "shadowColor": {
            "$count": 10
          },
          "shadowOffsetX": {
            "$count": 6
          },
          "opacity": {
            "$count": 13
          },
          "shadowOffsetY": {
            "$count": 4
          }
        },
        "emphasis": {
          "$count": 55,
          "opacity": {
            "$count": 7
          },
          "shadowBlur": {
            "$count": 7
          },
          "shadowColor": {
            "$count": 4
          },
          "shadowOffsetX": {
            "$count": 4
          },
          "shadowOffsetY": {
            "$count": 3
          },
          "color": {
            "$count": 8
          },
          "type": {
            "$count": 5
          },
          "width": {
            "$count": 4
          }
        }
      },
      "animation": {
        "$count": 46
      },
      "animationDuration": {
        "$count": 13
      },
      "animationEasingUpdate": {
        "$count": 11
      },
      "label": {
        "$count": 172,
        "normal": {
          "formatter": {
            "$count": 75
          },
          "$count": 72,
          "position": {
            "$count": 47
          },
          "show": {
            "$count": 27
          }
        },
        "emphasis": {
          "formatter": {
            "$count": 23
          },
          "$count": 45,
          "position": {
            "$count": 17
          },
          "show": {
            "$count": 17
          }
        }
      },
      "symbolSize": {
        "$count": 179
      },
      "animationEasing": {
        "$count": 13
      },
      "animationDurationUpdate": {
        "$count": 10
      },
      "precision": {
        "$count": 128
      }
    },
    "label": {
      "emphasis": {
        "$count": 219,
        "formatter": {
          "$count": 61
        },
        "position": {
          "$count": 50
        },
        "show": {
          "$count": 46
        },
        "textStyle": {
          "$count": 26,
          "fontStyle": {
            "$count": 3
          },
          "fontWeight": {
            "$count": 3
          },
          "fontFamily": {
            "$count": 3
          },
          "fontSize": {
            "$count": 4
          },
          "color": {
            "$count": 8
          }
        }
      },
      "normal": {
        "show": {
          "$count": 211
        },
        "position": {
          "$count": 314
        },
        "$count": 418,
        "formatter": {
          "$count": 458
        },
        "textStyle": {
          "$count": 190,
          "fontStyle": {
            "$count": 39
          },
          "fontSize": {
            "$count": 38
          },
          "fontFamily": {
            "$count": 23
          },
          "color": {
            "$count": 62
          },
          "fontWeight": {
            "$count": 25
          }
        }
      },
      "$count": 894
    },
    "areaStyle": {
      "$count": 889,
      "emphasis": {
        "$count": 140,
        "color": {
          "$count": 22
        },
        "opacity": {
          "$count": 16
        },
        "shadowColor": {
          "$count": 7
        },
        "shadowOffsetX": {
          "$count": 8
        },
        "shadowOffsetY": {
          "$count": 7
        },
        "shadowBlur": {
          "$count": 12
        }
      },
      "normal": {
        "color": {
          "$count": 247
        },
        "$count": 307,
        "shadowBlur": {
          "$count": 107
        },
        "shadowColor": {
          "$count": 68
        },
        "opacity": {
          "$count": 115
        },
        "shadowOffsetY": {
          "$count": 46
        },
        "shadowOffsetX": {
          "$count": 43
        }
      }
    },
    "markPoint": {
      "symbol": {
        "$count": 389
      },
      "$count": 1083,
      "symbolSize": {
        "$count": 231
      },
      "data": {
        "$count": 316,
        "coord": {
          "$count": 133
        },
        "symbol": {
          "$count": 84
        },
        "x": {
          "$count": 70
        },
        "value": {
          "$count": 121
        },
        "valueIndex": {
          "$count": 120
        },
        "type": {
          "$count": 182
        },
        "label": {
          "$count": 65,
          "normal": {
            "$count": 40,
            "show": {
              "$count": 19
            },
            "position": {
              "$count": 24
            },
            "textStyle": {
              "$count": 13,
              "color": {
                "$count": 9
              },
              "fontStyle": {
                "$count": 2
              },
              "fontWeight": {
                "$count": 1
              },
              "fontFamily": {
                "$count": 1
              },
              "fontSize": {
                "$count": 8
              }
            }
          },
          "emphasis": {
            "$count": 18,
            "show": {
              "$count": 3
            },
            "position": {
              "$count": 1
            },
            "textStyle": {
              "color": {
                "$count": 1
              }
            }
          }
        },
        "name": {
          "$count": 123
        },
        "y": {
          "$count": 36
        },
        "symbolOffset": {
          "$count": 33
        },
        "symbolSize": {
          "$count": 54
        },
        "symbolRotate": {
          "$count": 31
        },
        "itemStyle": {
          "normal": {
            "color": {
              "$count": 23
            },
            "$count": 25,
            "shadowBlur": {
              "$count": 5
            },
            "borderWidth": {
              "$count": 8
            },
            "shadowColor": {
              "$count": 2
            },
            "shadowOffsetX": {
              "$count": 3
            },
            "shadowOffsetY": {
              "$count": 3
            },
            "opacity": {
              "$count": 7
            },
            "borderColor": {
              "$count": 8
            }
          },
          "$count": 47,
          "emphasis": {
            "color": {
              "$count": 2
            },
            "borderColor": {
              "$count": 1
            },
            "$count": 6
          }
        },
        "valueDim": {
          "$count": 10
        }
      },
      "symbolRotate": {
        "$count": 111
      },
      "symbolOffset": {
        "$count": 104
      },
      "label": {
        "normal": {
          "formatter": {
            "$count": 111
          },
          "show": {
            "$count": 45
          },
          "$count": 97,
          "textStyle": {
            "$count": 32,
            "fontSize": {
              "$count": 10
            },
            "fontStyle": {
              "$count": 7
            },
            "fontWeight": {
              "$count": 3
            },
            "color": {
              "$count": 10
            },
            "fontFamily": {
              "$count": 1
            }
          },
          "position": {
            "$count": 52
          }
        },
        "emphasis": {
          "formatter": {
            "$count": 16
          },
          "$count": 39,
          "position": {
            "$count": 10
          },
          "show": {
            "$count": 6
          },
          "textStyle": {
            "$count": 4,
            "fontStyle": {
              "$count": 2
            },
            "color": {
              "$count": 1
            },
            "fontWeight": {
              "$count": 2
            },
            "fontFamily": {
              "$count": 2
            },
            "fontSize": {
              "$count": 1
            }
          }
        },
        "$count": 205
      },
      "itemStyle": {
        "$count": 170,
        "normal": {
          "borderWidth": {
            "$count": 15
          },
          "borderColor": {
            "$count": 24
          },
          "$count": 59,
          "opacity": {
            "$count": 13
          },
          "shadowBlur": {
            "$count": 11
          },
          "color": {
            "$count": 44
          },
          "shadowColor": {
            "$count": 4
          },
          "shadowOffsetX": {
            "$count": 5
          },
          "shadowOffsetY": {
            "$count": 2
          }
        },
        "emphasis": {
          "$count": 24,
          "color": {
            "$count": 5
          },
          "borderColor": {
            "$count": 1
          }
        }
      },
      "animation": {
        "$count": 39
      },
      "animationDuration": {
        "$count": 18
      },
      "animationEasingUpdate": {
        "$count": 14
      },
      "animationDurationUpdate": {
        "$count": 14
      },
      "animationEasing": {
        "$count": 17
      }
    },
    "showSymbol": {
      "$count": 631
    },
    "stack": {
      "$count": 999
    },
    "type": {
      "$count": 1490
    },
    "hoverAnimation": {
      "$count": 572
    },
    "symbolRotate": {
      "$count": 489
    },
    "lineStyle": {
      "$count": 1084,
      "normal": {
        "$count": 458,
        "width": {
          "$count": 152
        },
        "type": {
          "$count": 154
        },
        "opacity": {
          "$count": 82
        },
        "color": {
          "$count": 290
        },
        "shadowBlur": {
          "$count": 75
        },
        "shadowColor": {
          "$count": 48
        },
        "shadowOffsetX": {
          "$count": 33
        },
        "shadowOffsetY": {
          "$count": 26
        }
      },
      "emphasis": {
        "$count": 233,
        "type": {
          "$count": 20
        },
        "color": {
          "$count": 37
        },
        "shadowBlur": {
          "$count": 10
        },
        "opacity": {
          "$count": 10
        },
        "shadowOffsetY": {
          "$count": 5
        },
        "shadowColor": {
          "$count": 5
        },
        "width": {
          "$count": 11
        },
        "shadowOffsetX": {
          "$count": 4
        }
      }
    },
    "symbolOffset": {
      "$count": 445
    },
    "clipOverflow": {
      "$count": 523
    },
    "name": {
      "$count": 875
    },
    "polarIndex": {
      "$count": 486
    },
    "legendHoverLink": {
      "$count": 506
    },
    "animation": {
      "$count": 167
    },
    "animationEasing": {
      "$count": 79
    },
    "animationEasingUpdate": {
      "$count": 70
    },
    "animationDurationUpdate": {
      "$count": 56
    },
    "animationDuration": {
      "$count": 85
    },
    "smoothMonotone": {
      "$count": 34
    },
    "zlevel": {
      "$count": 18
    },
    "z": {
      "$count": 16
    }
  },
  "animation": {
    "$count": 2869
  },
  "animationDuration": {
    "$count": 2312
  },
  "animationEasing": {
    "$count": 2041
  },
  "animationEasingUpdate": {
    "$count": 1715
  },
  "animationDurationUpdate": {
    "$count": 1821
  },
  "color": {
    "$count": 5879
  },
  "series": {
    "$count": 11427
  },
  "series-bar": {
    "itemStyle": {
      "normal": {
        "opacity": {
          "$count": 204
        },
        "$count": 636,
        "color": {
          "$count": 613
        },
        "shadowBlur": {
          "$count": 160
        },
        "shadowOffsetY": {
          "$count": 112
        },
        "shadowOffsetX": {
          "$count": 110
        },
        "shadowColor": {
          "$count": 143
        },
        "barBorderWidth": {
          "$count": 211
        },
        "barBorderColor": {
          "$count": 274
        },
        "barBorderRadius": {
          "$count": 38
        }
      },
      "$count": 1093,
      "emphasis": {
        "$count": 280,
        "opacity": {
          "$count": 32
        },
        "shadowOffsetX": {
          "$count": 13
        },
        "shadowOffsetY": {
          "$count": 16
        },
        "shadowColor": {
          "$count": 16
        },
        "shadowBlur": {
          "$count": 14
        },
        "barBorderWidth": {
          "$count": 24
        },
        "barBorderColor": {
          "$count": 26
        },
        "color": {
          "$count": 83
        }
      }
    },
    "label": {
      "emphasis": {
        "$count": 209,
        "show": {
          "$count": 32
        },
        "position": {
          "$count": 36
        },
        "formatter": {
          "$count": 54
        },
        "textStyle": {
          "$count": 22,
          "color": {
            "$count": 8
          },
          "fontStyle": {
            "$count": 4
          },
          "fontWeight": {
            "$count": 2
          },
          "fontFamily": {
            "$count": 3
          },
          "fontSize": {
            "$count": 3
          }
        }
      },
      "normal": {
        "formatter": {
          "$count": 458
        },
        "textStyle": {
          "fontStyle": {
            "$count": 28
          },
          "fontFamily": {
            "$count": 19
          },
          "fontSize": {
            "$count": 41
          },
          "color": {
            "$count": 62
          },
          "$count": 186,
          "fontWeight": {
            "$count": 25
          }
        },
        "position": {
          "$count": 445
        },
        "$count": 413,
        "show": {
          "$count": 220
        }
      },
      "$count": 864
    },
    "coordinateSystem": {
      "$count": 494
    },
    "barGap": {
      "$count": 528
    },
    "barCategoryGap": {
      "$count": 400
    },
    "barMaxWidth": {
      "$count": 365
    },
    "data": {
      "label": {
        "$count": 287,
        "normal": {
          "$count": 158,
          "show": {
            "$count": 71
          },
          "position": {
            "$count": 86
          },
          "textStyle": {
            "$count": 73,
            "color": {
              "$count": 38
            },
            "fontSize": {
              "$count": 27
            },
            "fontStyle": {
              "$count": 21
            },
            "fontWeight": {
              "$count": 17
            },
            "fontFamily": {
              "$count": 20
            }
          }
        },
        "emphasis": {
          "$count": 60,
          "position": {
            "$count": 27
          },
          "show": {
            "$count": 28
          },
          "textStyle": {
            "color": {
              "$count": 9
            },
            "$count": 14,
            "fontStyle": {
              "$count": 4
            },
            "fontWeight": {
              "$count": 5
            },
            "fontFamily": {
              "$count": 4
            },
            "fontSize": {
              "$count": 2
            }
          }
        }
      },
      "$count": 644,
      "value": {
        "$count": 411
      },
      "itemStyle": {
        "normal": {
          "barBorderColor": {
            "$count": 58
          },
          "color": {
            "$count": 134
          },
          "barBorderWidth": {
            "$count": 37
          },
          "shadowBlur": {
            "$count": 34
          },
          "shadowOffsetX": {
            "$count": 23
          },
          "$count": 160,
          "shadowColor": {
            "$count": 25
          },
          "opacity": {
            "$count": 37
          },
          "shadowOffsetY": {
            "$count": 18
          },
          "barBorderRadius": {
            "$count": 1
          }
        },
        "$count": 283,
        "emphasis": {
          "$count": 67,
          "color": {
            "$count": 24
          },
          "shadowColor": {
            "$count": 8
          },
          "opacity": {
            "$count": 12
          },
          "shadowOffsetY": {
            "$count": 5
          },
          "shadowOffsetX": {
            "$count": 3
          },
          "shadowBlur": {
            "$count": 8
          },
          "barBorderWidth": {
            "$count": 7
          },
          "barBorderColor": {
            "$count": 11
          }
        }
      }
    },
    "markLine": {
      "$count": 550,
      "data": {
        "0": {
          "type": {
            "$count": 70
          },
          "$count": 107,
          "valueIndex": {
            "$count": 46
          },
          "coord": {
            "$count": 63
          },
          "x": {
            "$count": 45
          },
          "lineStyle": {
            "normal": {
              "color": {
                "$count": 5
              },
              "type": {
                "$count": 13
              },
              "width": {
                "$count": 2
              },
              "shadowBlur": {
                "$count": 4
              },
              "$count": 4,
              "shadowColor": {
                "$count": 1
              },
              "shadowOffsetX": {
                "$count": 2
              },
              "shadowOffsetY": {
                "$count": 1
              },
              "curveness": {
                "$count": 1
              },
              "opacity": {
                "$count": 1
              }
            },
            "$count": 24,
            "emphasis": {
              "shadowBlur": {
                "$count": 1
              },
              "$count": 2,
              "color": {
                "$count": 1
              }
            }
          },
          "label": {
            "$count": 23,
            "normal": {
              "formatter": {
                "$count": 15
              },
              "position": {
                "$count": 10
              },
              "$count": 7,
              "show": {
                "$count": 3
              }
            },
            "emphasis": {
              "formatter": {
                "$count": 2
              },
              "position": {
                "$count": 1
              },
              "$count": 1,
              "show": {
                "$count": 1
              }
            }
          },
          "y": {
            "$count": 24
          },
          "value": {
            "$count": 41
          },
          "symbol": {
            "$count": 56
          },
          "symbolSize": {
            "$count": 24
          },
          "symbolOffset": {
            "$count": 21
          },
          "symbolRotate": {
            "$count": 16
          },
          "valueDim": {
            "$count": 5
          }
        },
        "1": {
          "$count": 41,
          "symbolSize": {
            "$count": 1
          },
          "lineStyle": {
            "normal": {
              "shadowBlur": {
                "$count": 1
              },
              "width": {
                "$count": 1
              },
              "$count": 1
            },
            "emphasis": {
              "shadowBlur": {
                "$count": 1
              },
              "width": {
                "$count": 1
              }
            },
            "$count": 1
          },
          "type": {
            "$count": 5
          },
          "symbol": {
            "$count": 4
          },
          "label": {
            "normal": {
              "formatter": {
                "$count": 2
              }
            },
            "emphasis": {
              "formatter": {
                "$count": 1
              },
              "show": {
                "$count": 1
              }
            }
          },
          "valueIndex": {
            "$count": 2
          },
          "x": {
            "$count": 6
          },
          "y": {
            "$count": 2
          },
          "value": {
            "$count": 2
          },
          "coord": {
            "$count": 3
          }
        },
        "$count": 178
      },
      "lineStyle": {
        "$count": 107,
        "normal": {
          "shadowColor": {
            "$count": 7
          },
          "shadowBlur": {
            "$count": 10
          },
          "shadowOffsetX": {
            "$count": 6
          },
          "opacity": {
            "$count": 13
          },
          "curveness": {
            "$count": 12
          },
          "color": {
            "$count": 25
          },
          "width": {
            "$count": 18
          },
          "type": {
            "$count": 31
          },
          "$count": 40,
          "shadowOffsetY": {
            "$count": 3
          }
        },
        "emphasis": {
          "$count": 26,
          "shadowBlur": {
            "$count": 7
          },
          "width": {
            "$count": 3
          },
          "shadowOffsetX": {
            "$count": 5
          },
          "shadowOffsetY": {
            "$count": 3
          },
          "type": {
            "$count": 8
          },
          "color": {
            "$count": 3
          },
          "opacity": {
            "$count": 3
          },
          "shadowColor": {
            "$count": 3
          }
        }
      },
      "label": {
        "normal": {
          "position": {
            "$count": 36
          },
          "formatter": {
            "$count": 32
          },
          "$count": 41,
          "show": {
            "$count": 27
          }
        },
        "$count": 92,
        "emphasis": {
          "$count": 19,
          "show": {
            "$count": 3
          },
          "position": {
            "$count": 3
          },
          "formatter": {
            "$count": 6
          }
        }
      },
      "symbol": {
        "$count": 141
      },
      "symbolSize": {
        "$count": 70
      },
      "precision": {
        "$count": 36
      },
      "animationEasingUpdate": {
        "$count": 8
      },
      "animation": {
        "$count": 15
      },
      "animationDuration": {
        "$count": 8
      },
      "animationDurationUpdate": {
        "$count": 6
      },
      "animationEasing": {
        "$count": 5
      }
    },
    "$count": 3196,
    "barWidth": {
      "$count": 693
    },
    "type": {
      "$count": 590
    },
    "legendHoverLink": {
      "$count": 484
    },
    "name": {
      "$count": 420
    },
    "barMinHeight": {
      "$count": 261
    },
    "markPoint": {
      "itemStyle": {
        "$count": 79,
        "normal": {
          "$count": 32,
          "borderColor": {
            "$count": 14
          },
          "borderWidth": {
            "$count": 5
          },
          "color": {
            "$count": 23
          },
          "shadowBlur": {
            "$count": 3
          },
          "opacity": {
            "$count": 7
          },
          "shadowOffsetY": {
            "$count": 2
          },
          "shadowOffsetX": {
            "$count": 1
          },
          "shadowColor": {
            "$count": 2
          }
        },
        "emphasis": {
          "color": {
            "$count": 4
          },
          "shadowBlur": {
            "$count": 1
          },
          "$count": 10
        }
      },
      "data": {
        "type": {
          "$count": 112
        },
        "$count": 125,
        "value": {
          "$count": 63
        },
        "name": {
          "$count": 69
        },
        "symbolSize": {
          "$count": 27
        },
        "valueIndex": {
          "$count": 71
        },
        "x": {
          "$count": 41
        },
        "y": {
          "$count": 33
        },
        "symbol": {
          "$count": 62
        },
        "itemStyle": {
          "$count": 41,
          "normal": {
            "borderWidth": {
              "$count": 1
            },
            "borderColor": {
              "$count": 5
            },
            "$count": 16,
            "color": {
              "$count": 6
            },
            "opacity": {
              "$count": 1
            }
          },
          "emphasis": {
            "color": {
              "$count": 1
            },
            "$count": 5,
            "shadowOffsetX": {
              "$count": 1
            },
            "shadowBlur": {
              "$count": 1
            }
          }
        },
        "coord": {
          "$count": 50
        },
        "symbolRotate": {
          "$count": 16
        },
        "label": {
          "$count": 25,
          "emphasis": {
            "$count": 8,
            "position": {
              "$count": 3
            },
            "show": {
              "$count": 2
            },
            "textStyle": {
              "color": {
                "$count": 1
              }
            }
          },
          "normal": {
            "$count": 13,
            "textStyle": {
              "$count": 3,
              "color": {
                "$count": 2
              },
              "fontStyle": {
                "$count": 1
              },
              "fontFamily": {
                "$count": 1
              },
              "fontSize": {
                "$count": 1
              }
            },
            "position": {
              "$count": 13
            },
            "show": {
              "$count": 7
            }
          }
        },
        "symbolOffset": {
          "$count": 21
        },
        "valueDim": {
          "$count": 4
        }
      },
      "$count": 522,
      "label": {
        "$count": 88,
        "normal": {
          "formatter": {
            "$count": 40
          },
          "$count": 46,
          "position": {
            "$count": 37
          },
          "textStyle": {
            "$count": 16,
            "color": {
              "$count": 4
            },
            "fontSize": {
              "$count": 2
            }
          },
          "show": {
            "$count": 26
          }
        },
        "emphasis": {
          "$count": 20,
          "show": {
            "$count": 5
          },
          "position": {
            "$count": 4
          },
          "textStyle": {
            "$count": 2,
            "fontSize": {
              "$count": 1
            },
            "color": {
              "$count": 1
            }
          },
          "formatter": {
            "$count": 1
          }
        }
      },
      "symbolSize": {
        "$count": 87
      },
      "symbol": {
        "$count": 162
      },
      "symbolRotate": {
        "$count": 58
      },
      "symbolOffset": {
        "$count": 67
      },
      "animation": {
        "$count": 13
      },
      "animationDuration": {
        "$count": 7
      },
      "animationEasing": {
        "$count": 7
      },
      "animationDurationUpdate": {
        "$count": 8
      },
      "animationEasingUpdate": {
        "$count": 12
      }
    },
    "xAxisIndex": {
      "$count": 453
    },
    "yAxisIndex": {
      "$count": 314
    },
    "animation": {
      "$count": 123
    },
    "animationDuration": {
      "$count": 81
    },
    "animationDurationUpdate": {
      "$count": 64
    },
    "animationEasingUpdate": {
      "$count": 66
    },
    "stack": {
      "$count": 509
    },
    "animationEasing": {
      "$count": 67
    },
    "z": {
      "$count": 15
    },
    "zlevel": {
      "$count": 16
    }
  },
  "series-pie": {
    "center": {
      "$count": 512
    },
    "data": {
      "label": {
        "$count": 342,
        "normal": {
          "position": {
            "$count": 118
          },
          "textStyle": {
            "$count": 84,
            "color": {
              "$count": 26
            },
            "fontSize": {
              "$count": 20
            },
            "fontFamily": {
              "$count": 16
            },
            "fontWeight": {
              "$count": 11
            },
            "fontStyle": {
              "$count": 13
            }
          },
          "$count": 157,
          "show": {
            "$count": 98
          }
        },
        "emphasis": {
          "$count": 73,
          "textStyle": {
            "fontSize": {
              "$count": 7
            },
            "$count": 22,
            "color": {
              "$count": 11
            },
            "fontStyle": {
              "$count": 7
            },
            "fontWeight": {
              "$count": 7
            },
            "fontFamily": {
              "$count": 4
            }
          },
          "show": {
            "$count": 27
          }
        }
      },
      "$count": 533,
      "itemStyle": {
        "$count": 294,
        "normal": {
          "$count": 166,
          "color": {
            "$count": 131
          },
          "borderWidth": {
            "$count": 26
          },
          "borderColor": {
            "$count": 31
          },
          "shadowColor": {
            "$count": 25
          },
          "shadowOffsetX": {
            "$count": 8
          },
          "shadowBlur": {
            "$count": 28
          },
          "shadowOffsetY": {
            "$count": 11
          },
          "opacity": {
            "$count": 23
          }
        },
        "emphasis": {
          "$count": 80,
          "color": {
            "$count": 26
          },
          "borderColor": {
            "$count": 8
          },
          "shadowBlur": {
            "$count": 10
          },
          "shadowColor": {
            "$count": 9
          },
          "borderWidth": {
            "$count": 6
          },
          "opacity": {
            "$count": 12
          },
          "shadowOffsetX": {
            "$count": 3
          },
          "shadowOffsetY": {
            "$count": 6
          }
        }
      },
      "selected": {
        "$count": 239
      },
      "name": {
        "$count": 265
      },
      "labelLine": {
        "normal": {
          "show": {
            "$count": 19
          },
          "$count": 30,
          "length": {
            "$count": 17
          },
          "lineStyle": {
            "$count": 16,
            "width": {
              "$count": 5
            },
            "color": {
              "$count": 4
            },
            "shadowBlur": {
              "$count": 3
            },
            "shadowColor": {
              "$count": 2
            },
            "shadowOffsetY": {
              "$count": 1
            },
            "shadowOffsetX": {
              "$count": 3
            },
            "type": {
              "$count": 3
            }
          },
          "length2": {
            "$count": 9
          },
          "smooth": {
            "$count": 13
          }
        },
        "$count": 163,
        "emphasis": {
          "$count": 12,
          "show": {
            "$count": 6
          },
          "lineStyle": {
            "$count": 4,
            "color": {
              "$count": 2
            }
          }
        }
      },
      "value": {
        "$count": 248
      }
    },
    "type": {
      "$count": 586
    },
    "$count": 2477,
    "radius": {
      "$count": 548
    },
    "label": {
      "$count": 1025,
      "normal": {
        "position": {
          "$count": 548
        },
        "textStyle": {
          "$count": 243,
          "fontFamily": {
            "$count": 61
          },
          "fontWeight": {
            "$count": 61
          },
          "color": {
            "$count": 93
          },
          "fontStyle": {
            "$count": 68
          },
          "fontSize": {
            "$count": 85
          }
        },
        "formatter": {
          "$count": 562
        },
        "$count": 490,
        "show": {
          "$count": 278
        }
      },
      "emphasis": {
        "$count": 282,
        "formatter": {
          "$count": 124
        },
        "textStyle": {
          "$count": 58,
          "fontSize": {
            "$count": 11
          },
          "color": {
            "$count": 17
          },
          "fontStyle": {
            "$count": 8
          },
          "fontWeight": {
            "$count": 10
          },
          "fontFamily": {
            "$count": 9
          }
        },
        "show": {
          "$count": 84
        }
      }
    },
    "legendHoverLink": {
      "$count": 583
    },
    "hoverAnimation": {
      "$count": 466
    },
    "selectedOffset": {
      "$count": 352
    },
    "clockwise": {
      "$count": 353
    },
    "startAngle": {
      "$count": 348
    },
    "minAngle": {
      "$count": 290
    },
    "roseType": {
      "$count": 558
    },
    "avoidLabelOverlap": {
      "$count": 456
    },
    "name": {
      "$count": 482
    },
    "itemStyle": {
      "$count": 665,
      "normal": {
        "color": {
          "$count": 306
        },
        "$count": 283,
        "borderWidth": {
          "$count": 78
        },
        "borderColor": {
          "$count": 120
        },
        "shadowBlur": {
          "$count": 78
        },
        "shadowColor": {
          "$count": 55
        },
        "shadowOffsetX": {
          "$count": 57
        },
        "opacity": {
          "$count": 73
        },
        "shadowOffsetY": {
          "$count": 38
        }
      },
      "emphasis": {
        "$count": 170,
        "color": {
          "$count": 71
        },
        "opacity": {
          "$count": 28
        },
        "borderColor": {
          "$count": 29
        },
        "shadowOffsetY": {
          "$count": 13
        },
        "shadowOffsetX": {
          "$count": 24
        },
        "shadowColor": {
          "$count": 35
        },
        "shadowBlur": {
          "$count": 36
        },
        "borderWidth": {
          "$count": 23
        }
      }
    },
    "markLine": {
      "$count": 217,
      "symbol": {
        "$count": 37
      },
      "data": {
        "0": {
          "symbolOffset": {
            "$count": 1
          },
          "symbolRotate": {
            "$count": 3
          },
          "symbol": {
            "$count": 9
          },
          "symbolSize": {
            "$count": 2
          },
          "x": {
            "$count": 2
          },
          "y": {
            "$count": 2
          },
          "$count": 16,
          "value": {
            "$count": 5
          },
          "label": {
            "normal": {
              "formatter": {
                "$count": 2
              },
              "$count": 1
            },
            "$count": 3,
            "emphasis": {
              "formatter": {
                "$count": 2
              },
              "$count": 1
            }
          },
          "lineStyle": {
            "normal": {
              "color": {
                "$count": 2
              }
            },
            "$count": 2
          }
        },
        "1": {
          "$count": 6,
          "value": {
            "$count": 2
          },
          "lineStyle": {
            "emphasis": {
              "shadowBlur": {
                "$count": 1
              }
            }
          },
          "label": {
            "emphasis": {
              "position": {
                "$count": 1
              },
              "formatter": {
                "$count": 3
              }
            },
            "normal": {
              "formatter": {
                "$count": 2
              },
              "$count": 1
            },
            "$count": 1
          },
          "symbolRotate": {
            "$count": 1
          }
        },
        "$count": 21
      },
      "symbolSize": {
        "$count": 21
      },
      "label": {
        "normal": {
          "$count": 3,
          "formatter": {
            "$count": 4
          },
          "position": {
            "$count": 3
          },
          "show": {
            "$count": 6
          }
        },
        "$count": 17,
        "emphasis": {
          "formatter": {
            "$count": 1
          },
          "$count": 2
        }
      },
      "lineStyle": {
        "$count": 11,
        "normal": {
          "$count": 4,
          "color": {
            "$count": 2
          }
        },
        "emphasis": {
          "$count": 1,
          "shadowOffsetY": {
            "$count": 1
          },
          "shadowOffsetX": {
            "$count": 1
          },
          "shadowColor": {
            "$count": 1
          },
          "shadowBlur": {
            "$count": 1
          },
          "type": {
            "$count": 1
          }
        }
      },
      "precision": {
        "$count": 13
      },
      "animationEasingUpdate": {
        "$count": 1
      },
      "animation": {
        "$count": 4
      }
    },
    "selectedMode": {
      "$count": 449
    },
    "animation": {
      "$count": 115
    },
    "animationDuration": {
      "$count": 63
    },
    "animationEasing": {
      "$count": 57
    },
    "animationDurationUpdate": {
      "$count": 43
    },
    "animationEasingUpdate": {
      "$count": 53
    },
    "labelLine": {
      "$count": 627,
      "normal": {
        "$count": 178,
        "show": {
          "$count": 163
        },
        "lineStyle": {
          "color": {
            "$count": 25
          },
          "$count": 84,
          "type": {
            "$count": 28
          },
          "width": {
            "$count": 20
          },
          "shadowBlur": {
            "$count": 19
          },
          "shadowColor": {
            "$count": 12
          },
          "opacity": {
            "$count": 20
          },
          "shadowOffsetY": {
            "$count": 10
          },
          "shadowOffsetX": {
            "$count": 12
          }
        },
        "length": {
          "$count": 181
        },
        "length2": {
          "$count": 95
        },
        "smooth": {
          "$count": 88
        }
      },
      "emphasis": {
        "$count": 71,
        "show": {
          "$count": 28
        },
        "lineStyle": {
          "$count": 17,
          "color": {
            "$count": 7
          },
          "type": {
            "$count": 1
          },
          "shadowBlur": {
            "$count": 1
          },
          "opacity": {
            "$count": 1
          },
          "width": {
            "$count": 2
          }
        }
      }
    },
    "markPoint": {
      "$count": 305,
      "symbol": {
        "$count": 84
      },
      "symbolSize": {
        "$count": 40
      },
      "data": {
        "symbolSize": {
          "$count": 12
        },
        "$count": 66,
        "itemStyle": {
          "$count": 11,
          "emphasis": {
            "color": {
              "$count": 1
            },
            "$count": 1
          },
          "normal": {
            "color": {
              "$count": 2
            }
          }
        },
        "label": {
          "$count": 14,
          "normal": {
            "position": {
              "$count": 4
            },
            "textStyle": {
              "$count": 3
            },
            "$count": 1,
            "show": {
              "$count": 2
            }
          }
        },
        "name": {
          "$count": 28
        },
        "x": {
          "$count": 16
        },
        "y": {
          "$count": 10
        },
        "value": {
          "$count": 22
        },
        "symbolOffset": {
          "$count": 7
        },
        "symbol": {
          "$count": 11
        },
        "symbolRotate": {
          "$count": 6
        }
      },
      "symbolRotate": {
        "$count": 28
      },
      "symbolOffset": {
        "$count": 24
      },
      "label": {
        "$count": 45,
        "normal": {
          "$count": 16,
          "show": {
            "$count": 14
          },
          "position": {
            "$count": 16
          },
          "formatter": {
            "$count": 12
          },
          "textStyle": {
            "$count": 7,
            "color": {
              "$count": 1
            }
          }
        },
        "emphasis": {
          "show": {
            "$count": 1
          },
          "$count": 5,
          "formatter": {
            "$count": 1
          },
          "position": {
            "$count": 1
          }
        }
      },
      "itemStyle": {
        "$count": 29,
        "normal": {
          "$count": 5,
          "color": {
            "$count": 1
          }
        }
      },
      "animation": {
        "$count": 11
      },
      "animationDuration": {
        "$count": 4
      },
      "animationEasing": {
        "$count": 4
      },
      "animationDurationUpdate": {
        "$count": 4
      },
      "animationEasingUpdate": {
        "$count": 4
      }
    },
    "z": {
      "$count": 97
    },
    "zlevel": {
      "$count": 136
    }
  },
  "backgroundColor": {
    "$count": 3583
  },
  "series-treemap": {
    "$count": 964,
    "levels": {
      "$count": 91,
      "label": {
        "normal": {
          "position": {
            "$count": 4
          },
          "textStyle": {
            "baseline": {
              "$count": 4
            },
            "$count": 2,
            "ellipsis": {
              "$count": 2
            },
            "color": {
              "$count": 1
            },
            "fontStyle": {
              "$count": 3
            },
            "fontWeight": {
              "$count": 2
            },
            "fontFamily": {
              "$count": 2
            },
            "fontSize": {
              "$count": 1
            },
            "align": {
              "$count": 2
            }
          },
          "show": {
            "$count": 2
          },
          "$count": 1
        },
        "emphasis": {
          "textStyle": {
            "baseline": {
              "$count": 1
            },
            "ellipsis": {
              "$count": 1
            },
            "fontStyle": {
              "$count": 1
            }
          },
          "$count": 2,
          "show": {
            "$count": 1
          },
          "position": {
            "$count": 1
          }
        },
        "$count": 5
      },
      "colorAlpha": {
        "$count": 11
      },
      "itemStyle": {
        "normal": {
          "borderWidth": {
            "$count": 4
          },
          "borderColor": {
            "$count": 4
          },
          "gapWidth": {
            "$count": 3
          },
          "$count": 6,
          "color": {
            "$count": 5
          },
          "colorAlpha": {
            "$count": 2
          },
          "colorSaturation": {
            "$count": 2
          },
          "borderColorSaturation": {
            "$count": 2
          }
        },
        "$count": 4,
        "emphasis": {
          "color": {
            "$count": 1
          },
          "colorAlpha": {
            "$count": 1
          },
          "borderWidth": {
            "$count": 1
          },
          "gapWidth": {
            "$count": 1
          },
          "borderColorSaturation": {
            "$count": 1
          },
          "$count": 1
        }
      },
      "colorSaturation": {
        "$count": 11
      },
      "childrenVisibleMin": {
        "$count": 6
      },
      "visibleMin": {
        "$count": 4
      },
      "colorMappingBy": {
        "$count": 14
      },
      "color": {
        "$count": 17
      },
      "visualDimension": {
        "$count": 20
      }
    },
    "zoomToNodeRatio": {
      "$count": 56
    },
    "data": {
      "$count": 54,
      "value": {
        "$count": 25
      },
      "label": {
        "normal": {
          "position": {
            "$count": 2
          },
          "$count": 2,
          "show": {
            "$count": 1
          }
        },
        "$count": 7,
        "emphasis": {
          "$count": 1
        }
      },
      "children": {
        "$count": 20
      },
      "name": {
        "$count": 16
      },
      "itemStyle": {
        "$count": 11,
        "normal": {
          "$count": 1
        }
      },
      "childrenVisibleMin": {
        "$count": 11
      },
      "colorMappingBy": {
        "$count": 22
      },
      "color": {
        "$count": 15
      },
      "colorAlpha": {
        "$count": 7
      },
      "colorSaturation": {
        "$count": 8
      },
      "visibleMin": {
        "$count": 8
      },
      "link": {
        "$count": 37
      },
      "target": {
        "$count": 19
      },
      "id": {
        "$count": 16
      },
      "visualDimension": {
        "$count": 16
      }
    },
    "width": {
      "$count": 13
    },
    "type": {
      "$count": 76
    },
    "roam": {
      "$count": 53
    },
    "breadcrumb": {
      "$count": 23,
      "emptyItemWidth": {
        "$count": 5
      },
      "itemStyle": {
        "emphasis": {
          "color": {
            "$count": 3
          },
          "borderWidth": {
            "$count": 1
          },
          "opacity": {
            "$count": 1
          },
          "shadowOffsetY": {
            "$count": 1
          },
          "shadowOffsetX": {
            "$count": 1
          }
        },
        "$count": 6,
        "normal": {
          "$count": 3,
          "color": {
            "$count": 2
          },
          "opacity": {
            "$count": 3
          },
          "shadowOffsetY": {
            "$count": 4
          },
          "shadowOffsetX": {
            "$count": 3
          },
          "shadowColor": {
            "$count": 2
          },
          "shadowBlur": {
            "$count": 1
          },
          "borderWidth": {
            "$count": 1
          },
          "textStyle": {
            "$count": 1
          }
        }
      },
      "show": {
        "$count": 1
      },
      "bottom": {
        "$count": 1
      },
      "height": {
        "$count": 2
      },
      "left": {
        "$count": 2
      }
    },
    "zlevel": {
      "$count": 18
    },
    "label": {
      "normal": {
        "position": {
          "$count": 9
        },
        "$count": 10,
        "show": {
          "$count": 5
        },
        "textStyle": {
          "$count": 4,
          "ellipsis": {
            "$count": 4
          },
          "color": {
            "$count": 4
          },
          "fontStyle": {
            "$count": 2
          },
          "fontWeight": {
            "$count": 2
          },
          "fontSize": {
            "$count": 1
          },
          "align": {
            "$count": 2
          },
          "baseline": {
            "$count": 4
          },
          "fontFamily": {
            "$count": 1
          }
        }
      },
      "$count": 24,
      "emphasis": {
        "$count": 6,
        "show": {
          "$count": 1
        },
        "position": {
          "$count": 1
        },
        "textStyle": {
          "$count": 1,
          "align": {
            "$count": 1
          }
        }
      }
    },
    "height": {
      "$count": 18
    },
    "itemStyle": {
      "$count": 13,
      "normal": {
        "gapWidth": {
          "$count": 4
        },
        "borderWidth": {
          "$count": 3
        },
        "$count": 4,
        "borderColorSaturation": {
          "$count": 2
        },
        "colorAlpha": {
          "$count": 2
        },
        "colorSaturation": {
          "$count": 1
        },
        "borderColor": {
          "$count": 1
        },
        "color": {
          "$count": 3
        }
      },
      "emphasis": {
        "$count": 1
      }
    },
    "squareRatio": {
      "$count": 40
    },
    "z": {
      "$count": 13
    },
    "left": {
      "$count": 22
    },
    "top": {
      "$count": 15
    },
    "right": {
      "$count": 9
    },
    "bottom": {
      "$count": 10
    },
    "visualDimension": {
      "$count": 31
    },
    "visibleMin": {
      "$count": 10
    },
    "childrenVisibleMin": {
      "$count": 14
    },
    "animationEasing": {
      "$count": 16
    },
    "animationDuration": {
      "$count": 21
    },
    "colorMappingBy": {
      "$count": 18
    },
    "colorSaturation": {
      "$count": 19
    },
    "colorAlpha": {
      "$count": 14
    },
    "color": {
      "$count": 22
    },
    "nodeClick": {
      "$count": 140
    }
  },
  "series-map": {
    "$count": 2073,
    "mapValueCalculation": {
      "$count": 420
    },
    "roam": {
      "$count": 470
    },
    "selectedMode": {
      "$count": 438
    },
    "type": {
      "$count": 634
    },
    "itemStyle": {
      "$count": 540,
      "normal": {
        "areaColor": {
          "$count": 223
        },
        "$count": 243,
        "borderColor": {
          "$count": 80
        },
        "borderWidth": {
          "$count": 59
        },
        "color": {
          "$count": 138
        },
        "opacity": {
          "$count": 74
        },
        "shadowBlur": {
          "$count": 55
        },
        "shadowColor": {
          "$count": 31
        },
        "shadowOffsetX": {
          "$count": 36
        },
        "shadowOffsetY": {
          "$count": 28
        }
      },
      "emphasis": {
        "$count": 161,
        "color": {
          "$count": 107
        },
        "opacity": {
          "$count": 44
        },
        "shadowBlur": {
          "$count": 33
        },
        "borderColor": {
          "$count": 49
        },
        "borderWidth": {
          "$count": 31
        },
        "shadowOffsetY": {
          "$count": 18
        },
        "shadowColor": {
          "$count": 34
        },
        "shadowOffsetX": {
          "$count": 19
        }
      },
      "zlevel": {
        "$count": 83
      },
      "z": {
        "$count": 57
      },
      "bottom": {
        "$count": 46
      },
      "left": {
        "$count": 95
      },
      "top": {
        "$count": 60
      },
      "right": {
        "$count": 44
      }
    },
    "showLegendSymbol": {
      "$count": 414
    },
    "name": {
      "$count": 350
    },
    "map": {
      "$count": 651
    },
    "data": {
      "$count": 503,
      "name": {
        "$count": 371
      },
      "value": {
        "$count": 290
      }
    },
    "label": {
      "$count": 464,
      "emphasis": {
        "$count": 119,
        "textStyle": {
          "$count": 19,
          "color": {
            "$count": 8
          },
          "fontStyle": {
            "$count": 8
          },
          "fontFamily": {
            "$count": 7
          },
          "fontSize": {
            "$count": 3
          },
          "fontWeight": {
            "$count": 7
          }
        },
        "show": {
          "$count": 25
        }
      },
      "normal": {
        "$count": 223,
        "show": {
          "$count": 88
        },
        "textStyle": {
          "$count": 90,
          "color": {
            "$count": 38
          },
          "fontStyle": {
            "$count": 26
          },
          "fontWeight": {
            "$count": 26
          },
          "fontFamily": {
            "$count": 24
          },
          "fontSize": {
            "$count": 26
          }
        }
      }
    },
    "bottom": {
      "$count": 10
    },
    "right": {
      "$count": 4
    },
    "top": {
      "$count": 6
    },
    "left": {
      "$count": 14
    },
    "zlevel": {
      "$count": 15
    },
    "z": {
      "$count": 11
    }
  },
  "series-funnel": {
    "$count": 825,
    "type": {
      "$count": 41
    },
    "label": {
      "$count": 30,
      "normal": {
        "$count": 15,
        "position": {
          "$count": 16
        },
        "textStyle": {
          "$count": 9,
          "color": {
            "$count": 3
          },
          "fontSize": {
            "$count": 1
          },
          "fontFamily": {
            "$count": 1
          },
          "fontStyle": {
            "$count": 1
          }
        },
        "formatter": {
          "$count": 20
        },
        "show": {
          "$count": 6
        }
      },
      "emphasis": {
        "formatter": {
          "$count": 2
        },
        "$count": 6,
        "show": {
          "$count": 2
        }
      }
    },
    "labelLine": {
      "$count": 26,
      "normal": {
        "$count": 5,
        "lineStyle": {
          "$count": 4,
          "color": {
            "$count": 1
          },
          "width": {
            "$count": 1
          },
          "type": {
            "$count": 1
          },
          "shadowBlur": {
            "$count": 1
          }
        },
        "show": {
          "$count": 4
        },
        "length": {
          "$count": 3
        }
      },
      "emphasis": {
        "show": {
          "$count": 1
        }
      }
    },
    "itemStyle": {
      "$count": 22,
      "normal": {
        "$count": 10,
        "color": {
          "$count": 7
        },
        "borderWidth": {
          "$count": 2
        },
        "opacity": {
          "$count": 4
        },
        "shadowOffsetY": {
          "$count": 2
        },
        "shadowColor": {
          "$count": 2
        },
        "shadowBlur": {
          "$count": 2
        },
        "borderColor": {
          "$count": 1
        },
        "shadowOffsetX": {
          "$count": 1
        }
      },
      "emphasis": {
        "$count": 6,
        "opacity": {
          "$count": 2
        },
        "color": {
          "$count": 1
        }
      }
    },
    "data": {
      "$count": 24,
      "value": {
        "$count": 11
      },
      "name": {
        "$count": 7
      },
      "labelLine": {
        "$count": 4,
        "normal": {
          "lineStyle": {
            "width": {
              "$count": 1
            },
            "opacity": {
              "$count": 1
            }
          },
          "length": {
            "$count": 1
          },
          "show": {
            "$count": 1
          }
        }
      },
      "label": {
        "normal": {
          "position": {
            "$count": 2
          },
          "$count": 3,
          "textStyle": {
            "color": {
              "$count": 1
            },
            "$count": 2,
            "fontSize": {
              "$count": 1
            },
            "fontWeight": {
              "$count": 1
            },
            "fontStyle": {
              "$count": 1
            }
          },
          "show": {
            "$count": 1
          }
        },
        "$count": 12,
        "emphasis": {
          "show": {
            "$count": 1
          },
          "$count": 2
        }
      },
      "itemStyle": {
        "$count": 4,
        "normal": {
          "color": {
            "$count": 2
          },
          "borderColor": {
            "$count": 1
          },
          "borderWidth": {
            "$count": 1
          },
          "$count": 3
        }
      }
    },
    "funnelAlign": {
      "$count": 32
    },
    "markLine": {
      "$count": 20,
      "data": {
        "0": {
          "label": {
            "emphasis": {
              "formatter": {
                "$count": 1
              }
            }
          },
          "x": {
            "$count": 1
          },
          "symbol": {
            "$count": 1
          }
        },
        "1": {
          "lineStyle": {
            "normal": {
              "type": {
                "$count": 1
              }
            },
            "$count": 1
          }
        },
        "$count": 3
      },
      "symbolSize": {
        "$count": 1
      },
      "symbol": {
        "$count": 4
      },
      "label": {
        "$count": 2
      }
    },
    "markPoint": {
      "label": {
        "normal": {
          "position": {
            "$count": 1
          }
        },
        "$count": 1
      },
      "$count": 14,
      "itemStyle": {
        "normal": {
          "color": {
            "$count": 2
          },
          "$count": 1
        }
      },
      "symbol": {
        "$count": 1
      },
      "data": {
        "itemStyle": {
          "$count": 1
        },
        "symbol": {
          "$count": 1
        },
        "symbolRotate": {
          "$count": 1
        },
        "$count": 1
      },
      "symbolRotate": {
        "$count": 1
      }
    },
    "sort": {
      "$count": 43
    },
    "name": {
      "$count": 15
    },
    "min": {
      "$count": 12
    },
    "max": {
      "$count": 10
    },
    "minSize": {
      "$count": 14
    },
    "maxSize": {
      "$count": 9
    },
    "gap": {
      "$count": 22
    },
    "legendHoverLink": {
      "$count": 19
    },
    "animation": {
      "$count": 6
    },
    "animationDuration": {
      "$count": 5
    },
    "animationEasing": {
      "$count": 1
    },
    "animationDurationUpdate": {
      "$count": 1
    },
    "animationEasingUpdate": {
      "$count": 2
    }
  },
  "series-effectScatter": {
    "$count": 1209,
    "effectType": {
      "$count": 148
    },
    "showEffectOn": {
      "$count": 145
    },
    "rippleEffect": {
      "$count": 175,
      "brushType": {
        "$count": 87
      },
      "period": {
        "$count": 83
      },
      "scale": {
        "$count": 65
      }
    },
    "data": {
      "$count": 124,
      "itemStyle": {
        "$count": 22,
        "normal": {
          "shadowOffsetY": {
            "$count": 1
          },
          "shadowOffsetX": {
            "$count": 1
          },
          "opacity": {
            "$count": 3
          },
          "color": {
            "$count": 6
          },
          "$count": 8,
          "borderWidth": {
            "$count": 1
          },
          "borderColor": {
            "$count": 1
          }
        },
        "emphasis": {
          "$count": 2,
          "color": {
            "$count": 1
          },
          "opacity": {
            "$count": 1
          }
        }
      },
      "symbol": {
        "$count": 43
      },
      "symbolSize": {
        "$count": 24
      },
      "symbolRotate": {
        "$count": 18
      },
      "symbolOffset": {
        "$count": 16
      },
      "label": {
        "$count": 28,
        "normal": {
          "$count": 9,
          "position": {
            "$count": 5
          },
          "textStyle": {
            "color": {
              "$count": 1
            },
            "fontStyle": {
              "$count": 1
            },
            "fontSize": {
              "$count": 1
            },
            "$count": 2
          },
          "show": {
            "$count": 2
          }
        },
        "emphasis": {
          "$count": 5,
          "show": {
            "$count": 1
          }
        }
      }
    },
    "markPoint": {
      "$count": 69,
      "itemStyle": {
        "$count": 3,
        "normal": {
          "$count": 1,
          "borderWidth": {
            "$count": 1
          }
        },
        "emphasis": {
          "$count": 1
        }
      },
      "label": {
        "$count": 8,
        "normal": {
          "position": {
            "$count": 2
          },
          "show": {
            "$count": 1
          },
          "formatter": {
            "$count": 1
          },
          "$count": 1
        },
        "emphasis": {
          "$count": 2
        }
      },
      "data": {
        "$count": 8,
        "type": {
          "$count": 8
        },
        "name": {
          "$count": 2
        },
        "valueIndex": {
          "$count": 1
        },
        "coord": {
          "$count": 3
        },
        "x": {
          "$count": 2
        },
        "y": {
          "$count": 2
        },
        "value": {
          "$count": 1
        },
        "symbol": {
          "$count": 3
        },
        "symbolSize": {
          "$count": 2
        },
        "symbolRotate": {
          "$count": 1
        },
        "symbolOffset": {
          "$count": 1
        },
        "label": {
          "emphasis": {
            "textStyle": {
              "$count": 1
            },
            "show": {
              "$count": 1
            }
          }
        }
      },
      "symbol": {
        "$count": 27
      },
      "animationEasingUpdate": {
        "$count": 4
      },
      "animationDurationUpdate": {
        "$count": 3
      },
      "animationEasing": {
        "$count": 2
      },
      "animationDuration": {
        "$count": 3
      },
      "animation": {
        "$count": 5
      },
      "symbolSize": {
        "$count": 10
      },
      "symbolRotate": {
        "$count": 6
      },
      "symbolOffset": {
        "$count": 4
      }
    },
    "markLine": {
      "$count": 29,
      "data": {
        "0": {
          "symbol": {
            "$count": 2
          },
          "$count": 1,
          "symbolSize": {
            "$count": 1
          }
        },
        "1": {
          "symbolSize": {
            "$count": 1
          }
        },
        "$count": 3
      },
      "label": {
        "emphasis": {
          "formatter": {
            "$count": 1
          },
          "$count": 1
        },
        "$count": 1
      },
      "symbolSize": {
        "$count": 2
      },
      "precision": {
        "$count": 3
      },
      "lineStyle": {
        "$count": 1,
        "normal": {
          "width": {
            "$count": 1
          },
          "curveness": {
            "$count": 1
          }
        }
      },
      "symbol": {
        "$count": 5
      }
    },
    "animation": {
      "$count": 24
    },
    "animationDuration": {
      "$count": 17
    },
    "animationEasing": {
      "$count": 12
    },
    "animationDurationUpdate": {
      "$count": 15
    },
    "animationEasingUpdate": {
      "$count": 14
    },
    "type": {
      "$count": 197
    },
    "legendHoverLink": {
      "$count": 66
    },
    "name": {
      "$count": 58
    },
    "geoIndex": {
      "$count": 42
    },
    "label": {
      "normal": {
        "$count": 37,
        "formatter": {
          "$count": 40
        },
        "position": {
          "$count": 26
        },
        "textStyle": {
          "$count": 17,
          "color": {
            "$count": 5
          },
          "fontStyle": {
            "$count": 4
          },
          "fontWeight": {
            "$count": 2
          },
          "fontFamily": {
            "$count": 3
          },
          "fontSize": {
            "$count": 2
          }
        },
        "show": {
          "$count": 10
        }
      },
      "$count": 62,
      "emphasis": {
        "$count": 21,
        "show": {
          "$count": 6
        },
        "position": {
          "$count": 6
        },
        "formatter": {
          "$count": 9
        }
      }
    },
    "coordinateSystem": {
      "$count": 98
    },
    "yAxisIndex": {
      "$count": 22
    },
    "polarIndex": {
      "$count": 25
    },
    "symbolSize": {
      "$count": 82
    },
    "symbol": {
      "$count": 108
    },
    "itemStyle": {
      "$count": 46,
      "normal": {
        "shadowBlur": {
          "$count": 15
        },
        "shadowColor": {
          "$count": 10
        },
        "opacity": {
          "$count": 7
        },
        "$count": 20,
        "color": {
          "$count": 11
        },
        "shadowOffsetY": {
          "$count": 4
        },
        "borderColor": {
          "$count": 7
        },
        "borderWidth": {
          "$count": 5
        },
        "shadowOffsetX": {
          "$count": 3
        }
      },
      "emphasis": {
        "$count": 8,
        "opacity": {
          "$count": 1
        },
        "shadowOffsetY": {
          "$count": 1
        },
        "shadowOffsetX": {
          "$count": 1
        },
        "shadowColor": {
          "$count": 1
        },
        "borderWidth": {
          "$count": 1
        },
        "borderColor": {
          "$count": 1
        }
      }
    },
    "xAxisIndex": {
      "$count": 37
    },
    "symbolRotate": {
      "$count": 35
    },
    "symbolOffset": {
      "$count": 36
    },
    "z": {
      "$count": 1
    },
    "zlevel": {
      "$count": 1
    }
  },
  "series-graph": {
    "$count": 1317,
    "lineStyle": {
      "$count": 169,
      "normal": {
        "curveness": {
          "$count": 30
        },
        "$count": 54,
        "color": {
          "$count": 21
        },
        "width": {
          "$count": 26
        },
        "type": {
          "$count": 35
        },
        "shadowBlur": {
          "$count": 18
        },
        "shadowColor": {
          "$count": 11
        },
        "shadowOffsetX": {
          "$count": 9
        },
        "opacity": {
          "$count": 21
        },
        "shadowOffsetY": {
          "$count": 4
        }
      },
      "emphasis": {
        "$count": 24,
        "shadowOffsetY": {
          "$count": 3
        },
        "shadowOffsetX": {
          "$count": 5
        },
        "shadowColor": {
          "$count": 4
        },
        "shadowBlur": {
          "$count": 4
        },
        "opacity": {
          "$count": 8
        },
        "color": {
          "$count": 2
        },
        "width": {
          "$count": 2
        },
        "type": {
          "$count": 4
        }
      }
    },
    "links": {
      "$count": 430,
      "target": {
        "$count": 96
      },
      "lineStyle": {
        "$count": 161,
        "normal": {
          "$count": 99,
          "color": {
            "$count": 50
          },
          "width": {
            "$count": 55
          },
          "type": {
            "$count": 70
          },
          "curveness": {
            "$count": 36
          },
          "shadowBlur": {
            "$count": 31
          },
          "shadowColor": {
            "$count": 22
          },
          "shadowOffsetX": {
            "$count": 21
          },
          "shadowOffsetY": {
            "$count": 16
          },
          "opacity": {
            "$count": 33
          }
        },
        "emphasis": {
          "$count": 63,
          "color": {
            "$count": 8
          },
          "type": {
            "$count": 11
          },
          "shadowOffsetX": {
            "$count": 4
          },
          "shadowOffsetY": {
            "$count": 5
          },
          "opacity": {
            "$count": 12
          },
          "shadowBlur": {
            "$count": 8
          },
          "shadowColor": {
            "$count": 4
          },
          "width": {
            "$count": 8
          }
        }
      },
      "source": {
        "$count": 140
      }
    },
    "edges": {
      "$count": 171
    },
    "layout": {
      "$count": 282
    },
    "force": {
      "$count": 291,
      "repulsion": {
        "$count": 100
      },
      "layoutAnimation": {
        "$count": 47
      },
      "initLayout": {
        "$count": 128
      },
      "gravity": {
        "$count": 60
      },
      "edgeLength": {
        "$count": 66
      }
    },
    "data": {
      "$count": 559,
      "name": {
        "$count": 228
      },
      "label": {
        "$count": 109,
        "normal": {
          "position": {
            "$count": 36
          },
          "$count": 49,
          "show": {
            "$count": 40
          },
          "textStyle": {
            "$count": 20,
            "fontWeight": {
              "$count": 1
            },
            "color": {
              "$count": 1
            },
            "fontStyle": {
              "$count": 1
            },
            "fontFamily": {
              "$count": 1
            }
          }
        },
        "emphasis": {
          "$count": 20,
          "show": {
            "$count": 3
          },
          "textStyle": {
            "$count": 3
          },
          "position": {
            "$count": 3
          }
        }
      },
      "symbol": {
        "$count": 146
      },
      "itemStyle": {
        "$count": 95,
        "emphasis": {
          "color": {
            "$count": 2
          },
          "$count": 14,
          "borderColor": {
            "$count": 1
          },
          "shadowBlur": {
            "$count": 3
          },
          "shadowColor": {
            "$count": 2
          },
          "shadowOffsetX": {
            "$count": 2
          },
          "shadowOffsetY": {
            "$count": 1
          },
          "opacity": {
            "$count": 1
          }
        },
        "normal": {
          "$count": 38,
          "color": {
            "$count": 21
          },
          "opacity": {
            "$count": 9
          },
          "shadowBlur": {
            "$count": 8
          },
          "borderColor": {
            "$count": 10
          },
          "borderWidth": {
            "$count": 9
          },
          "shadowColor": {
            "$count": 8
          },
          "shadowOffsetX": {
            "$count": 9
          },
          "shadowOffsetY": {
            "$count": 7
          }
        }
      },
      "value": {
        "$count": 151
      },
      "category": {
        "$count": 181
      },
      "symbolRotate": {
        "$count": 65
      },
      "symbolSize": {
        "$count": 106
      },
      "symbolOffset": {
        "$count": 68
      }
    },
    "nodes": {
      "$count": 316
    },
    "symbolOffset": {
      "$count": 61
    },
    "label": {
      "$count": 169,
      "normal": {
        "show": {
          "$count": 34
        },
        "$count": 52,
        "formatter": {
          "$count": 98
        },
        "position": {
          "$count": 46
        },
        "textStyle": {
          "$count": 31,
          "color": {
            "$count": 6
          },
          "fontStyle": {
            "$count": 5
          },
          "fontWeight": {
            "$count": 6
          },
          "fontFamily": {
            "$count": 4
          },
          "fontSize": {
            "$count": 10
          }
        }
      },
      "emphasis": {
        "$count": 19,
        "show": {
          "$count": 5
        },
        "position": {
          "$count": 7
        },
        "textStyle": {
          "$count": 5,
          "fontStyle": {
            "$count": 1
          },
          "fontWeight": {
            "$count": 1
          },
          "fontFamily": {
            "$count": 1
          },
          "fontSize": {
            "$count": 1
          }
        },
        "formatter": {
          "$count": 11
        }
      }
    },
    "zlevel": {
      "$count": 31
    },
    "width": {
      "$count": 45
    },
    "animation": {
      "$count": 40
    },
    "type": {
      "$count": 244
    },
    "legendHoverLink": {
      "$count": 135
    },
    "hoverAnimation": {
      "$count": 112
    },
    "itemStyle": {
      "$count": 157,
      "emphasis": {
        "$count": 18,
        "shadowOffsetY": {
          "$count": 1
        },
        "color": {
          "$count": 1
        },
        "borderWidth": {
          "$count": 1
        }
      },
      "normal": {
        "borderColor": {
          "$count": 13
        },
        "color": {
          "$count": 17
        },
        "opacity": {
          "$count": 6
        },
        "$count": 38,
        "borderWidth": {
          "$count": 11
        },
        "shadowBlur": {
          "$count": 6
        },
        "shadowColor": {
          "$count": 2
        },
        "shadowOffsetX": {
          "$count": 3
        },
        "shadowOffsetY": {
          "$count": 2
        }
      }
    },
    "name": {
      "$count": 135
    },
    "categories": {
      "$count": 211,
      "symbol": {
        "$count": 44
      },
      "itemStyle": {
        "$count": 16,
        "normal": {
          "shadowBlur": {
            "$count": 2
          },
          "$count": 7,
          "color": {
            "$count": 13
          },
          "borderWidth": {
            "$count": 2
          },
          "borderColor": {
            "$count": 3
          },
          "shadowColor": {
            "$count": 1
          },
          "shadowOffsetY": {
            "$count": 1
          },
          "opacity": {
            "$count": 1
          }
        },
        "emphasis": {
          "color": {
            "$count": 1
          },
          "$count": 1
        }
      },
      "symbolSize": {
        "$count": 18
      },
      "name": {
        "$count": 50
      },
      "symbolRotate": {
        "$count": 11
      },
      "label": {
        "$count": 8,
        "normal": {
          "formatter": {
            "$count": 3
          },
          "$count": 2
        }
      },
      "symbolOffset": {
        "$count": 9
      }
    },
    "roam": {
      "$count": 138
    },
    "symbolRotate": {
      "$count": 65
    },
    "symbolSize": {
      "$count": 94
    },
    "left": {
      "$count": 35
    },
    "top": {
      "$count": 27
    },
    "symbol": {
      "$count": 136
    },
    "nodeScaleRatio": {
      "$count": 98
    },
    "animationEasingUpdate": {
      "$count": 30
    },
    "animationEasing": {
      "$count": 24
    },
    "color": {
      "$count": 39
    },
    "height": {
      "$count": 30
    },
    "bottom": {
      "$count": 18
    },
    "markLine": {
      "$count": 159,
      "symbol": {
        "$count": 57
      },
      "lineStyle": {
        "$count": 17,
        "normal": {
          "$count": 2,
          "curveness": {
            "$count": 3
          },
          "type": {
            "$count": 6
          },
          "shadowBlur": {
            "$count": 2
          },
          "shadowColor": {
            "$count": 2
          },
          "shadowOffsetX": {
            "$count": 2
          },
          "color": {
            "$count": 2
          },
          "width": {
            "$count": 2
          },
          "opacity": {
            "$count": 1
          }
        },
        "emphasis": {
          "type": {
            "$count": 2
          },
          "shadowBlur": {
            "$count": 1
          },
          "$count": 1
        }
      },
      "data": {
        "0": {
          "$count": 17,
          "symbol": {
            "$count": 24
          },
          "x": {
            "$count": 8
          },
          "y": {
            "$count": 5
          },
          "value": {
            "$count": 8
          },
          "symbolSize": {
            "$count": 6
          },
          "lineStyle": {
            "$count": 8,
            "normal": {
              "$count": 1,
              "type": {
                "$count": 1
              }
            }
          },
          "label": {
            "normal": {
              "position": {
                "$count": 1
              },
              "formatter": {
                "$count": 2
              },
              "$count": 1
            },
            "emphasis": {
              "position": {
                "$count": 1
              },
              "formatter": {
                "$count": 2
              }
            },
            "$count": 4
          },
          "symbolOffset": {
            "$count": 3
          },
          "symbolRotate": {
            "$count": 2
          }
        },
        "1": {
          "$count": 8,
          "lineStyle": {
            "normal": {
              "color": {
                "$count": 2
              },
              "$count": 1,
              "shadowBlur": {
                "$count": 1
              }
            }
          },
          "value": {
            "$count": 1
          },
          "symbolRotate": {
            "$count": 1
          },
          "label": {
            "emphasis": {
              "position": {
                "$count": 1
              },
              "formatter": {
                "$count": 1
              }
            },
            "normal": {
              "position": {
                "$count": 1
              },
              "formatter": {
                "$count": 3
              }
            },
            "$count": 1
          },
          "x": {
            "$count": 3
          },
          "symbol": {
            "$count": 2
          }
        },
        "$count": 47
      },
      "symbolSize": {
        "$count": 19
      },
      "precision": {
        "$count": 11
      },
      "label": {
        "$count": 19,
        "normal": {
          "$count": 6,
          "formatter": {
            "$count": 5
          },
          "show": {
            "$count": 7
          },
          "position": {
            "$count": 9
          }
        },
        "emphasis": {
          "$count": 1,
          "formatter": {
            "$count": 1
          }
        }
      },
      "animationEasing": {
        "$count": 1
      },
      "animation": {
        "$count": 1
      }
    },
    "z": {
      "$count": 22
    },
    "right": {
      "$count": 14
    },
    "markPoint": {
      "$count": 120,
      "symbol": {
        "$count": 22
      },
      "symbolRotate": {
        "$count": 6
      },
      "data": {
        "x": {
          "$count": 3
        },
        "$count": 24,
        "name": {
          "$count": 3
        },
        "itemStyle": {
          "normal": {
            "color": {
              "$count": 1
            }
          },
          "$count": 5
        },
        "label": {
          "$count": 3,
          "normal": {
            "$count": 3,
            "textStyle": {
              "$count": 1
            },
            "show": {
              "$count": 1
            },
            "position": {
              "$count": 1
            }
          },
          "emphasis": {
            "$count": 1,
            "textStyle": {
              "fontFamily": {
                "$count": 1
              }
            }
          }
        },
        "y": {
          "$count": 1
        },
        "value": {
          "$count": 3
        },
        "symbol": {
          "$count": 3
        },
        "symbolSize": {
          "$count": 1
        },
        "symbolRotate": {
          "$count": 1
        },
        "symbolOffset": {
          "$count": 1
        }
      },
      "label": {
        "normal": {
          "textStyle": {
            "color": {
              "$count": 1
            },
            "$count": 2
          },
          "$count": 12,
          "formatter": {
            "$count": 9
          },
          "show": {
            "$count": 2
          },
          "position": {
            "$count": 5
          }
        },
        "$count": 19,
        "emphasis": {
          "$count": 4,
          "formatter": {
            "$count": 1
          }
        }
      },
      "animationEasingUpdate": {
        "$count": 2
      },
      "animationDurationUpdate": {
        "$count": 2
      },
      "animationEasing": {
        "$count": 3
      },
      "animationDuration": {
        "$count": 4
      },
      "animation": {
        "$count": 7
      },
      "symbolSize": {
        "$count": 9
      },
      "itemStyle": {
        "$count": 4,
        "normal": {
          "shadowOffsetY": {
            "$count": 1
          },
          "opacity": {
            "$count": 1
          },
          "shadowOffsetX": {
            "$count": 1
          },
          "shadowColor": {
            "$count": 1
          },
          "shadowBlur": {
            "$count": 1
          },
          "borderWidth": {
            "$count": 1
          },
          "borderColor": {
            "$count": 2
          },
          "color": {
            "$count": 1
          }
        },
        "emphasis": {
          "color": {
            "$count": 1
          }
        }
      },
      "symbolOffset": {
        "$count": 3
      }
    },
    "animationDurationUpdate": {
      "$count": 22
    },
    "animationDuration": {
      "$count": 30
    }
  },
  "series-gauge": {
    "$count": 1161,
    "detail": {
      "$count": 173,
      "show": {
        "$count": 26
      },
      "width": {
        "$count": 31
      },
      "height": {
        "$count": 22
      },
      "backgroundColor": {
        "$count": 29
      },
      "textStyle": {
        "$count": 44,
        "fontWeight": {
          "$count": 12
        },
        "color": {
          "$count": 12
        },
        "fontStyle": {
          "$count": 12
        },
        "fontFamily": {
          "$count": 9
        },
        "fontSize": {
          "$count": 22
        }
      },
      "offsetCenter": {
        "$count": 55
      },
      "borderWidth": {
        "$count": 14
      },
      "borderColor": {
        "$count": 15
      }
    },
    "itemStyle": {
      "$count": 148,
      "normal": {
        "$count": 46,
        "borderWidth": {
          "$count": 9
        },
        "shadowBlur": {
          "$count": 6
        },
        "shadowColor": {
          "$count": 6
        },
        "shadowOffsetX": {
          "$count": 5
        },
        "shadowOffsetY": {
          "$count": 5
        },
        "opacity": {
          "$count": 9
        },
        "color": {
          "$count": 21
        },
        "borderColor": {
          "$count": 9
        }
      },
      "emphasis": {
        "color": {
          "$count": 11
        },
        "borderColor": {
          "$count": 6
        },
        "borderWidth": {
          "$count": 5
        },
        "shadowBlur": {
          "$count": 5
        },
        "shadowColor": {
          "$count": 5
        },
        "shadowOffsetX": {
          "$count": 4
        },
        "shadowOffsetY": {
          "$count": 4
        },
        "opacity": {
          "$count": 6
        },
        "$count": 25
      }
    },
    "title": {
      "$count": 109,
      "textStyle": {
        "fontFamily": {
          "$count": 2
        },
        "fontStyle": {
          "$count": 2
        },
        "fontSize": {
          "$count": 4
        },
        "$count": 20,
        "fontWeight": {
          "$count": 2
        },
        "color": {
          "$count": 3
        }
      },
      "show": {
        "$count": 10
      },
      "offsetCenter": {
        "$count": 37
      }
    },
    "radius": {
      "$count": 164
    },
    "min": {
      "$count": 83
    },
    "pointer": {
      "$count": 147,
      "show": {
        "$count": 21
      },
      "length": {
        "$count": 19
      },
      "width": {
        "$count": 19
      }
    },
    "markPoint": {
      "$count": 116,
      "symbol": {
        "$count": 28
      },
      "symbolSize": {
        "$count": 12
      },
      "data": {
        "$count": 19,
        "symbolRotate": {
          "$count": 4
        },
        "name": {
          "$count": 11
        },
        "x": {
          "$count": 9
        },
        "y": {
          "$count": 5
        },
        "value": {
          "$count": 15
        },
        "symbolSize": {
          "$count": 11
        },
        "label": {
          "$count": 7,
          "emphasis": {
            "$count": 3
          },
          "normal": {
            "$count": 3,
            "position": {
              "$count": 4
            }
          }
        },
        "symbol": {
          "$count": 9
        },
        "itemStyle": {
          "$count": 13,
          "normal": {
            "$count": 6
          },
          "emphasis": {
            "$count": 3,
            "borderWidth": {
              "$count": 1
            }
          }
        },
        "symbolOffset": {
          "$count": 4
        }
      },
      "itemStyle": {
        "$count": 6,
        "emphasis": {
          "$count": 2,
          "opacity": {
            "$count": 1
          },
          "shadowOffsetY": {
            "$count": 1
          },
          "shadowOffsetX": {
            "$count": 1
          }
        }
      },
      "label": {
        "$count": 14,
        "normal": {
          "$count": 5,
          "textStyle": {
            "$count": 2,
            "color": {
              "$count": 1
            },
            "fontSize": {
              "$count": 1
            }
          },
          "formatter": {
            "$count": 9
          },
          "position": {
            "$count": 5
          },
          "show": {
            "$count": 2
          }
        },
        "emphasis": {
          "$count": 7,
          "position": {
            "$count": 3
          },
          "formatter": {
            "$count": 1
          }
        }
      },
      "symbolRotate": {
        "$count": 9
      },
      "symbolOffset": {
        "$count": 10
      },
      "animation": {
        "$count": 2
      },
      "animationDuration": {
        "$count": 3
      },
      "animationEasingUpdate": {
        "$count": 2
      },
      "animationDurationUpdate": {
        "$count": 3
      },
      "animationEasing": {
        "$count": 1
      }
    },
    "splitLine": {
      "lineStyle": {
        "type": {
          "$count": 8
        },
        "width": {
          "$count": 9
        },
        "color": {
          "$count": 14
        },
        "$count": 36,
        "opacity": {
          "$count": 4
        },
        "shadowOffsetX": {
          "$count": 4
        },
        "shadowOffsetY": {
          "$count": 3
        },
        "shadowBlur": {
          "$count": 3
        },
        "shadowColor": {
          "$count": 2
        }
      },
      "$count": 174,
      "show": {
        "$count": 18
      },
      "length": {
        "$count": 24
      }
    },
    "splitNumber": {
      "$count": 135
    },
    "axisLabel": {
      "$count": 159,
      "textStyle": {
        "$count": 38,
        "fontWeight": {
          "$count": 6
        },
        "fontFamily": {
          "$count": 4
        },
        "fontStyle": {
          "$count": 8
        },
        "color": {
          "$count": 5
        },
        "fontSize": {
          "$count": 12
        }
      },
      "color": {
        "$count": 15
      },
      "formatter": {
        "$count": 61
      },
      "show": {
        "$count": 24
      }
    },
    "axisTick": {
      "lineStyle": {
        "$count": 28,
        "type": {
          "$count": 9
        },
        "color": {
          "$count": 14
        },
        "shadowBlur": {
          "$count": 7
        },
        "width": {
          "$count": 8
        },
        "opacity": {
          "$count": 5
        },
        "shadowOffsetX": {
          "$count": 6
        },
        "shadowColor": {
          "$count": 5
        },
        "shadowOffsetY": {
          "$count": 2
        }
      },
      "$count": 174,
      "show": {
        "$count": 23
      },
      "splitNumber": {
        "$count": 35
      },
      "length": {
        "$count": 26
      }
    },
    "type": {
      "$count": 147
    },
    "axisLine": {
      "$count": 249,
      "lineStyle": {
        "width": {
          "$count": 70,
          "shadowBlur": {
            "$count": 35
          },
          "shadowColor": {
            "$count": 20
          },
          "shadowOffsetX": {
            "$count": 17
          },
          "shadowOffsetY": {
            "$count": 10
          },
          "opacity": {
            "$count": 14
          }
        },
        "color": {
          "$count": 124
        },
        "$count": 86,
        "shadowBlur": {
          "$count": 5
        },
        "shadowColor": {
          "$count": 5
        },
        "shadowOffsetX": {
          "$count": 2
        },
        "shadowOffsetY": {
          "$count": 2
        },
        "opacity": {
          "$count": 2
        }
      },
      "show": {
        "$count": 42
      }
    },
    "startAngle": {
      "$count": 121
    },
    "max": {
      "$count": 67
    },
    "markLine": {
      "$count": 78,
      "symbol": {
        "$count": 8
      },
      "label": {
        "$count": 5,
        "normal": {
          "$count": 6,
          "position": {
            "$count": 2
          },
          "formatter": {
            "$count": 2
          }
        },
        "emphasis": {
          "$count": 4,
          "formatter": {
            "$count": 3
          },
          "position": {
            "$count": 2
          },
          "show": {
            "$count": 1
          }
        }
      },
      "lineStyle": {
        "$count": 4,
        "normal": {
          "$count": 1,
          "color": {
            "$count": 1
          }
        },
        "emphasis": {
          "$count": 1
        }
      },
      "precision": {
        "$count": 5
      },
      "symbolSize": {
        "$count": 6
      },
      "data": {
        "0": {
          "label": {
            "emphasis": {
              "formatter": {
                "$count": 1
              }
            },
            "normal": {
              "formatter": {
                "$count": 2
              }
            }
          },
          "$count": 2,
          "lineStyle": {
            "normal": {
              "color": {
                "$count": 1
              },
              "$count": 1
            },
            "$count": 3
          },
          "y": {
            "$count": 1
          },
          "value": {
            "$count": 1
          }
        },
        "1": {
          "label": {
            "emphasis": {
              "formatter": {
                "$count": 1
              }
            },
            "normal": {
              "formatter": {
                "$count": 1
              }
            }
          },
          "$count": 1,
          "lineStyle": {
            "emphasis": {
              "type": {
                "$count": 1
              }
            }
          }
        },
        "$count": 6
      }
    },
    "clockwise": {
      "$count": 107
    },
    "name": {
      "$count": 96
    },
    "animation": {
      "$count": 25
    },
    "endAngle": {
      "$count": 74
    },
    "animationEasingUpdate": {
      "$count": 17
    },
    "animationDurationUpdate": {
      "$count": 21
    },
    "animationEasing": {
      "$count": 15
    },
    "animationDuration": {
      "$count": 23
    }
  },
  "dataZoom-slider": {
    "$count": 910,
    "end": {
      "$count": 48
    },
    "start": {
      "$count": 121
    },
    "xAxisIndex": {
      "$count": 104
    },
    "type": {
      "$count": 335
    },
    "show": {
      "$count": 114
    },
    "realtime": {
      "$count": 173
    },
    "zoomLock": {
      "$count": 84
    },
    "backgroundColor": {
      "$count": 165
    },
    "filterMode": {
      "$count": 95
    },
    "showDataShadow": {
      "$count": 96
    },
    "showDetail": {
      "$count": 111
    },
    "bottom": {
      "$count": 76
    },
    "orient": {
      "$count": 89
    },
    "throttle": {
      "$count": 78
    },
    "zlevel": {
      "$count": 63
    },
    "z": {
      "$count": 56
    },
    "dataBackgroundColor": {
      "$count": 108
    },
    "handleColor": {
      "$count": 96
    },
    "fillerColor": {
      "$count": 91
    },
    "labelFormatter": {
      "$count": 169
    },
    "handleSize": {
      "$count": 130
    },
    "labelPrecision": {
      "$count": 119
    },
    "yAxisIndex": {
      "$count": 64
    },
    "startValue": {
      "$count": 98
    },
    "angleAxisIndex": {
      "$count": 50
    },
    "top": {
      "$count": 83
    },
    "left": {
      "$count": 85
    },
    "right": {
      "$count": 46
    },
    "textStyle": {
      "$count": 97,
      "color": {
        "$count": 20
      },
      "fontStyle": {
        "$count": 12
      },
      "fontWeight": {
        "$count": 14
      },
      "fontFamily": {
        "$count": 10
      },
      "fontSize": {
        "$count": 17
      }
    },
    "endValue": {
      "$count": 45
    },
    "radiusAxisIndex": {
      "$count": 52
    }
  },
  "timeline": {
    "$count": 4025,
    "itemStyle": {
      "$count": 128,
      "normal": {
        "$count": 33,
        "color": {
          "$count": 25
        },
        "borderColor": {
          "$count": 13
        },
        "borderWidth": {
          "$count": 13
        },
        "shadowBlur": {
          "$count": 6
        },
        "shadowColor": {
          "$count": 5
        },
        "shadowOffsetY": {
          "$count": 6
        },
        "opacity": {
          "$count": 9
        },
        "shadowOffsetX": {
          "$count": 5
        }
      },
      "emphasis": {
        "$count": 14,
        "color": {
          "$count": 5
        },
        "shadowColor": {
          "$count": 2
        },
        "opacity": {
          "$count": 2
        }
      }
    },
    "symbolSize": {
      "$count": 125
    },
    "checkpointStyle": {
      "$count": 88,
      "symbolOffset": {
        "$count": 12
      },
      "symbolSize": {
        "$count": 31
      },
      "symbol": {
        "$count": 45
      },
      "borderWidth": {
        "$count": 9
      },
      "animationEasing: 'quinticInOut'": {
        "$count": 10
      },
      "symbolRotate": {
        "$count": 16
      },
      "borderColor": {
        "$count": 6
      },
      "animation": {
        "$count": 14
      },
      "animationDuration": {
        "$count": 12
      },
      "color": {
        "$count": 10
      }
    },
    "symbol": {
      "$count": 184
    },
    "symbolOffset": {
      "$count": 68
    },
    "label": {
      "position": {
        "$count": 87
      },
      "normal": {
        "formatter": {
          "$count": 67
        },
        "$count": 43,
        "textStyle": {
          "$count": 19,
          "color": {
            "$count": 6
          },
          "fontStyle": {
            "$count": 5
          },
          "fontWeight": {
            "$count": 4
          },
          "fontFamily": {
            "$count": 3
          },
          "fontSize": {
            "$count": 7
          }
        },
        "rotate": {
          "$count": 17
        },
        "show": {
          "$count": 14
        },
        "interval": {
          "$count": 15
        }
      },
      "emphasis": {
        "formatter": {
          "$count": 17
        },
        "$count": 32,
        "show": {
          "$count": 4
        },
        "textStyle": {
          "$count": 2,
          "color": {
            "$count": 2
          }
        },
        "rotate": {
          "$count": 1
        }
      },
      "$count": 155
    },
    "controlStyle": {
      "position": {
        "$count": 28
      },
      "showPlayBtn": {
        "$count": 19
      },
      "$count": 78,
      "show": {
        "$count": 12
      },
      "showPrevBtn": {
        "$count": 7
      },
      "showNextBtn": {
        "$count": 4
      },
      "itemSize": {
        "$count": 13
      },
      "itemGap": {
        "$count": 12
      },
      "playIcon": {
        "$count": 25
      },
      "stopIcon": {
        "$count": 9
      },
      "normal": {
        "$count": 10,
        "borderWidth": {
          "$count": 2
        },
        "borderColor": {
          "$count": 3
        },
        "color": {
          "$count": 3
        }
      },
      "emphasis": {
        "$count": 5,
        "color": {
          "$count": 2
        }
      },
      "prevIcon": {
        "$count": 10
      },
      "nextIcon": {
        "$count": 8
      }
    },
    "show": {
      "$count": 246
    },
    "axisType": {
      "$count": 177
    },
    "autoPlay": {
      "$count": 86
    },
    "loop": {
      "$count": 67
    },
    "type": {
      "$count": 171
    },
    "currentIndex": {
      "$count": 103
    },
    "data": {
      "$count": 140
    },
    "rewind": {
      "$count": 75
    },
    "playInterval": {
      "$count": 83
    },
    "realtime: true,": {
      "$count": 81
    },
    "orient": {
      "$count": 77
    },
    "inverse": {
      "$count": 70
    },
    "controlPosition": {
      "$count": 89
    },
    "symbolRotate": {
      "$count": 73
    },
    "top": {
      "$count": 35
    },
    "left": {
      "$count": 70
    },
    "lineStyle": {
      "$count": 94,
      "type": {
        "$count": 16
      },
      "color": {
        "$count": 11
      },
      "opacity": {
        "$count": 13
      },
      "width": {
        "$count": 11
      },
      "shadowBlur": {
        "$count": 12
      },
      "shadowColor": {
        "$count": 9
      },
      "shadowOffsetX": {
        "$count": 6
      },
      "shadowOffsetY": {
        "$count": 5
      },
      "show": {
        "$count": 11
      }
    },
    "zlevel": {
      "$count": 53
    },
    "z": {
      "$count": 35
    },
    "padding": {
      "$count": 48
    },
    "right": {
      "$count": 31
    },
    "bottom": {
      "$count": 41
    }
  },
  "parallelAxis": {
    "$count": 2817,
    "axisLabel": {
      "formatter": {
        "$count": 11
      },
      "$count": 22,
      "show": {
        "$count": 3
      },
      "margin": {
        "$count": 2
      },
      "rotate": {
        "$count": 6
      },
      "interval": {
        "$count": 1
      },
      "textStyle": {
        "color": {
          "$count": 2
        },
        "$count": 1,
        "fontSize": {
          "$count": 1
        }
      },
      "inside": {
        "$count": 1
      }
    },
    "parallelIndex": {
      "$count": 43
    },
    "dim": {
      "$count": 49
    },
    "type": {
      "$count": 22
    },
    "data": {
      "$count": 14,
      "textStyle": {
        "color": {
          "$count": 1
        },
        "baseline": {
          "$count": 1
        },
        "align": {
          "$count": 1
        },
        "$count": 1
      },
      "value": {
        "$count": 4
      }
    },
    "axisTick": {
      "$count": 19,
      "lineStyle": {
        "$count": 2,
        "color": {
          "$count": 2
        },
        "width": {
          "$count": 1
        },
        "type": {
          "$count": 1
        },
        "shadowBlur": {
          "$count": 1
        },
        "opacity": {
          "$count": 1
        },
        "shadowOffsetY": {
          "$count": 1
        }
      },
      "inside": {
        "$count": 2
      },
      "interval": {
        "$count": 2
      }
    },
    "min": {
      "$count": 9
    },
    "max": {
      "$count": 5
    },
    "scale": {
      "$count": 10
    },
    "splitNumber": {
      "$count": 9
    },
    "interval": {
      "$count": 11
    },
    "name": {
      "$count": 12
    },
    "axisLine": {
      "$count": 27,
      "lineStyle": {
        "$count": 9,
        "color": {
          "$count": 1
        }
      },
      "show": {
        "$count": 2
      }
    },
    "areaSelectStyle": {
      "$count": 37,
      "width": {
        "$count": 4
      },
      "opacity": {
        "$count": 2
      },
      "borderWidth": {
        "$count": 1
      },
      "borderColor": {
        "$count": 2
      },
      "color": {
        "$count": 1
      }
    },
    "nameLocation": {
      "$count": 10
    },
    "boundaryGap": {
      "$count": 15
    },
    "nameTextStyle": {
      "$count": 14,
      "color": {
        "$count": 2
      }
    },
    "inverse": {
      "$count": 9
    },
    "nameGap": {
      "$count": 8
    }
  },
  "textStyle": {
    "$count": 3717,
    "fontFamily": {
      "$count": 207
    },
    "fontWeight": {
      "$count": 209
    },
    "color": {
      "$count": 411
    },
    "fontStyle": {
      "$count": 254
    },
    "fontSize": {
      "$count": 210
    }
  },
  "series-candlestick": {
    "type": {
      "$count": 78
    },
    "coordinateSystem": {
      "$count": 52
    },
    "xAxisIndex": {
      "$count": 38
    },
    "legendHoverLink": {
      "$count": 36
    },
    "layout": {
      "$count": 35
    },
    "itemStyle": {
      "normal": {
        "$count": 39,
        "color": {
          "$count": 65
        },
        "borderWidth": {
          "$count": 14
        },
        "borderColor": {
          "$count": 20
        },
        "color0": {
          "$count": 37
        },
        "shadowBlur": {
          "$count": 9
        },
        "shadowColor": {
          "$count": 9
        },
        "shadowOffsetX": {
          "$count": 10
        },
        "shadowOffsetY": {
          "$count": 12
        },
        "opacity": {
          "$count": 15
        },
        "borderColor0": {
          "$count": 6
        }
      },
      "$count": 64,
      "emphasis": {
        "$count": 26,
        "color": {
          "$count": 6
        },
        "color0": {
          "$count": 3
        },
        "borderColor": {
          "$count": 1
        }
      }
    },
    "$count": 860,
    "markLine": {
      "animationEasingUpdate": {
        "$count": 1
      },
      "label": {
        "normal": {
          "position": {
            "$count": 1
          },
          "$count": 4,
          "show": {
            "$count": 1
          }
        },
        "$count": 5,
        "emphasis": {
          "$count": 3,
          "formatter": {
            "$count": 1
          }
        }
      },
      "data": {
        "0": {
          "label": {
            "normal": {
              "position": {
                "$count": 2
              },
              "formatter": {
                "$count": 1
              }
            },
            "$count": 1
          },
          "$count": 8,
          "valueIndex": {
            "$count": 5
          },
          "coord": {
            "$count": 12
          },
          "value": {
            "$count": 3
          },
          "y": {
            "$count": 2
          },
          "x": {
            "$count": 4
          },
          "symbol": {
            "$count": 1
          },
          "lineStyle": {
            "$count": 2
          },
          "valueDim": {
            "$count": 1
          }
        },
        "1": {
          "label": {
            "normal": {
              "position": {
                "$count": 1
              },
              "formatter": {
                "$count": 1
              }
            }
          },
          "$count": 4,
          "valueIndex": {
            "$count": 1
          },
          "coord": {
            "$count": 1
          },
          "x": {
            "$count": 1
          },
          "symbolSize": {
            "$count": 2
          },
          "symbol": {
            "$count": 1
          }
        },
        "$count": 23
      },
      "$count": 51,
      "symbol": {
        "$count": 19
      },
      "symbolSize": {
        "$count": 12
      },
      "lineStyle": {
        "$count": 8,
        "normal": {
          "$count": 3,
          "type": {
            "$count": 1
          }
        }
      },
      "precision": {
        "$count": 11
      },
      "animation": {
        "$count": 3
      },
      "animationDuration": {
        "$count": 1
      }
    },
    "data": {
      "$count": 65,
      "value": {
        "$count": 28
      },
      "itemStyle": {
        "$count": 11,
        "color": {
          "$count": 10
        },
        "normal": {
          "$count": 10
        },
        "color0": {
          "$count": 6
        },
        "borderColor": {
          "$count": 7
        },
        "shadowBlur": {
          "$count": 5
        },
        "borderWidth": {
          "$count": 4
        },
        "shadowColor": {
          "$count": 4
        },
        "opacity": {
          "$count": 4
        },
        "shadowOffsetY": {
          "$count": 2
        },
        "borderColor0": {
          "$count": 5
        },
        "emphasis": {
          "$count": 6
        },
        "shadowOffsetX": {
          "$count": 2
        }
      },
      "name": {
        "$count": 26
      }
    },
    "animationDuration": {
      "$count": 9
    },
    "animationEasing": {
      "$count": 11
    },
    "hoverAnimation": {
      "$count": 27
    },
    "name": {
      "$count": 44
    },
    "yAxisIndex": {
      "$count": 29
    },
    "markPoint": {
      "label": {
        "normal": {
          "position": {
            "$count": 12
          },
          "formatter": {
            "$count": 11
          },
          "show": {
            "$count": 5
          },
          "textStyle": {
            "$count": 3,
            "color": {
              "$count": 2
            },
            "fontWeight": {
              "$count": 1
            },
            "fontSize": {
              "$count": 1
            }
          },
          "$count": 2
        },
        "$count": 13,
        "emphasis": {
          "show": {
            "$count": 1
          },
          "position": {
            "$count": 3
          },
          "formatter": {
            "$count": 1
          },
          "textStyle": {
            "$count": 1
          },
          "$count": 5
        }
      },
      "data": {
        "label": {
          "normal": {
            "position": {
              "$count": 3
            },
            "$count": 2,
            "show": {
              "$count": 1
            },
            "textStyle": {
              "$count": 1
            }
          },
          "$count": 3
        },
        "symbol": {
          "$count": 13
        },
        "coord": {
          "$count": 20
        },
        "valueIndex": {
          "$count": 11
        },
        "name": {
          "$count": 11
        },
        "symbolRotate": {
          "$count": 3
        },
        "symbolSize": {
          "$count": 6
        },
        "value": {
          "$count": 10
        },
        "y": {
          "$count": 3
        },
        "x": {
          "$count": 7
        },
        "symbolOffset": {
          "$count": 6
        },
        "itemStyle": {
          "normal": {
            "$count": 1
          },
          "$count": 4
        },
        "$count": 31
      },
      "$count": 77,
      "symbol": {
        "$count": 28
      },
      "symbolRotate": {
        "$count": 12
      },
      "itemStyle": {
        "$count": 12,
        "normal": {
          "color": {
            "$count": 2
          },
          "$count": 3
        },
        "emphasis": {
          "$count": 1
        }
      },
      "symbolOffset": {
        "$count": 13
      },
      "symbolSize": {
        "$count": 10
      },
      "animation": {
        "$count": 2
      },
      "animationDurationUpdate": {
        "$count": 1
      }
    },
    "z": {
      "$count": 1
    },
    "zlevel": {
      "$count": 2
    }
  },
  "series-lines": {
    "$count": 1436,
    "effect": {
      "$count": 153,
      "symbol": {
        "$count": 127
      },
      "trailLength": {
        "$count": 54
      },
      "show": {
        "$count": 51
      },
      "period": {
        "$count": 57
      },
      "color": {
        "$count": 37
      },
      "symbolSize": {
        "$count": 37
      }
    },
    "label": {
      "$count": 69,
      "normal": {
        "$count": 24,
        "formatter": {
          "$count": 24
        },
        "position": {
          "$count": 16
        },
        "show": {
          "$count": 6
        }
      }
    },
    "geoIndex": {
      "$count": 53
    },
    "type": {
      "$count": 192
    },
    "name": {
      "$count": 56
    },
    "coordinateSystem": {
      "$count": 94
    },
    "xAxisIndex": {
      "$count": 45
    },
    "yAxisIndex": {
      "$count": 30
    },
    "lineStyle": {
      "$count": 107,
      "emphasis": {
        "$count": 22,
        "color": {
          "$count": 6
        },
        "shadowOffsetX": {
          "$count": 1
        },
        "opacity": {
          "$count": 2
        },
        "shadowBlur": {
          "$count": 1
        },
        "shadowOffsetY": {
          "$count": 1
        },
        "type": {
          "$count": 1
        }
      },
      "normal": {
        "type": {
          "$count": 24
        },
        "$count": 48,
        "color": {
          "$count": 38
        },
        "opacity": {
          "$count": 14
        },
        "shadowColor": {
          "$count": 9
        },
        "shadowBlur": {
          "$count": 11
        },
        "width": {
          "$count": 19
        },
        "shadowOffsetX": {
          "$count": 7
        },
        "shadowOffsetY": {
          "$count": 5
        }
      }
    },
    "markPoint": {
      "symbol": {
        "$count": 27
      },
      "symbolRotate": {
        "$count": 9
      },
      "symbolOffset": {
        "$count": 7
      },
      "$count": 86,
      "label": {
        "normal": {
          "position": {
            "$count": 3
          },
          "formatter": {
            "$count": 6
          },
          "$count": 1,
          "textStyle": {
            "$count": 1,
            "color": {
              "$count": 2
            },
            "fontSize": {
              "$count": 1
            },
            "fontFamily": {
              "$count": 1
            },
            "fontWeight": {
              "$count": 1
            },
            "fontStyle": {
              "$count": 1
            }
          },
          "show": {
            "$count": 1
          }
        },
        "$count": 5,
        "emphasis": {
          "formatter": {
            "$count": 1
          },
          "$count": 2
        }
      },
      "data": {
        "label": {
          "normal": {
            "position": {
              "$count": 1
            }
          }
        },
        "$count": 9,
        "name": {
          "$count": 1
        },
        "x": {
          "$count": 1
        },
        "y": {
          "$count": 1
        },
        "symbolSize": {
          "$count": 2
        },
        "symbolRotate": {
          "$count": 1
        },
        "itemStyle": {
          "normal": {
            "$count": 2
          }
        }
      },
      "symbolSize": {
        "$count": 14
      },
      "itemStyle": {
        "$count": 4,
        "normal": {
          "shadowColor": {
            "$count": 2
          },
          "opacity": {
            "$count": 2
          },
          "borderColor": {
            "$count": 2
          },
          "color": {
            "$count": 1
          },
          "borderWidth": {
            "$count": 1
          },
          "shadowBlur": {
            "$count": 1
          }
        },
        "emphasis": {
          "opacity": {
            "$count": 1
          }
        }
      },
      "animation": {
        "$count": 5
      },
      "animationDuration": {
        "$count": 4
      },
      "animationEasing": {
        "$count": 3
      },
      "animationEasingUpdate": {
        "$count": 3
      },
      "animationDurationUpdate": {
        "$count": 3
      }
    },
    "animationEasingUpdate": {
      "$count": 17
    },
    "data": {
      "0": {
        "$count": 56,
        "name": {
          "$count": 20
        },
        "lineStyle": {
          "$count": 18,
          "emphasis": {
            "$count": 4,
            "curveness": {
              "$count": 1
            }
          },
          "normal": {
            "$count": 6,
            "curveness": {
              "$count": 6
            },
            "opacity": {
              "$count": 2
            },
            "width": {
              "$count": 1
            },
            "shadowBlur": {
              "$count": 2
            }
          }
        },
        "value": {
          "$count": 14
        },
        "coord": {
          "$count": 34
        }
      },
      "1": {
        "$count": 19,
        "coord": {
          "$count": 10
        },
        "name": {
          "$count": 6
        },
        "lineStyle": {
          "normal": {
            "$count": 1
          },
          "$count": 1
        }
      },
      "$count": 97
    },
    "markLine": {
      "$count": 102,
      "symbol": {
        "$count": 20
      },
      "label": {
        "normal": {
          "formatter": {
            "$count": 1
          },
          "$count": 1,
          "position": {
            "$count": 1
          }
        },
        "$count": 8,
        "emphasis": {
          "formatter": {
            "$count": 1
          }
        }
      },
      "lineStyle": {
        "normal": {
          "shadowBlur": {
            "$count": 2
          },
          "width": {
            "$count": 3
          },
          "$count": 5,
          "curveness": {
            "$count": 4
          },
          "type": {
            "$count": 3
          },
          "color": {
            "$count": 1
          }
        },
        "$count": 14,
        "emphasis": {
          "$count": 1,
          "color": {
            "$count": 1
          }
        }
      },
      "animation": {
        "$count": 12
      },
      "data": {
        "0": {
          "label": {
            "normal": {
              "position": {
                "$count": 1
              }
            },
            "$count": 1
          },
          "lineStyle": {
            "$count": 6,
            "emphasis": {
              "$count": 2
            },
            "normal": {
              "$count": 3
            }
          },
          "$count": 6,
          "x": {
            "$count": 10
          },
          "value": {
            "$count": 8
          },
          "symbolOffset": {
            "$count": 3
          },
          "symbol": {
            "$count": 8
          },
          "y": {
            "$count": 6
          },
          "symbolSize": {
            "$count": 1
          },
          "symbolRotate": {
            "$count": 2
          }
        },
        "1": {
          "label": {
            "normal": {
              "position": {
                "$count": 1
              }
            }
          },
          "$count": 3
        },
        "$count": 25
      },
      "animationDuration": {
        "$count": 5
      },
      "animationEasingUpdate": {
        "$count": 2
      },
      "animationDurationUpdate": {
        "$count": 3
      },
      "animationEasing": {
        "$count": 2
      },
      "precision": {
        "$count": 7
      },
      "symbolSize": {
        "$count": 3
      }
    },
    "animation": {
      "$count": 39
    },
    "animationDuration": {
      "$count": 22
    },
    "animationEasing": {
      "$count": 14
    },
    "animationDurationUpdate": {
      "$count": 14
    },
    "zlevel": {
      "$count": 4
    },
    "z": {
      "$count": 2
    }
  },
  "series-boxplot": {
    "$count": 794,
    "data": {
      "$count": 38,
      "name": {
        "$count": 8
      },
      "value": {
        "$count": 8
      },
      "itemStyle": {
        "$count": 5,
        "shadowBlur": {
          "$count": 1
        }
      }
    },
    "animationEasing": {
      "$count": 6
    },
    "type": {
      "$count": 27
    },
    "markPoint": {
      "label": {
        "normal": {
          "formatter": {
            "$count": 2
          },
          "position": {
            "$count": 3
          },
          "$count": 1,
          "show": {
            "$count": 1
          },
          "textStyle": {
            "$count": 1,
            "color": {
              "$count": 1
            },
            "fontStyle": {
              "$count": 1
            }
          }
        },
        "$count": 1
      },
      "data": {
        "label": {
          "normal": {
            "position": {
              "$count": 1
            }
          }
        },
        "coord": {
          "$count": 2
        },
        "valueIndex": {
          "$count": 1
        },
        "$count": 2,
        "valueDim": {
          "$count": 1
        }
      },
      "$count": 14,
      "symbol": {
        "$count": 3
      },
      "symbolSize": {
        "$count": 2
      },
      "symbolRotate": {
        "$count": 1
      },
      "symbolOffset": {
        "$count": 1
      }
    },
    "markLine": {
      "label": {
        "normal": {
          "position": {
            "$count": 1
          }
        },
        "emphasis": {
          "formatter": {
            "$count": 1
          }
        }
      },
      "data": {
        "0": {
          "label": {
            "normal": {
              "position": {
                "$count": 3
              }
            },
            "emphasis": {
              "formatter": {
                "$count": 1
              }
            }
          }
        },
        "1": {
          "label": {
            "normal": {
              "position": {
                "$count": 2
              }
            }
          }
        },
        "$count": 2
      },
      "$count": 16,
      "symbol": {
        "$count": 2
      },
      "lineStyle": {
        "normal": {
          "type": {
            "$count": 1
          },
          "curveness": {
            "$count": 1
          }
        },
        "$count": 1
      },
      "symbolSize": {
        "$count": 1
      }
    },
    "layout": {
      "$count": 16
    },
    "coordinateSystem": {
      "$count": 21
    },
    "itemStyle": {
      "$count": 28,
      "normal": {
        "shadowBlur": {
          "$count": 8
        },
        "$count": 10,
        "color": {
          "$count": 9
        },
        "shadowColor": {
          "$count": 3
        },
        "opacity": {
          "$count": 4
        },
        "shadowOffsetY": {
          "$count": 3
        },
        "shadowOffsetX": {
          "$count": 4
        },
        "borderWidth": {
          "$count": 6
        },
        "borderColor": {
          "$count": 7
        }
      },
      "emphasis": {
        "shadowOffsetX": {
          "$count": 1
        },
        "color": {
          "$count": 1
        },
        "$count": 4
      }
    },
    "boxWidth": {
      "$count": 16
    },
    "legendHoverLink": {
      "$count": 21
    },
    "xAxisIndex": {
      "$count": 13
    },
    "name": {
      "$count": 11
    },
    "yAxisIndex": {
      "$count": 7
    },
    "hoverAnimation": {
      "$count": 10
    },
    "animationDuration": {
      "$count": 6
    },
    "z": {
      "$count": 1
    }
  },
  "series-heatmap": {
    "$count": 1010,
    "type": {
      "$count": 113
    },
    "name": {
      "$count": 68
    },
    "coordinateSystem": {
      "$count": 88
    },
    "xAxisIndex": {
      "$count": 47
    },
    "yAxisIndex": {
      "$count": 33
    },
    "geoIndex": {
      "$count": 68
    },
    "blurSize": {
      "$count": 71
    },
    "data": {
      "$count": 114,
      "name": {
        "$count": 67
      },
      "value": {
        "$count": 77
      },
      "itemStyle": {
        "normal": {
          "color": {
            "$count": 17
          },
          "borderColor": {
            "$count": 10
          },
          "$count": 25,
          "borderWidth": {
            "$count": 6
          },
          "shadowBlur": {
            "$count": 5
          },
          "shadowColor": {
            "$count": 3
          },
          "shadowOffsetX": {
            "$count": 5
          },
          "opacity": {
            "$count": 5
          }
        },
        "$count": 39,
        "emphasis": {
          "$count": 12,
          "opacity": {
            "$count": 3
          },
          "shadowOffsetX": {
            "$count": 1
          },
          "shadowOffsetY": {
            "$count": 1
          },
          "shadowColor": {
            "$count": 4
          },
          "shadowBlur": {
            "$count": 6
          },
          "borderWidth": {
            "$count": 2
          },
          "borderColor": {
            "$count": 5
          },
          "color": {
            "$count": 8
          }
        }
      },
      "label": {
        "normal": {
          "position": {
            "$count": 6
          },
          "$count": 30,
          "show": {
            "$count": 10
          },
          "textStyle": {
            "$count": 7,
            "color": {
              "$count": 1
            }
          }
        },
        "$count": 58,
        "emphasis": {
          "$count": 22,
          "show": {
            "$count": 1
          },
          "position": {
            "$count": 2
          },
          "textStyle": {
            "$count": 1
          }
        }
      }
    },
    "markLine": {
      "symbolSize": {
        "$count": 1
      }
    },
    "markPoint": {
      "itemStyle": {
        "$count": 1
      },
      "symbolRotate": {
        "$count": 1
      },
      "$count": 2
    }
  },
  "series-parallel": {
    "$count": 792,
    "type": {
      "$count": 17
    },
    "coordinateSystem": {
      "$count": 14
    },
    "lineStyle": {
      "$count": 14,
      "normal": {
        "color": {
          "$count": 2
        },
        "$count": 4,
        "width": {
          "$count": 2
        }
      },
      "emphasis": {
        "$count": 2,
        "type": {
          "$count": 1
        },
        "shadowBlur": {
          "$count": 1
        },
        "shadowColor": {
          "$count": 1
        },
        "opacity": {
          "$count": 1
        }
      }
    },
    "animationEasing": {
      "$count": 3
    },
    "data": {
      "$count": 18,
      "value": {
        "$count": 6
      },
      "lineStyle": {
        "$count": 4,
        "width": {
          "$count": 2
        },
        "type": {
          "$count": 2
        },
        "shadowBlur": {
          "$count": 1
        },
        "shadowColor": {
          "$count": 1
        },
        "shadowOffsetY": {
          "$count": 1
        },
        "opacity": {
          "$count": 1
        },
        "emphasis": {
          "$count": 3
        },
        "normal": {
          "$count": 2
        },
        "color": {
          "$count": 1
        }
      },
      "name": {
        "$count": 3
      }
    },
    "animation": {
      "$count": 3
    },
    "parallelIndex": {
      "$count": 10
    },
    "name": {
      "$count": 6
    },
    "inactiveOpacity": {
      "$count": 5
    },
    "activeOpacity": {
      "$count": 7
    },
    "animationDuration": {
      "$count": 2
    },
    "animationDurationUpdate": {
      "$count": 1
    },
    "animationEasingUpdate": {
      "$count": 1
    }
  },
  "series-sankey": {
    "$count": 497,
    "lineStyle": {
      "$count": 11,
      "normal": {
        "color": {
          "$count": 7
        },
        "opacity": {
          "$count": 1
        },
        "shadowColor": {
          "$count": 1
        },
        "shadowBlur": {
          "$count": 1
        },
        "$count": 2
      },
      "emphasis": {
        "$count": 2,
        "color": {
          "$count": 2
        }
      }
    },
    "itemStyle": {
      "$count": 25,
      "normal": {
        "color": {
          "$count": 19
        },
        "borderColor": {
          "$count": 10
        },
        "borderWidth": {
          "$count": 7
        },
        "shadowBlur": {
          "$count": 6
        },
        "shadowColor": {
          "$count": 4
        },
        "shadowOffsetX": {
          "$count": 5
        },
        "shadowOffsetY": {
          "$count": 3
        },
        "opacity": {
          "$count": 8
        },
        "$count": 9
      },
      "emphasis": {
        "$count": 8,
        "borderColor": {
          "$count": 1
        },
        "color": {
          "$count": 3
        }
      }
    },
    "type": {
      "$count": 15
    },
    "data": {
      "$count": 45,
      "value": {
        "$count": 14
      },
      "name": {
        "$count": 9
      },
      "itemStyle": {
        "normal": {
          "color": {
            "$count": 15
          },
          "borderColor": {
            "$count": 8
          },
          "borderWidth": {
            "$count": 8
          },
          "shadowBlur": {
            "$count": 4
          },
          "shadowColor": {
            "$count": 4
          },
          "shadowOffsetX": {
            "$count": 4
          },
          "shadowOffsetY": {
            "$count": 2
          },
          "opacity": {
            "$count": 2
          },
          "$count": 8
        },
        "$count": 16,
        "emphasis": {
          "color": {
            "$count": 3
          },
          "borderColor": {
            "$count": 2
          },
          "opacity": {
            "$count": 2
          },
          "shadowOffsetY": {
            "$count": 1
          },
          "shadowOffsetX": {
            "$count": 1
          },
          "shadowBlur": {
            "$count": 1
          },
          "borderWidth": {
            "$count": 1
          }
        }
      },
      "label": {
        "normal": {
          "$count": 2,
          "position": {
            "$count": 2
          },
          "show": {
            "$count": 1
          },
          "textStyle": {
            "color": {
              "$count": 2
            },
            "fontStyle": {
              "$count": 1
            }
          }
        },
        "$count": 10
      }
    },
    "top": {
      "$count": 6
    },
    "layoutIterations": {
      "$count": 24
    },
    "nodes": {
      "$count": 34
    },
    "links": {
      "$count": 35,
      "lineStyle": {
        "normal": {
          "$count": 13,
          "color": {
            "$count": 22
          },
          "opacity": {
            "$count": 9
          },
          "curveness": {
            "$count": 5
          },
          "shadowBlur": {
            "$count": 6
          },
          "shadowColor": {
            "$count": 4
          },
          "shadowOffsetX": {
            "$count": 3
          },
          "shadowOffsetY": {
            "$count": 3
          }
        },
        "emphasis": {
          "$count": 7,
          "color": {
            "$count": 7
          },
          "opacity": {
            "$count": 3
          },
          "curveness": {
            "$count": 2
          },
          "shadowBlur": {
            "$count": 1
          }
        },
        "$count": 18
      },
      "value": {
        "$count": 14
      },
      "source": {
        "$count": 16
      },
      "target": {
        "$count": 8
      }
    },
    "label": {
      "normal": {
        "formatter": {
          "$count": 7
        },
        "$count": 7,
        "textStyle": {
          "$count": 4,
          "color": {
            "$count": 3
          }
        },
        "show": {
          "$count": 2
        },
        "position": {
          "$count": 3
        }
      },
      "$count": 23,
      "emphasis": {
        "$count": 1
      }
    },
    "nodeWidth": {
      "$count": 14
    },
    "bottom": {
      "$count": 4
    },
    "nodeGap": {
      "$count": 13
    },
    "edges": {
      "$count": 18
    },
    "right": {
      "$count": 4
    },
    "left": {
      "$count": 8
    },
    "width": {
      "$count": 4
    },
    "height": {
      "$count": 1
    },
    "z": {
      "$count": 3
    },
    "zlevel": {
      "$count": 4
    },
    "animation": {
      "$count": 5
    },
    "animationDuration": {
      "$count": 2
    },
    "animationEasing": {
      "$count": 2
    },
    "animationDurationUpdate": {
      "$count": 1
    },
    "animationEasingUpdate": {
      "$count": 1
    }
  }
};
run(res[0]);

function run(rawData) {
  const dataWrap = prepareData(rawData);
  initChart(dataWrap.seriesData, dataWrap.maxDepth);
}
function prepareData(rawData) {
  const seriesData = [];
  let maxDepth = 0;
  function convert(source, basePath, depth) {
    if (source == null) {
      return;
    }
    if (maxDepth > 5) {
      return;
    }
    maxDepth = Math.max(depth, maxDepth);
    seriesData.push({
      id: basePath,
      value: source.$count,
      depth: depth,
      index: seriesData.length
    });
    for (var key in source) {
      if (source.hasOwnProperty(key) && !key.match(/^\$/)) {
        var path = basePath + '.' + key;
        convert(source[key], path, depth + 1);
      }
    }
  }
  convert(rawData, 'option', 0);
  return {
    seriesData: seriesData,
    maxDepth: maxDepth
  };
}
function initChart(seriesData, maxDepth) {
  var displayRoot = stratify();
  function stratify() {
    return d3
      .stratify()
      .parentId(function (d) {
        return d.id.substring(0, d.id.lastIndexOf('.'));
      })(seriesData)
      .sum(function (d) {
        return d.value || 0;
      })
      .sort(function (a, b) {
        return b.value - a.value;
      });
  }
  function overallLayout(params, api) {
    var context = params.context;
    d3
      .pack()
      .size([api.getWidth() - 2, api.getHeight() - 2])
      .padding(3)(displayRoot);
    context.nodes = {};
    displayRoot.descendants().forEach(function (node, index) {
      context.nodes[node.id] = node;
    });
  }
  function renderItem(params, api) {
    var context = params.context;
    // Only do that layout once in each time `setOption` called.
    if (!context.layout) {
      context.layout = true;
      overallLayout(params, api);
    }
    var nodePath = api.value('id');
    var node = context.nodes[nodePath];
    if (!node) {
      // Reder nothing.
      return;
    }
    var isLeaf = !node.children || !node.children.length;
    var focus = new Uint32Array(
      node.descendants().map(function (node) {
        return node.data.index;
      })
    );
    var nodeName = isLeaf
      ? nodePath
          .slice(nodePath.lastIndexOf('.') + 1)
          .split(/(?=[A-Z][^A-Z])/g)
          .join('\n')
      : '';
    var z2 = api.value('depth') * 2;
    return {
      type: 'circle',
      focus: focus,
      shape: {
        cx: node.x,
        cy: node.y,
        r: node.r
      },
      transition: ['shape'],
      z2: z2,
      textContent: {
        type: 'text',
        style: {
          // transition: isLeaf ? 'fontSize' : null,
          text: nodeName,
          fontFamily: 'Arial',
          width: node.r * 1.3,
          overflow: 'truncate',
          fontSize: node.r / 3
        },
        emphasis: {
          style: {
            overflow: null,
            fontSize: Math.max(node.r / 3, 12)
          }
        }
      },
      textConfig: {
        position: 'inside'
      },
      style: {
        fill: api.visual('color')
      },
      emphasis: {
        style: {
          fontFamily: 'Arial',
          fontSize: 12,
          shadowBlur: 20,
          shadowOffsetX: 3,
          shadowOffsetY: 5,
          shadowColor: 'rgba(0,0,0,0.3)'
        }
      }
    };
  }
  option = {
    dataset: {
      source: seriesData
    },
    tooltip: {},
    visualMap: [
      {
        show: false,
        min: 0,
        max: maxDepth,
        dimension: 'depth',
        inRange: {
          color: ['#006edd', '#e0ffff']
        }
      }
    ],
    hoverLayerThreshold: Infinity,
    series: {
      type: 'custom',
      renderItem: renderItem,
      progressive: 0,
      coordinateSystem: 'none',
      encode: {
        tooltip: 'value',
        itemName: 'id'
      }
    }
  };
  myChart.setOption(option);
  myChart.on('click', { seriesIndex: 0 }, function (params) {
    drillDown(params.data.id);
  });
  function drillDown(targetNodeId) {
    displayRoot = stratify();
    if (targetNodeId != null) {
      displayRoot = displayRoot.descendants().find(function (node) {
        return node.data.id === targetNodeId;
      });
    }
    // A trick to prevent d3-hierarchy from visiting parents in this algorithm.
    displayRoot.parent = null;
    myChart.setOption({
      dataset: {
        source: seriesData
      }
    });
  }
  // Reset: click on the blank area.
  myChart.getZr().on('click', function (event) {
    if (!event.target) {
      drillDown();
    }
  });
}
```
