# treemap-drill-down

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=treemap-drill-down
**Chart Type:** `treemap`

## User Data Requirements

Columns needed: need nested **name+value** or **name+children**

## Data Arrays — Complete Replacement Guide

**1 array(s)** to replace with real data:

### [0] `children` (context: root)
```
children: []
```

## Agent Workflow

1. **Analyze** user table → identify columns matching the required format above
2. **Query DuckDB** → transform to match each data array's format
3. **Replace**: use **bracket-counting** to find each `data: [...]` → replace with real data
4. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: ECharts Option Query
category: treemap
titleCN: ECharts 配置项查询分布
*/
const uploadedDataURL =
  'https://echarts.apache.org/examples/data/asset/data/ec-option-doc-statistics-201604.json';
myChart.showLoading();
var rawData = {
  "xAxis": {
    "axisLabel": {
      "$count": 2534,
      "show": {
        "$count": 444
      },
      "interval": {
        "$count": 950
      },
      "rotate": {
        "$count": 584
      },
      "inside": {
        "$count": 416
      },
      "formatter": {
        "$count": 886
      },
      "textStyle": {
        "$count": 490,
        "color": {
          "$count": 142
        },
        "fontStyle": {
          "$count": 107
        },
        "fontWeight": {
          "$count": 73
        },
        "fontFamily": {
          "$count": 68
        },
        "fontSize": {
          "$count": 128
        }
      },
      "margin": {
        "$count": 456
      }
    },
    "axisLine": {
      "$count": 2303,
      "lineStyle": {
        "width": {
          "$count": 158
        },
        "$count": 616,
        "shadowBlur": {
          "$count": 126
        },
        "color": {
          "$count": 244
        },
        "type": {
          "$count": 185
        },
        "shadowColor": {
          "$count": 103
        },
        "opacity": {
          "$count": 125
        },
        "shadowOffsetX": {
          "$count": 72
        },
        "shadowOffsetY": {
          "$count": 57
        }
      },
      "show": {
        "$count": 494
      },
      "onZero": {
        "$count": 465
      }
    },
    "$count": 11102,
    "boundaryGap": {
      "$count": 2319
    },
    "interval": {
      "$count": 1738
    },
    "type": {
      "$count": 3544
    },
    "position": {
      "$count": 2285
    },
    "splitNumber": {
      "$count": 1817
    },
    "splitLine": {
      "$count": 1565,
      "interval": {
        "$count": 273
      },
      "lineStyle": {
        "$count": 250,
        "color": {
          "$count": 131
        },
        "shadowBlur": {
          "$count": 42
        },
        "shadowColor": {
          "$count": 31
        },
        "type": {
          "$count": 97
        },
        "opacity": {
          "$count": 58
        },
        "shadowOffsetX": {
          "$count": 23
        },
        "width": {
          "$count": 67
        },
        "shadowOffsetY": {
          "$count": 22
        }
      },
      "show": {
        "$count": 217
      }
    },
    "name": {
      "$count": 1777
    },
    "data": {
      "value": {
        "$count": 769
      },
      "textStyle": {
        "align": {
          "$count": 178
        },
        "baseline": {
          "$count": 182
        },
        "fontStyle": {
          "$count": 90
        },
        "$count": 454,
        "color": {
          "$count": 146
        },
        "fontWeight": {
          "$count": 70
        },
        "fontFamily": {
          "$count": 67
        },
        "fontSize": {
          "$count": 84
        }
      },
      "$count": 1726
    },
    "max": {
      "$count": 947
    },
    "axisTick": {
      "$count": 1752,
      "interval": {
        "$count": 446
      },
      "length": {
        "$count": 270
      },
      "show": {
        "$count": 283
      },
      "lineStyle": {
        "$count": 290,
        "color": {
          "$count": 109
        },
        "width": {
          "$count": 59
        },
        "type": {
          "$count": 61
        },
        "shadowBlur": {
          "$count": 40
        },
        "opacity": {
          "$count": 36
        },
        "shadowOffsetY": {
          "$count": 18
        },
        "shadowOffsetX": {
          "$count": 21
        },
        "shadowColor": {
          "$count": 33
        }
      },
      "inside": {
        "$count": 225
      }
    },
    "splitArea": {
      "$count": 1020,
      "interval": {
        "$count": 224
      },
      "show": {
        "$count": 120
      },
      "areaStyle": {
        "color": {
          "$count": 151
        },
        "shadowBlur": {
          "$count": 62
        },
        "$count": 231,
        "shadowColor": {
          "$count": 45
        },
        "shadowOffsetX": {
          "$count": 37
        },
        "shadowOffsetY": {
          "$count": 26
        },
        "opacity": {
          "$count": 49
        }
      }
    },
    "nameTextStyle": {
      "$count": 1870,
      "color": {
        "$count": 410
      },
      "fontSize": {
        "$count": 213
      },
      "fontStyle": {
        "$count": 243
      },
      "fontWeight": {
        "$count": 170
      },
      "fontFamily": {
        "$count": 149
      }
    },
    "inverse": {
      "$count": 1362
    },
    "nameLocation": {
      "$count": 1729
    },
    "gridIndex": {
      "$count": 2271
    },
    "scale": {
      "$count": 1456
    },
    "min": {
      "$count": 1339
    },
    "nameGap": {
      "$count": 1647
    },
    "silent": {
      "$count": 424
    }
  },
  "series": {
    "bar": {
      "$count": 3662,
      "itemStyle": {
        "$count": 1134,
        "normal": {
          "barBorderColor": {
            "$count": 236
          },
          "barBorderRadius": {
            "$count": 163
          },
          "shadowBlur": {
            "$count": 117
          },
          "shadowOffsetX": {
            "$count": 84
          },
          "opacity": {
            "$count": 146
          },
          "$count": 543,
          "color": {
            "$count": 604
          },
          "shadowColor": {
            "$count": 91
          },
          "barBorderWidth": {
            "$count": 170
          },
          "shadowOffsetY": {
            "$count": 76
          }
        },
        "emphasis": {
          "$count": 276,
          "shadowBlur": {
            "$count": 18
          },
          "shadowColor": {
            "$count": 18
          },
          "shadowOffsetX": {
            "$count": 11
          },
          "shadowOffsetY": {
            "$count": 9
          },
          "opacity": {
            "$count": 18
          },
          "color": {
            "$count": 79
          },
          "barBorderColor": {
            "$count": 28
          },
          "barBorderWidth": {
            "$count": 17
          }
        }
      },
      "label": {
        "normal": {
          "textStyle": {
            "$count": 270,
            "color": {
              "$count": 92
            },
            "fontSize": {
              "$count": 57
            },
            "fontFamily": {
              "$count": 31
            },
            "fontStyle": {
              "$count": 55
            },
            "fontWeight": {
              "$count": 48
            }
          },
          "formatter": {
            "$count": 635
          },
          "position": {
            "$count": 613
          },
          "$count": 502,
          "show": {
            "$count": 283
          }
        },
        "emphasis": {
          "$count": 264,
          "position": {
            "$count": 68
          },
          "formatter": {
            "$count": 88
          },
          "textStyle": {
            "$count": 34,
            "color": {
              "$count": 14
            },
            "fontStyle": {
              "$count": 7
            },
            "fontWeight": {
              "$count": 4
            },
            "fontFamily": {
              "$count": 7
            },
            "fontSize": {
              "$count": 4
            }
          },
          "show": {
            "$count": 52
          }
        },
        "$count": 1074
      },
      "barWidth": {
        "$count": 992
      },
      "barCategoryGap": {
        "$count": 553
      },
      "yAxisIndex": {
        "$count": 401
      },
      "data": {
        "name": {
          "$count": 404
        },
        "value": {
          "$count": 418
        },
        "label": {
          "normal": {
            "position": {
              "$count": 130
            },
            "show": {
              "$count": 86
            },
            "$count": 180,
            "textStyle": {
              "$count": 68,
              "fontSize": {
                "$count": 23
              },
              "fontStyle": {
                "$count": 16
              },
              "fontWeight": {
                "$count": 11
              },
              "fontFamily": {
                "$count": 17
              },
              "color": {
                "$count": 34
              }
            }
          },
          "$count": 386,
          "emphasis": {
            "$count": 75,
            "position": {
              "$count": 21
            },
            "show": {
              "$count": 16
            },
            "textStyle": {
              "$count": 8,
              "color": {
                "$count": 11
              },
              "fontStyle": {
                "$count": 4
              },
              "fontWeight": {
                "$count": 4
              },
              "fontFamily": {
                "$count": 3
              },
              "fontSize": {
                "$count": 3
              }
            }
          }
        },
        "$count": 842,
        "itemStyle": {
          "$count": 352,
          "normal": {
            "$count": 188,
            "color": {
              "$count": 150
            },
            "barBorderRadius": {
              "$count": 27
            },
            "barBorderWidth": {
              "$count": 36
            },
            "barBorderColor": {
              "$count": 52
            },
            "shadowOffsetY": {
              "$count": 13
            },
            "shadowBlur": {
              "$count": 25
            },
            "shadowOffsetX": {
              "$count": 19
            },
            "opacity": {
              "$count": 30
            },
            "shadowColor": {
              "$count": 22
            }
          },
          "emphasis": {
            "barBorderColor": {
              "$count": 12
            },
            "$count": 98,
            "shadowBlur": {
              "$count": 2
            },
            "opacity": {
              "$count": 5
            },
            "color": {
              "$count": 25
            },
            "barBorderWidth": {
              "$count": 8
            },
            "shadowColor": {
              "$count": 4
            },
            "shadowOffsetX": {
              "$count": 4
            },
            "shadowOffsetY": {
              "$count": 3
            }
          }
        }
      },
      "barMaxWidth": {
        "$count": 456
      },
      "xAxisIndex": {
        "$count": 552
      },
      "stack": {
        "$count": 590
      },
      "legendHoverLink": {
        "$count": 551
      },
      "type": {
        "$count": 732
      },
      "name": {
        "$count": 517
      },
      "barGap": {
        "$count": 685
      },
      "z": {
        "$count": 100
      },
      "markLine": {
        "$count": 451,
        "data": {
          "0": {
            "$count": 62,
            "symbol": {
              "$count": 38
            },
            "symbolSize": {
              "$count": 14
            },
            "type": {
              "$count": 96
            },
            "symbolRotate": {
              "$count": 13
            },
            "symbolOffset": {
              "$count": 8
            },
            "x": {
              "$count": 35
            },
            "label": {
              "normal": {
                "formatter": {
                  "$count": 8
                },
                "$count": 3,
                "position": {
                  "$count": 1
                }
              },
              "$count": 10,
              "emphasis": {
                "formatter": {
                  "$count": 3
                },
                "position": {
                  "$count": 1
                }
              }
            },
            "valueIndex": {
              "$count": 50
            },
            "y": {
              "$count": 15
            },
            "value": {
              "$count": 45
            },
            "valueDim": {
              "$count": 29
            },
            "coord": {
              "$count": 53
            },
            "lineStyle": {
              "normal": {
                "$count": 10,
                "type": {
                  "$count": 2
                },
                "color": {
                  "$count": 5
                },
                "width": {
                  "$count": 3
                }
              },
              "$count": 14,
              "emphasis": {
                "$count": 3,
                "color": {
                  "$count": 1
                },
                "width": {
                  "$count": 1
                }
              }
            }
          },
          "1": {
            "$count": 31,
            "type": {
              "$count": 8
            },
            "x": {
              "$count": 6
            },
            "value": {
              "$count": 4
            },
            "label": {
              "normal": {
                "formatter": {
                  "$count": 3
                }
              },
              "emphasis": {
                "$count": 1
              }
            },
            "valueIndex": {
              "$count": 2
            },
            "valueDim": {
              "$count": 3
            },
            "coord": {
              "$count": 5
            },
            "y": {
              "$count": 3
            },
            "symbol": {
              "$count": 6
            },
            "symbolSize": {
              "$count": 3
            },
            "symbolRotate": {
              "$count": 2
            },
            "symbolOffset": {
              "$count": 3
            },
            "lineStyle": {
              "$count": 2,
              "normal": {
                "$count": 1
              }
            }
          },
          "$count": 114
        },
        "symbol": {
          "$count": 140
        },
        "lineStyle": {
          "$count": 86,
          "normal": {
            "type": {
              "$count": 37
            },
            "$count": 35,
            "shadowBlur": {
              "$count": 8
            },
            "color": {
              "$count": 25
            },
            "curveness": {
              "$count": 11
            },
            "width": {
              "$count": 13
            },
            "opacity": {
              "$count": 5
            },
            "shadowOffsetX": {
              "$count": 5
            },
            "shadowColor": {
              "$count": 6
            },
            "shadowOffsetY": {
              "$count": 4
            }
          },
          "emphasis": {
            "$count": 9,
            "width": {
              "$count": 1
            },
            "type": {
              "$count": 1
            },
            "shadowBlur": {
              "$count": 2
            },
            "shadowColor": {
              "$count": 2
            },
            "shadowOffsetX": {
              "$count": 1
            },
            "shadowOffsetY": {
              "$count": 1
            },
            "opacity": {
              "$count": 2
            },
            "color": {
              "$count": 2
            }
          }
        },
        "precision": {
          "$count": 43
        },
        "label": {
          "$count": 57,
          "normal": {
            "show": {
              "$count": 19
            },
            "position": {
              "$count": 23
            },
            "formatter": {
              "$count": 27
            },
            "$count": 16
          },
          "emphasis": {
            "$count": 9,
            "show": {
              "$count": 5
            },
            "formatter": {
              "$count": 5
            },
            "position": {
              "$count": 3
            }
          }
        },
        "symbolSize": {
          "$count": 51
        },
        "animation": {
          "$count": 11
        },
        "animationEasing": {
          "$count": 4
        },
        "animationDuration": {
          "$count": 5
        },
        "animationEasingUpdate": {
          "$count": 4
        },
        "animationDurationUpdate": {
          "$count": 4
        }
      },
      "markPoint": {
        "symbol": {
          "$count": 147
        },
        "$count": 556,
        "symbolRotate": {
          "$count": 62
        },
        "symbolOffset": {
          "$count": 44
        },
        "label": {
          "$count": 80,
          "normal": {
            "$count": 29,
            "position": {
              "$count": 23
            },
            "formatter": {
              "$count": 47
            },
            "textStyle": {
              "$count": 14,
              "fontStyle": {
                "$count": 3
              },
              "fontWeight": {
                "$count": 3
              },
              "fontFamily": {
                "$count": 1
              },
              "fontSize": {
                "$count": 4
              },
              "color": {
                "$count": 6
              }
            },
            "show": {
              "$count": 21
            }
          },
          "emphasis": {
            "formatter": {
              "$count": 8
            },
            "show": {
              "$count": 5
            },
            "position": {
              "$count": 6
            },
            "textStyle": {
              "$count": 3,
              "fontSize": {
                "$count": 1
              }
            },
            "$count": 19
          }
        },
        "data": {
          "$count": 101,
          "valueIndex": {
            "$count": 44
          },
          "valueDim": {
            "$count": 30
          },
          "coord": {
            "$count": 45
          },
          "x": {
            "$count": 35
          },
          "name": {
            "$count": 44
          },
          "type": {
            "$count": 70
          },
          "itemStyle": {
            "$count": 20,
            "normal": {
              "$count": 6,
              "color": {
                "$count": 6
              }
            },
            "emphasis": {
              "color": {
                "$count": 2
              },
              "$count": 3,
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
              "shadowBlur": {
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
          "y": {
            "$count": 14
          },
          "value": {
            "$count": 30
          },
          "label": {
            "normal": {
              "position": {
                "$count": 6
              },
              "$count": 2,
              "show": {
                "$count": 3
              }
            },
            "$count": 12,
            "emphasis": {
              "position": {
                "$count": 1
              }
            }
          },
          "symbol": {
            "$count": 25
          },
          "symbolRotate": {
            "$count": 9
          },
          "symbolSize": {
            "$count": 17
          },
          "symbolOffset": {
            "$count": 9
          }
        },
        "symbolSize": {
          "$count": 97
        },
        "itemStyle": {
          "$count": 74,
          "normal": {
            "color": {
              "$count": 17
            },
            "$count": 23,
            "borderWidth": {
              "$count": 4
            },
            "borderColor": {
              "$count": 1
            },
            "shadowBlur": {
              "$count": 3
            },
            "opacity": {
              "$count": 1
            },
            "shadowOffsetY": {
              "$count": 1
            },
            "shadowOffsetX": {
              "$count": 2
            },
            "shadowColor": {
              "$count": 1
            }
          },
          "emphasis": {
            "$count": 10,
            "color": {
              "$count": 2
            },
            "borderColor": {
              "$count": 1
            },
            "borderWidth": {
              "$count": 1
            }
          }
        },
        "animation": {
          "$count": 13
        },
        "animationEasing": {
          "$count": 8
        },
        "animationDurationUpdate": {
          "$count": 3
        },
        "animationDuration": {
          "$count": 6
        },
        "animationEasingUpdate": {
          "$count": 1
        }
      },
      "coordinateSystem": {
        "$count": 528
      },
      "barMinHeight": {
        "$count": 330
      },
      "zlevel": {
        "$count": 132
      },
      "animation": {
        "$count": 133
      },
      "animationDuration": {
        "$count": 70
      },
      "animationEasing": {
        "$count": 70
      },
      "animationEasingUpdate": {
        "$count": 72
      },
      "animationDurationUpdate": {
        "$count": 64
      },
      "silent": {
        "$count": 63
      }
    },
    "graph": {
      "links": {
        "$count": 535,
        "source": {
          "$count": 222
        },
        "target": {
          "$count": 133
        },
        "lineStyle": {
          "normal": {
            "$count": 109,
            "color": {
              "$count": 38
            },
            "type": {
              "$count": 50
            },
            "width": {
              "$count": 45
            },
            "shadowBlur": {
              "$count": 30
            },
            "shadowColor": {
              "$count": 22
            },
            "shadowOffsetX": {
              "$count": 21
            },
            "shadowOffsetY": {
              "$count": 22
            },
            "opacity": {
              "$count": 30
            },
            "curveness": {
              "$count": 38
            }
          },
          "$count": 189,
          "emphasis": {
            "$count": 49,
            "shadowOffsetY": {
              "$count": 5
            },
            "opacity": {
              "$count": 5
            },
            "type": {
              "$count": 8
            },
            "shadowOffsetX": {
              "$count": 4
            },
            "color": {
              "$count": 4
            },
            "width": {
              "$count": 3
            },
            "shadowBlur": {
              "$count": 5
            },
            "shadowColor": {
              "$count": 2
            }
          }
        }
      },
      "data": {
        "name": {
          "$count": 291
        },
        "$count": 676,
        "value": {
          "$count": 184
        },
        "symbolSize": {
          "$count": 134
        },
        "itemStyle": {
          "normal": {
            "$count": 54,
            "color": {
              "$count": 34
            },
            "borderColor": {
              "$count": 13
            },
            "opacity": {
              "$count": 24
            },
            "borderWidth": {
              "$count": 16
            },
            "shadowBlur": {
              "$count": 16
            },
            "shadowColor": {
              "$count": 9
            },
            "shadowOffsetX": {
              "$count": 9
            },
            "shadowOffsetY": {
              "$count": 8
            }
          },
          "emphasis": {
            "$count": 25,
            "borderWidth": {
              "$count": 5
            },
            "borderColor": {
              "$count": 5
            },
            "color": {
              "$count": 6
            },
            "shadowBlur": {
              "$count": 3
            },
            "shadowColor": {
              "$count": 3
            },
            "opacity": {
              "$count": 2
            },
            "shadowOffsetY": {
              "$count": 1
            },
            "shadowOffsetX": {
              "$count": 1
            }
          },
          "$count": 112
        },
        "category": {
          "$count": 217
        },
        "symbol": {
          "$count": 171
        },
        "label": {
          "$count": 85,
          "emphasis": {
            "$count": 16,
            "position": {
              "$count": 2
            },
            "show": {
              "$count": 4
            },
            "textStyle": {
              "$count": 1
            }
          },
          "normal": {
            "$count": 45,
            "position": {
              "$count": 25
            },
            "textStyle": {
              "$count": 17,
              "color": {
                "$count": 5
              },
              "fontStyle": {
                "$count": 8
              },
              "fontWeight": {
                "$count": 4
              },
              "fontFamily": {
                "$count": 4
              },
              "fontSize": {
                "$count": 4
              }
            },
            "show": {
              "$count": 28
            }
          }
        },
        "symbolRotate": {
          "$count": 74
        },
        "symbolOffset": {
          "$count": 75
        }
      },
      "force": {
        "initLayout": {
          "$count": 209
        },
        "repulsion": {
          "$count": 185
        },
        "$count": 430,
        "gravity": {
          "$count": 126
        },
        "edgeLength": {
          "$count": 152
        },
        "layoutAnimation": {
          "$count": 104
        }
      },
      "$count": 1470,
      "layout": {
        "$count": 390
      },
      "left": {
        "$count": 41
      },
      "top": {
        "$count": 36
      },
      "nodes": {
        "$count": 463
      },
      "roam": {
        "$count": 204
      },
      "nodeScaleRatio": {
        "$count": 174
      },
      "symbol": {
        "$count": 247
      },
      "symbolRotate": {
        "$count": 138
      },
      "symbolSize": {
        "$count": 181
      },
      "symbolOffset": {
        "$count": 116
      },
      "label": {
        "$count": 231,
        "normal": {
          "$count": 75,
          "textStyle": {
            "$count": 30,
            "color": {
              "$count": 9
            },
            "fontStyle": {
              "$count": 6
            },
            "fontFamily": {
              "$count": 5
            },
            "fontSize": {
              "$count": 2
            },
            "fontWeight": {
              "$count": 5
            }
          },
          "show": {
            "$count": 46
          },
          "formatter": {
            "$count": 121
          },
          "position": {
            "$count": 53
          }
        },
        "emphasis": {
          "$count": 49,
          "formatter": {
            "$count": 9
          },
          "textStyle": {
            "fontWeight": {
              "$count": 1
            },
            "fontSize": {
              "$count": 1
            },
            "$count": 7
          },
          "position": {
            "$count": 3
          },
          "show": {
            "$count": 6
          }
        }
      },
      "hoverAnimation": {
        "$count": 183
      },
      "lineStyle": {
        "$count": 225,
        "normal": {
          "$count": 79,
          "color": {
            "$count": 32
          },
          "type": {
            "$count": 35
          },
          "curveness": {
            "$count": 35
          },
          "opacity": {
            "$count": 18
          },
          "width": {
            "$count": 28
          },
          "shadowBlur": {
            "$count": 14
          },
          "shadowColor": {
            "$count": 8
          },
          "shadowOffsetX": {
            "$count": 7
          },
          "shadowOffsetY": {
            "$count": 6
          }
        },
        "emphasis": {
          "shadowColor": {
            "$count": 1
          },
          "shadowOffsetX": {
            "$count": 3
          },
          "shadowOffsetY": {
            "$count": 2
          },
          "opacity": {
            "$count": 4
          },
          "type": {
            "$count": 11
          },
          "$count": 44,
          "shadowBlur": {
            "$count": 4
          },
          "width": {
            "$count": 5
          },
          "color": {
            "$count": 5
          }
        }
      },
      "type": {
        "$count": 327
      },
      "legendHoverLink": {
        "$count": 217
      },
      "itemStyle": {
        "$count": 201,
        "normal": {
          "$count": 63,
          "shadowColor": {
            "$count": 14
          },
          "shadowOffsetX": {
            "$count": 13
          },
          "color": {
            "$count": 45
          },
          "shadowBlur": {
            "$count": 16
          },
          "borderWidth": {
            "$count": 18
          },
          "borderColor": {
            "$count": 27
          },
          "opacity": {
            "$count": 18
          },
          "shadowOffsetY": {
            "$count": 10
          }
        },
        "emphasis": {
          "$count": 46,
          "shadowColor": {
            "$count": 7
          },
          "shadowBlur": {
            "$count": 7
          },
          "color": {
            "$count": 10
          },
          "borderWidth": {
            "$count": 4
          },
          "opacity": {
            "$count": 9
          },
          "shadowOffsetY": {
            "$count": 5
          },
          "shadowOffsetX": {
            "$count": 4
          },
          "borderColor": {
            "$count": 5
          }
        }
      },
      "width": {
        "$count": 59
      },
      "edges": {
        "$count": 223
      },
      "height": {
        "$count": 50
      },
      "markLine": {
        "$count": 157,
        "symbol": {
          "$count": 46
        },
        "label": {
          "$count": 25,
          "normal": {
            "formatter": {
              "$count": 6
            },
            "show": {
              "$count": 4
            },
            "$count": 6,
            "position": {
              "$count": 3
            }
          },
          "emphasis": {
            "$count": 6,
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
        "symbolSize": {
          "$count": 24
        },
        "lineStyle": {
          "$count": 22,
          "emphasis": {
            "$count": 1
          },
          "normal": {
            "$count": 6,
            "type": {
              "$count": 2
            },
            "color": {
              "$count": 3
            },
            "shadowColor": {
              "$count": 1
            },
            "opacity": {
              "$count": 1
            },
            "curveness": {
              "$count": 2
            },
            "shadowOffsetY": {
              "$count": 1
            }
          }
        },
        "precision": {
          "$count": 17
        },
        "data": {
          "0": {
            "$count": 20,
            "symbol": {
              "$count": 13
            },
            "x": {
              "$count": 8
            },
            "symbolOffset": {
              "$count": 4
            },
            "symbolRotate": {
              "$count": 3
            },
            "value": {
              "$count": 10
            },
            "label": {
              "$count": 4,
              "normal": {
                "$count": 3
              },
              "emphasis": {
                "$count": 1
              }
            },
            "y": {
              "$count": 2
            },
            "symbolSize": {
              "$count": 1
            },
            "lineStyle": {
              "$count": 3,
              "normal": {
                "$count": 1
              }
            }
          },
          "1": {
            "symbolOffset": {
              "$count": 3
            },
            "symbolRotate": {
              "$count": 2
            },
            "symbolSize": {
              "$count": 2
            },
            "symbol": {
              "$count": 2
            },
            "x": {
              "$count": 2
            },
            "y": {
              "$count": 2
            },
            "label": {
              "$count": 2,
              "normal": {
                "$count": 1,
                "show": {
                  "$count": 1
                },
                "position": {
                  "$count": 1
                },
                "formatter": {
                  "$count": 1
                }
              },
              "emphasis": {
                "$count": 1
              }
            },
            "$count": 4,
            "value": {
              "$count": 1
            },
            "lineStyle": {
              "$count": 3,
              "normal": {
                "$count": 4
              },
              "emphasis": {
                "$count": 1
              }
            }
          },
          "$count": 32
        },
        "animation": {
          "$count": 5
        },
        "animationDuration": {
          "$count": 2
        },
        "animationEasing": {
          "$count": 1
        },
        "animationDurationUpdate": {
          "$count": 2
        },
        "animationEasingUpdate": {
          "$count": 2
        }
      },
      "zlevel": {
        "$count": 45
      },
      "categories": {
        "name": {
          "$count": 81
        },
        "$count": 323,
        "symbol": {
          "$count": 74
        },
        "symbolSize": {
          "$count": 42
        },
        "symbolRotate": {
          "$count": 20
        },
        "itemStyle": {
          "$count": 34,
          "normal": {
            "$count": 12,
            "color": {
              "$count": 18
            },
            "shadowColor": {
              "$count": 6
            },
            "shadowBlur": {
              "$count": 5
            },
            "borderWidth": {
              "$count": 5
            },
            "shadowOffsetX": {
              "$count": 2
            },
            "shadowOffsetY": {
              "$count": 3
            },
            "opacity": {
              "$count": 5
            },
            "borderColor": {
              "$count": 5
            }
          },
          "emphasis": {
            "$count": 2
          }
        },
        "label": {
          "$count": 28,
          "normal": {
            "$count": 14,
            "position": {
              "$count": 12
            },
            "formatter": {
              "$count": 8
            },
            "textStyle": {
              "$count": 4,
              "color": {
                "$count": 1
              },
              "fontSize": {
                "$count": 2
              }
            },
            "show": {
              "$count": 5
            }
          },
          "emphasis": {
            "$count": 3,
            "show": {
              "$count": 1
            },
            "position": {
              "$count": 1
            }
          }
        },
        "symbolOffset": {
          "$count": 17
        }
      },
      "markPoint": {
        "$count": 134,
        "animationEasing": {
          "$count": 5
        },
        "animationEasingUpdate": {
          "$count": 3
        },
        "symbol": {
          "$count": 30
        },
        "data": {
          "$count": 10,
          "symbol": {
            "$count": 5
          },
          "symbolRotate": {
            "$count": 4
          },
          "value": {
            "$count": 1
          },
          "symbolSize": {
            "$count": 4
          },
          "symbolOffset": {
            "$count": 1
          },
          "itemStyle": {
            "$count": 6,
            "normal": {
              "$count": 1,
              "shadowBlur": {
                "$count": 1
              },
              "shadowOffsetX": {
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
              "borderColor": {
                "$count": 1
              },
              "opacity": {
                "$count": 1
              }
            }
          },
          "label": {
            "$count": 6,
            "normal": {
              "$count": 3,
              "show": {
                "$count": 2
              },
              "position": {
                "$count": 1
              },
              "textStyle": {
                "$count": 1,
                "color": {
                  "$count": 1
                },
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
              }
            },
            "emphasis": {
              "$count": 2
            }
          },
          "name": {
            "$count": 1
          },
          "x": {
            "$count": 1
          },
          "y": {
            "$count": 1
          }
        },
        "symbolSize": {
          "$count": 11
        },
        "symbolRotate": {
          "$count": 11
        },
        "animationDuration": {
          "$count": 4
        },
        "animationDurationUpdate": {
          "$count": 2
        },
        "itemStyle": {
          "normal": {
            "color": {
              "$count": 2
            }
          },
          "$count": 7
        },
        "symbolOffset": {
          "$count": 7
        },
        "label": {
          "$count": 7,
          "normal": {
            "$count": 5,
            "textStyle": {
              "$count": 1
            }
          },
          "emphasis": {
            "$count": 2
          }
        },
        "animation": {
          "$count": 5
        }
      },
      "animation": {
        "$count": 68
      },
      "animationDuration": {
        "$count": 42
      },
      "name": {
        "$count": 168
      },
      "animationEasingUpdate": {
        "$count": 35
      },
      "animationDurationUpdate": {
        "$count": 28
      },
      "animationEasing": {
        "$count": 32
      },
      "color": {
        "$count": 69
      },
      "z": {
        "$count": 30
      },
      "right": {
        "$count": 21
      },
      "bottom": {
        "$count": 24
      },
      "silent": {
        "$count": 26
      }
    },
    "pie": {
      "markPoint": {
        "symbolOffset": {
          "$count": 28
        },
        "symbolRotate": {
          "$count": 33
        },
        "symbol": {
          "$count": 101
        },
        "$count": 372,
        "label": {
          "$count": 44,
          "normal": {
            "formatter": {
              "$count": 20
            },
            "$count": 22,
            "show": {
              "$count": 11
            },
            "position": {
              "$count": 15
            },
            "textStyle": {
              "$count": 10,
              "fontSize": {
                "$count": 2
              },
              "color": {
                "$count": 2
              },
              "fontStyle": {
                "$count": 1
              },
              "fontWeight": {
                "$count": 1
              },
              "fontFamily": {
                "$count": 1
              }
            }
          },
          "emphasis": {
            "formatter": {
              "$count": 3
            },
            "textStyle": {
              "$count": 1
            },
            "$count": 5
          }
        },
        "animation": {
          "$count": 12
        },
        "itemStyle": {
          "$count": 22,
          "emphasis": {
            "shadowBlur": {
              "$count": 2
            },
            "$count": 3,
            "shadowOffsetX": {
              "$count": 1
            }
          },
          "normal": {
            "$count": 5,
            "borderColor": {
              "$count": 1
            },
            "opacity": {
              "$count": 1
            },
            "color": {
              "$count": 6
            }
          }
        },
        "data": {
          "$count": 36,
          "value": {
            "$count": 20
          },
          "symbolSize": {
            "$count": 9
          },
          "symbolRotate": {
            "$count": 6
          },
          "itemStyle": {
            "$count": 13,
            "normal": {
              "$count": 3,
              "color": {
                "$count": 4
              },
              "shadowColor": {
                "$count": 1
              }
            },
            "emphasis": {
              "borderColor": {
                "$count": 1
              }
            }
          },
          "label": {
            "normal": {
              "position": {
                "$count": 7
              },
              "show": {
                "$count": 2
              },
              "textStyle": {
                "$count": 3
              },
              "$count": 6
            },
            "$count": 12,
            "emphasis": {
              "textStyle": {
                "$count": 1
              },
              "position": {
                "$count": 1
              },
              "$count": 1
            }
          },
          "x": {
            "$count": 20
          },
          "name": {
            "$count": 17
          },
          "symbol": {
            "$count": 14
          },
          "y": {
            "$count": 7
          },
          "symbolOffset": {
            "$count": 1
          }
        },
        "symbolSize": {
          "$count": 47
        },
        "animationDuration": {
          "$count": 8
        },
        "animationEasing": {
          "$count": 5
        },
        "animationDurationUpdate": {
          "$count": 5
        },
        "animationEasingUpdate": {
          "$count": 2
        }
      },
      "name": {
        "$count": 576
      },
      "label": {
        "$count": 1210,
        "normal": {
          "$count": 595,
          "show": {
            "$count": 320
          },
          "position": {
            "$count": 686
          },
          "textStyle": {
            "$count": 287,
            "color": {
              "$count": 116
            },
            "fontSize": {
              "$count": 98
            },
            "fontFamily": {
              "$count": 81
            },
            "fontWeight": {
              "$count": 90
            },
            "fontStyle": {
              "$count": 107
            }
          },
          "formatter": {
            "$count": 698
          }
        },
        "emphasis": {
          "show": {
            "$count": 104
          },
          "textStyle": {
            "$count": 41,
            "fontWeight": {
              "$count": 19
            },
            "color": {
              "$count": 23
            },
            "fontStyle": {
              "$count": 17
            },
            "fontFamily": {
              "$count": 9
            },
            "fontSize": {
              "$count": 12
            }
          },
          "$count": 313,
          "formatter": {
            "$count": 128
          }
        }
      },
      "labelLine": {
        "$count": 768,
        "normal": {
          "length2": {
            "$count": 124
          },
          "smooth": {
            "$count": 107
          },
          "lineStyle": {
            "$count": 100,
            "color": {
              "$count": 37
            },
            "type": {
              "$count": 43
            },
            "shadowBlur": {
              "$count": 33
            },
            "shadowColor": {
              "$count": 24
            },
            "shadowOffsetX": {
              "$count": 24
            },
            "shadowOffsetY": {
              "$count": 24
            },
            "opacity": {
              "$count": 33
            },
            "width": {
              "$count": 39
            }
          },
          "length": {
            "$count": 220
          },
          "$count": 211,
          "show": {
            "$count": 236
          }
        },
        "emphasis": {
          "$count": 68,
          "show": {
            "$count": 44
          },
          "lineStyle": {
            "$count": 16,
            "type": {
              "$count": 6
            },
            "shadowBlur": {
              "$count": 3
            },
            "shadowColor": {
              "$count": 3
            },
            "shadowOffsetY": {
              "$count": 4
            },
            "opacity": {
              "$count": 5
            },
            "color": {
              "$count": 8
            },
            "width": {
              "$count": 3
            },
            "shadowOffsetX": {
              "$count": 3
            }
          }
        }
      },
      "$count": 2772,
      "selectedMode": {
        "$count": 596
      },
      "radius": {
        "$count": 642
      },
      "itemStyle": {
        "$count": 797,
        "normal": {
          "$count": 323,
          "color": {
            "$count": 326
          },
          "opacity": {
            "$count": 79
          },
          "borderWidth": {
            "$count": 79
          },
          "shadowColor": {
            "$count": 53
          },
          "shadowBlur": {
            "$count": 83
          },
          "borderColor": {
            "$count": 108
          },
          "shadowOffsetX": {
            "$count": 48
          },
          "shadowOffsetY": {
            "$count": 36
          }
        },
        "emphasis": {
          "$count": 207,
          "borderWidth": {
            "$count": 39
          },
          "shadowBlur": {
            "$count": 55
          },
          "shadowColor": {
            "$count": 42
          },
          "opacity": {
            "$count": 37
          },
          "borderColor": {
            "$count": 48
          },
          "color": {
            "$count": 83
          },
          "shadowOffsetX": {
            "$count": 38
          },
          "shadowOffsetY": {
            "$count": 29
          }
        }
      },
      "data": {
        "$count": 647,
        "itemStyle": {
          "normal": {
            "$count": 161,
            "borderColor": {
              "$count": 66
            },
            "color": {
              "$count": 190
            },
            "shadowBlur": {
              "$count": 27
            },
            "borderWidth": {
              "$count": 38
            },
            "shadowColor": {
              "$count": 22
            },
            "opacity": {
              "$count": 35
            },
            "shadowOffsetX": {
              "$count": 18
            },
            "shadowOffsetY": {
              "$count": 12
            }
          },
          "$count": 297,
          "emphasis": {
            "opacity": {
              "$count": 12
            },
            "$count": 82,
            "color": {
              "$count": 26
            },
            "borderColor": {
              "$count": 14
            },
            "shadowOffsetX": {
              "$count": 6
            },
            "shadowBlur": {
              "$count": 9
            },
            "borderWidth": {
              "$count": 7
            },
            "shadowOffsetY": {
              "$count": 4
            },
            "shadowColor": {
              "$count": 2
            }
          }
        },
        "name": {
          "$count": 301
        },
        "labelLine": {
          "normal": {
            "$count": 50,
            "show": {
              "$count": 45
            },
            "smooth": {
              "$count": 28
            },
            "lineStyle": {
              "$count": 33,
              "color": {
                "$count": 16
              },
              "width": {
                "$count": 4
              },
              "type": {
                "$count": 4
              },
              "shadowBlur": {
                "$count": 3
              },
              "shadowColor": {
                "$count": 2
              },
              "opacity": {
                "$count": 4
              },
              "shadowOffsetX": {
                "$count": 2
              },
              "shadowOffsetY": {
                "$count": 3
              }
            },
            "length": {
              "$count": 34
            },
            "length2": {
              "$count": 18
            }
          },
          "$count": 198,
          "emphasis": {
            "$count": 16,
            "show": {
              "$count": 9
            },
            "lineStyle": {
              "$count": 1
            }
          }
        },
        "selected": {
          "$count": 221
        },
        "label": {
          "$count": 372,
          "normal": {
            "$count": 169,
            "show": {
              "$count": 102
            },
            "position": {
              "$count": 136
            },
            "textStyle": {
              "$count": 79,
              "color": {
                "$count": 37
              },
              "fontStyle": {
                "$count": 21
              },
              "fontFamily": {
                "$count": 14
              },
              "fontWeight": {
                "$count": 12
              },
              "fontSize": {
                "$count": 18
              }
            }
          },
          "emphasis": {
            "$count": 65,
            "show": {
              "$count": 27
            },
            "textStyle": {
              "$count": 22,
              "color": {
                "$count": 9
              },
              "fontStyle": {
                "$count": 6
              },
              "fontFamily": {
                "$count": 6
              },
              "fontWeight": {
                "$count": 3
              },
              "fontSize": {
                "$count": 3
              }
            }
          }
        },
        "value": {
          "$count": 276
        }
      },
      "legendHoverLink": {
        "$count": 702
      },
      "hoverAnimation": {
        "$count": 591
      },
      "selectedOffset": {
        "$count": 480
      },
      "clockwise": {
        "$count": 500
      },
      "startAngle": {
        "$count": 465
      },
      "minAngle": {
        "$count": 413
      },
      "roseType": {
        "$count": 717
      },
      "avoidLabelOverlap": {
        "$count": 603
      },
      "animation": {
        "$count": 177
      },
      "animationDuration": {
        "$count": 94
      },
      "animationEasing": {
        "$count": 103
      },
      "animationDurationUpdate": {
        "$count": 84
      },
      "animationEasingUpdate": {
        "$count": 80
      },
      "type": {
        "$count": 704
      },
      "markLine": {
        "$count": 279,
        "label": {
          "normal": {
            "formatter": {
              "$count": 10
            },
            "$count": 11,
            "show": {
              "$count": 4
            },
            "position": {
              "$count": 3
            }
          },
          "$count": 30,
          "emphasis": {
            "$count": 2,
            "show": {
              "$count": 1
            },
            "position": {
              "$count": 1
            },
            "formatter": {
              "$count": 2
            }
          }
        },
        "data": {
          "0": {
            "label": {
              "normal": {
                "formatter": {
                  "$count": 2
                }
              }
            },
            "$count": 9,
            "x": {
              "$count": 7
            },
            "lineStyle": {
              "$count": 2,
              "normal": {
                "color": {
                  "$count": 1
                }
              }
            },
            "value": {
              "$count": 6
            },
            "symbol": {
              "$count": 6
            },
            "y": {
              "$count": 2
            },
            "symbolOffset": {
              "$count": 1
            },
            "symbolSize": {
              "$count": 3
            }
          },
          "1": {
            "symbolSize": {
              "$count": 2
            },
            "$count": 1,
            "symbol": {
              "$count": 2
            },
            "lineStyle": {
              "$count": 2
            },
            "symbolRotate": {
              "$count": 2
            },
            "symbolOffset": {
              "$count": 2
            }
          },
          "$count": 23
        },
        "symbol": {
          "$count": 45
        },
        "symbolSize": {
          "$count": 24
        },
        "precision": {
          "$count": 14
        },
        "lineStyle": {
          "$count": 24,
          "normal": {
            "$count": 6,
            "width": {
              "$count": 1
            },
            "curveness": {
              "$count": 1
            },
            "type": {
              "$count": 3
            },
            "color": {
              "$count": 1
            }
          },
          "emphasis": {
            "$count": 2
          }
        },
        "animationDuration": {
          "$count": 5
        },
        "animation": {
          "$count": 4
        },
        "animationEasing": {
          "$count": 4
        },
        "animationDurationUpdate": {
          "$count": 2
        },
        "animationEasingUpdate": {
          "$count": 2
        }
      },
      "center": {
        "$count": 625
      },
      "zlevel": {
        "$count": 178
      },
      "z": {
        "$count": 141
      },
      "silent": {
        "$count": 78
      }
    },
    "$count": 12295,
    "effectScatter": {
      "coordinateSystem": {
        "$count": 134
      },
      "yAxisIndex": {
        "$count": 26
      },
      "polarIndex": {
        "$count": 40
      },
      "geoIndex": {
        "$count": 61
      },
      "symbol": {
        "$count": 132
      },
      "symbolSize": {
        "$count": 123
      },
      "symbolRotate": {
        "$count": 64
      },
      "label": {
        "normal": {
          "textStyle": {
            "fontStyle": {
              "$count": 7
            },
            "fontWeight": {
              "$count": 5
            },
            "fontFamily": {
              "$count": 7
            },
            "$count": 19,
            "color": {
              "$count": 7
            },
            "fontSize": {
              "$count": 7
            }
          },
          "$count": 29,
          "formatter": {
            "$count": 57
          },
          "show": {
            "$count": 16
          },
          "position": {
            "$count": 39
          }
        },
        "$count": 96,
        "emphasis": {
          "$count": 13,
          "show": {
            "$count": 4
          },
          "position": {
            "$count": 8
          },
          "textStyle": {
            "$count": 3
          },
          "formatter": {
            "$count": 9
          }
        }
      },
      "itemStyle": {
        "normal": {
          "borderColor": {
            "$count": 10
          },
          "borderWidth": {
            "$count": 5
          },
          "shadowColor": {
            "$count": 11
          },
          "shadowBlur": {
            "$count": 13
          },
          "shadowOffsetY": {
            "$count": 5
          },
          "opacity": {
            "$count": 12
          },
          "shadowOffsetX": {
            "$count": 4
          },
          "color": {
            "$count": 26
          },
          "$count": 22
        },
        "$count": 66,
        "emphasis": {
          "$count": 11,
          "opacity": {
            "$count": 2
          },
          "color": {
            "$count": 1
          },
          "borderColor": {
            "$count": 2
          },
          "borderWidth": {
            "$count": 2
          },
          "shadowColor": {
            "$count": 2
          },
          "shadowBlur": {
            "$count": 3
          },
          "shadowOffsetX": {
            "$count": 1
          },
          "shadowOffsetY": {
            "$count": 1
          }
        }
      },
      "$count": 1385,
      "markPoint": {
        "itemStyle": {
          "$count": 10,
          "normal": {
            "$count": 5,
            "opacity": {
              "$count": 3
            },
            "color": {
              "$count": 2
            },
            "borderWidth": {
              "$count": 1
            },
            "shadowColor": {
              "$count": 1
            },
            "shadowBlur": {
              "$count": 2
            }
          }
        },
        "$count": 73,
        "symbolSize": {
          "$count": 9
        },
        "symbol": {
          "$count": 31
        },
        "data": {
          "valueDim": {
            "$count": 5
          },
          "$count": 26,
          "coord": {
            "$count": 10
          },
          "symbol": {
            "$count": 5
          },
          "type": {
            "$count": 6
          },
          "value": {
            "$count": 10
          },
          "symbolRotate": {
            "$count": 2
          },
          "name": {
            "$count": 8
          },
          "x": {
            "$count": 5
          },
          "y": {
            "$count": 5
          },
          "itemStyle": {
            "$count": 4
          },
          "label": {
            "normal": {
              "$count": 2,
              "show": {
                "$count": 1
              }
            },
            "$count": 3
          },
          "valueIndex": {
            "$count": 4
          },
          "symbolSize": {
            "$count": 1
          },
          "symbolOffset": {
            "$count": 1
          }
        },
        "symbolOffset": {
          "$count": 6
        },
        "label": {
          "$count": 8,
          "normal": {
            "formatter": {
              "$count": 7
            },
            "position": {
              "$count": 2
            },
            "textStyle": {
              "$count": 1
            },
            "$count": 2
          },
          "emphasis": {
            "$count": 1
          }
        },
        "symbolRotate": {
          "$count": 7
        },
        "animation": {
          "$count": 3
        },
        "animationDuration": {
          "$count": 3
        },
        "animationEasing": {
          "$count": 3
        },
        "animationDurationUpdate": {
          "$count": 2
        },
        "animationEasingUpdate": {
          "$count": 2
        }
      },
      "effectType": {
        "$count": 228
      },
      "rippleEffect": {
        "period": {
          "$count": 100
        },
        "$count": 243,
        "brushType": {
          "$count": 124
        },
        "scale": {
          "$count": 89
        }
      },
      "type": {
        "$count": 247
      },
      "name": {
        "$count": 80
      },
      "legendHoverLink": {
        "$count": 106
      },
      "showEffectOn": {
        "$count": 222
      },
      "zlevel": {
        "$count": 22
      },
      "data": {
        "$count": 150,
        "symbol": {
          "$count": 34
        },
        "label": {
          "$count": 29,
          "emphasis": {
            "$count": 5,
            "position": {
              "$count": 2
            },
            "textStyle": {
              "$count": 2
            }
          },
          "normal": {
            "$count": 11,
            "show": {
              "$count": 6
            },
            "position": {
              "$count": 5
            },
            "textStyle": {
              "fontWeight": {
                "$count": 1
              },
              "$count": 2
            }
          }
        },
        "symbolSize": {
          "$count": 18
        },
        "symbolOffset": {
          "$count": 11
        },
        "symbolRotate": {
          "$count": 9
        },
        "itemStyle": {
          "normal": {
            "color": {
              "$count": 4
            },
            "$count": 9,
            "opacity": {
              "$count": 2
            },
            "shadowColor": {
              "$count": 2
            },
            "borderColor": {
              "$count": 1
            },
            "shadowBlur": {
              "$count": 2
            }
          },
          "$count": 17,
          "emphasis": {
            "$count": 3
          }
        }
      },
      "xAxisIndex": {
        "$count": 49
      },
      "markLine": {
        "data": {
          "0": {
            "$count": 10,
            "coord": {
              "$count": 5
            },
            "valueDim": {
              "$count": 3
            },
            "symbol": {
              "$count": 3
            },
            "type": {
              "$count": 6
            },
            "symbolRotate": {
              "$count": 1
            },
            "symbolSize": {
              "$count": 1
            },
            "valueIndex": {
              "$count": 4
            },
            "x": {
              "$count": 1
            }
          },
          "1": {
            "lineStyle": {
              "normal": {
                "curveness": {
                  "$count": 1
                }
              }
            },
            "$count": 2,
            "symbol": {
              "$count": 1
            }
          },
          "$count": 11
        },
        "$count": 30,
        "symbol": {
          "$count": 11
        },
        "symbolSize": {
          "$count": 6
        },
        "precision": {
          "$count": 8
        },
        "label": {
          "$count": 4,
          "normal": {
            "$count": 1,
            "position": {
              "$count": 2
            }
          },
          "emphasis": {
            "position": {
              "$count": 2
            }
          }
        },
        "lineStyle": {
          "$count": 3,
          "normal": {
            "type": {
              "$count": 2
            },
            "curveness": {
              "$count": 2
            },
            "color": {
              "$count": 1
            },
            "shadowColor": {
              "$count": 1
            }
          }
        }
      },
      "animation": {
        "$count": 25
      },
      "symbolOffset": {
        "$count": 40
      },
      "animationDuration": {
        "$count": 13
      },
      "animationEasing": {
        "$count": 16
      },
      "animationDurationUpdate": {
        "$count": 12
      },
      "animationEasingUpdate": {
        "$count": 13
      },
      "z": {
        "$count": 8
      },
      "silent": {
        "$count": 6
      }
    },
    "line": {
      "itemStyle": {
        "$count": 1439,
        "normal": {
          "$count": 533,
          "borderWidth": {
            "$count": 201
          },
          "color": {
            "$count": 442
          },
          "opacity": {
            "$count": 150
          },
          "borderColor": {
            "$count": 225
          },
          "shadowBlur": {
            "$count": 142
          },
          "shadowOffsetX": {
            "$count": 92
          },
          "shadowOffsetY": {
            "$count": 76
          },
          "shadowColor": {
            "$count": 111
          }
        },
        "emphasis": {
          "$count": 278,
          "color": {
            "$count": 71
          },
          "opacity": {
            "$count": 30
          },
          "shadowOffsetY": {
            "$count": 24
          },
          "shadowOffsetX": {
            "$count": 39
          },
          "shadowColor": {
            "$count": 40
          },
          "shadowBlur": {
            "$count": 49
          },
          "borderWidth": {
            "$count": 38
          },
          "borderColor": {
            "$count": 47
          }
        }
      },
      "markPoint": {
        "$count": 1244,
        "itemStyle": {
          "$count": 192,
          "normal": {
            "$count": 76,
            "color": {
              "$count": 66
            },
            "opacity": {
              "$count": 19
            },
            "shadowOffsetY": {
              "$count": 3
            },
            "shadowOffsetX": {
              "$count": 6
            },
            "shadowColor": {
              "$count": 12
            },
            "borderWidth": {
              "$count": 18
            },
            "borderColor": {
              "$count": 26
            },
            "shadowBlur": {
              "$count": 10
            }
          },
          "emphasis": {
            "$count": 24,
            "opacity": {
              "$count": 4
            },
            "shadowColor": {
              "$count": 1
            },
            "color": {
              "$count": 4
            },
            "borderWidth": {
              "$count": 3
            },
            "borderColor": {
              "$count": 2
            },
            "shadowOffsetX": {
              "$count": 1
            }
          }
        },
        "label": {
          "emphasis": {
            "$count": 44,
            "formatter": {
              "$count": 24
            },
            "textStyle": {
              "$count": 5,
              "color": {
                "$count": 4
              },
              "fontWeight": {
                "$count": 3
              },
              "fontFamily": {
                "$count": 3
              },
              "fontSize": {
                "$count": 3
              },
              "fontStyle": {
                "$count": 3
              }
            },
            "show": {
              "$count": 7
            },
            "position": {
              "$count": 11
            }
          },
          "normal": {
            "$count": 117,
            "position": {
              "$count": 73
            },
            "formatter": {
              "$count": 140
            },
            "show": {
              "$count": 43
            },
            "textStyle": {
              "$count": 51,
              "color": {
                "$count": 34
              },
              "fontStyle": {
                "$count": 11
              },
              "fontWeight": {
                "$count": 14
              },
              "fontFamily": {
                "$count": 11
              },
              "fontSize": {
                "$count": 13
              }
            }
          },
          "$count": 251
        },
        "symbol": {
          "$count": 486
        },
        "symbolSize": {
          "$count": 230
        },
        "symbolRotate": {
          "$count": 165
        },
        "symbolOffset": {
          "$count": 169
        },
        "data": {
          "type": {
            "$count": 241
          },
          "$count": 342,
          "name": {
            "$count": 174
          },
          "valueIndex": {
            "$count": 125
          },
          "valueDim": {
            "$count": 105
          },
          "coord": {
            "$count": 172
          },
          "itemStyle": {
            "$count": 86,
            "normal": {
              "color": {
                "$count": 22
              },
              "$count": 35,
              "borderWidth": {
                "$count": 5
              },
              "shadowBlur": {
                "$count": 7
              },
              "borderColor": {
                "$count": 6
              },
              "opacity": {
                "$count": 2
              },
              "shadowOffsetY": {
                "$count": 3
              },
              "shadowOffsetX": {
                "$count": 3
              },
              "shadowColor": {
                "$count": 3
              }
            },
            "emphasis": {
              "opacity": {
                "$count": 3
              },
              "shadowOffsetY": {
                "$count": 2
              },
              "$count": 14,
              "color": {
                "$count": 2
              },
              "borderColor": {
                "$count": 3
              },
              "borderWidth": {
                "$count": 2
              },
              "shadowBlur": {
                "$count": 1
              },
              "shadowColor": {
                "$count": 1
              },
              "shadowOffsetX": {
                "$count": 1
              }
            }
          },
          "symbol": {
            "$count": 99
          },
          "symbolSize": {
            "$count": 60
          },
          "symbolRotate": {
            "$count": 40
          },
          "symbolOffset": {
            "$count": 38
          },
          "label": {
            "normal": {
              "textStyle": {
                "color": {
                  "$count": 8
                },
                "$count": 10,
                "fontStyle": {
                  "$count": 1
                },
                "fontFamily": {
                  "$count": 1
                },
                "fontSize": {
                  "$count": 2
                }
              },
              "show": {
                "$count": 16
              },
              "position": {
                "$count": 30
              },
              "$count": 37
            },
            "$count": 75,
            "emphasis": {
              "position": {
                "$count": 4
              },
              "$count": 17,
              "show": {
                "$count": 2
              },
              "textStyle": {
                "$count": 2
              }
            }
          },
          "value": {
            "$count": 148
          },
          "x": {
            "$count": 91
          },
          "y": {
            "$count": 56
          }
        },
        "animation": {
          "$count": 56
        },
        "animationDuration": {
          "$count": 37
        },
        "animationEasing": {
          "$count": 33
        },
        "animationDurationUpdate": {
          "$count": 27
        },
        "animationEasingUpdate": {
          "$count": 25
        }
      },
      "showAllSymbol": {
        "$count": 684
      },
      "$count": 4746,
      "stack": {
        "$count": 1111
      },
      "data": {
        "$count": 1422,
        "label": {
          "$count": 292,
          "normal": {
            "position": {
              "$count": 66
            },
            "$count": 120,
            "show": {
              "$count": 61
            },
            "textStyle": {
              "$count": 48,
              "fontSize": {
                "$count": 12
              },
              "color": {
                "$count": 17
              },
              "fontStyle": {
                "$count": 9
              },
              "fontWeight": {
                "$count": 6
              },
              "fontFamily": {
                "$count": 7
              }
            }
          },
          "emphasis": {
            "$count": 66,
            "show": {
              "$count": 18
            },
            "position": {
              "$count": 18
            },
            "textStyle": {
              "$count": 12,
              "color": {
                "$count": 6
              },
              "fontStyle": {
                "$count": 4
              },
              "fontWeight": {
                "$count": 3
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
        "itemStyle": {
          "$count": 268,
          "emphasis": {
            "$count": 55,
            "barBorderColor": {
              "$count": 16
            },
            "color": {
              "$count": 11
            },
            "opacity": {
              "$count": 7
            },
            "barBorderWidth": {
              "$count": 11
            },
            "shadowColor": {
              "$count": 2
            },
            "shadowOffsetX": {
              "$count": 3
            },
            "shadowOffsetY": {
              "$count": 2
            },
            "shadowBlur": {
              "$count": 3
            }
          },
          "normal": {
            "color": {
              "$count": 94
            },
            "barBorderColor": {
              "$count": 55
            },
            "$count": 101,
            "shadowBlur": {
              "$count": 27
            },
            "opacity": {
              "$count": 20
            },
            "shadowOffsetY": {
              "$count": 11
            },
            "shadowOffsetX": {
              "$count": 12
            },
            "barBorderWidth": {
              "$count": 29
            },
            "shadowColor": {
              "$count": 13
            }
          }
        },
        "symbol": {
          "$count": 309
        },
        "symbolSize": {
          "$count": 191
        },
        "name": {
          "$count": 486
        },
        "value": {
          "$count": 515
        },
        "symbolOffset": {
          "$count": 140
        },
        "symbolRotate": {
          "$count": 143
        }
      },
      "symbolOffset": {
        "$count": 569
      },
      "type": {
        "$count": 1788
      },
      "coordinateSystem": {
        "$count": 1153
      },
      "yAxisIndex": {
        "$count": 679
      },
      "polarIndex": {
        "$count": 567
      },
      "symbolSize": {
        "$count": 1042
      },
      "smooth": {
        "$count": 727
      },
      "lineStyle": {
        "emphasis": {
          "$count": 54,
          "color": {
            "$count": 12
          },
          "width": {
            "$count": 4
          },
          "opacity": {
            "$count": 3
          },
          "shadowOffsetY": {
            "$count": 2
          },
          "shadowOffsetX": {
            "$count": 2
          },
          "shadowBlur": {
            "$count": 2
          },
          "shadowColor": {
            "$count": 1
          },
          "type": {
            "$count": 6
          }
        },
        "normal": {
          "$count": 507,
          "opacity": {
            "$count": 106
          },
          "color": {
            "$count": 365
          },
          "shadowBlur": {
            "$count": 133
          },
          "width": {
            "$count": 211
          },
          "type": {
            "$count": 249
          },
          "shadowColor": {
            "$count": 87
          },
          "shadowOffsetX": {
            "$count": 60
          },
          "shadowOffsetY": {
            "$count": 47
          }
        },
        "$count": 1329
      },
      "markLine": {
        "data": {
          "0": {
            "type": {
              "$count": 200
            },
            "coord": {
              "$count": 194
            },
            "symbolOffset": {
              "$count": 32
            },
            "valueIndex": {
              "$count": 116
            },
            "value": {
              "$count": 105
            },
            "symbol": {
              "$count": 106
            },
            "lineStyle": {
              "normal": {
                "$count": 30,
                "type": {
                  "$count": 15
                },
                "color": {
                  "$count": 9
                },
                "shadowColor": {
                  "$count": 9
                },
                "shadowBlur": {
                  "$count": 8
                },
                "shadowOffsetX": {
                  "$count": 9
                },
                "shadowOffsetY": {
                  "$count": 7
                },
                "curveness": {
                  "$count": 13
                },
                "width": {
                  "$count": 5
                },
                "opacity": {
                  "$count": 6
                }
              },
              "emphasis": {
                "$count": 15,
                "width": {
                  "$count": 1
                },
                "color": {
                  "$count": 2
                },
                "type": {
                  "$count": 4
                },
                "shadowColor": {
                  "$count": 1
                },
                "shadowOffsetY": {
                  "$count": 2
                },
                "curveness": {
                  "$count": 2
                },
                "opacity": {
                  "$count": 2
                },
                "shadowOffsetX": {
                  "$count": 1
                }
              },
              "$count": 58
            },
            "label": {
              "$count": 37,
              "normal": {
                "formatter": {
                  "$count": 20
                },
                "position": {
                  "$count": 14
                },
                "$count": 13,
                "show": {
                  "$count": 5
                }
              },
              "emphasis": {
                "formatter": {
                  "$count": 5
                },
                "$count": 7,
                "show": {
                  "$count": 1
                },
                "position": {
                  "$count": 1
                }
              }
            },
            "$count": 229,
            "x": {
              "$count": 103
            },
            "y": {
              "$count": 53
            },
            "valueDim": {
              "$count": 74
            },
            "symbolSize": {
              "$count": 40
            },
            "symbolRotate": {
              "$count": 27
            }
          },
          "1": {
            "label": {
              "normal": {
                "formatter": {
                  "$count": 9
                },
                "show": {
                  "$count": 2
                },
                "position": {
                  "$count": 5
                },
                "$count": 5
              },
              "emphasis": {
                "formatter": {
                  "$count": 2
                },
                "$count": 2
              },
              "$count": 15
            },
            "$count": 90,
            "type": {
              "$count": 41
            },
            "valueIndex": {
              "$count": 22
            },
            "x": {
              "$count": 20
            },
            "value": {
              "$count": 15
            },
            "y": {
              "$count": 9
            },
            "coord": {
              "$count": 33
            },
            "symbolSize": {
              "$count": 10
            },
            "symbolRotate": {
              "$count": 6
            },
            "valueDim": {
              "$count": 18
            },
            "symbol": {
              "$count": 13
            },
            "lineStyle": {
              "emphasis": {
                "$count": 2,
                "color": {
                  "$count": 1
                }
              },
              "$count": 15,
              "normal": {
                "$count": 6,
                "color": {
                  "$count": 3
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
              }
            },
            "symbolOffset": {
              "$count": 2
            }
          },
          "$count": 462
        },
        "lineStyle": {
          "$count": 271,
          "normal": {
            "$count": 119,
            "width": {
              "$count": 48
            },
            "color": {
              "$count": 77
            },
            "opacity": {
              "$count": 34
            },
            "curveness": {
              "$count": 52
            },
            "type": {
              "$count": 71
            },
            "shadowColor": {
              "$count": 28
            },
            "shadowOffsetX": {
              "$count": 15
            },
            "shadowOffsetY": {
              "$count": 16
            },
            "shadowBlur": {
              "$count": 36
            }
          },
          "emphasis": {
            "$count": 46,
            "width": {
              "$count": 7
            },
            "color": {
              "$count": 9
            },
            "type": {
              "$count": 5
            },
            "opacity": {
              "$count": 3
            },
            "shadowBlur": {
              "$count": 3
            },
            "shadowColor": {
              "$count": 4
            },
            "shadowOffsetX": {
              "$count": 3
            },
            "shadowOffsetY": {
              "$count": 1
            }
          }
        },
        "label": {
          "normal": {
            "formatter": {
              "$count": 74
            },
            "$count": 109,
            "position": {
              "$count": 65
            },
            "show": {
              "$count": 44
            }
          },
          "$count": 221,
          "emphasis": {
            "$count": 53,
            "show": {
              "$count": 16
            },
            "position": {
              "$count": 13
            },
            "formatter": {
              "$count": 16
            }
          }
        },
        "$count": 1276,
        "precision": {
          "$count": 186
        },
        "symbol": {
          "$count": 453
        },
        "symbolSize": {
          "$count": 203
        },
        "animation": {
          "$count": 55
        },
        "animationEasing": {
          "$count": 22
        },
        "animationDuration": {
          "$count": 28
        },
        "animationDurationUpdate": {
          "$count": 18
        },
        "animationEasingUpdate": {
          "$count": 17
        }
      },
      "label": {
        "normal": {
          "show": {
            "$count": 229
          },
          "position": {
            "$count": 328
          },
          "formatter": {
            "$count": 466
          },
          "textStyle": {
            "$count": 188,
            "fontSize": {
              "$count": 32
            },
            "color": {
              "$count": 83
            },
            "fontStyle": {
              "$count": 33
            },
            "fontWeight": {
              "$count": 33
            },
            "fontFamily": {
              "$count": 28
            }
          },
          "$count": 461
        },
        "$count": 1066,
        "emphasis": {
          "$count": 276,
          "show": {
            "$count": 51
          },
          "position": {
            "$count": 68
          },
          "formatter": {
            "$count": 100
          },
          "textStyle": {
            "$count": 35,
            "color": {
              "$count": 16
            },
            "fontStyle": {
              "$count": 9
            },
            "fontWeight": {
              "$count": 7
            },
            "fontFamily": {
              "$count": 7
            },
            "fontSize": {
              "$count": 6
            }
          }
        }
      },
      "sampling": {
        "$count": 514
      },
      "animationEasingUpdate": {
        "$count": 100
      },
      "name": {
        "$count": 1052
      },
      "xAxisIndex": {
        "$count": 915
      },
      "areaStyle": {
        "emphasis": {
          "$count": 41,
          "color": {
            "$count": 9
          },
          "shadowBlur": {
            "$count": 4
          },
          "shadowColor": {
            "$count": 2
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
        "$count": 992,
        "normal": {
          "shadowBlur": {
            "$count": 142
          },
          "shadowColor": {
            "$count": 104
          },
          "opacity": {
            "$count": 149
          },
          "$count": 318,
          "color": {
            "$count": 298
          },
          "shadowOffsetX": {
            "$count": 62
          },
          "shadowOffsetY": {
            "$count": 43
          }
        }
      },
      "symbol": {
        "$count": 1694
      },
      "hoverAnimation": {
        "$count": 711
      },
      "symbolRotate": {
        "$count": 600
      },
      "showSymbol": {
        "$count": 899
      },
      "clipOverflow": {
        "$count": 657
      },
      "legendHoverLink": {
        "$count": 647
      },
      "zlevel": {
        "$count": 212
      },
      "z": {
        "$count": 153
      },
      "smoothMonotone": {
        "$count": 419
      },
      "animation": {
        "$count": 185
      },
      "animationDuration": {
        "$count": 121
      },
      "animationEasing": {
        "$count": 120
      },
      "animationDurationUpdate": {
        "$count": 104
      },
      "silent": {
        "$count": 102
      }
    },
    "map": {
      "$count": 2151,
      "selectedMode": {
        "$count": 422
      },
      "roam": {
        "$count": 492
      },
      "map": {
        "$count": 688
      },
      "scaleLimit": {
        "$count": 462,
        "min": {
          "$count": 106
        },
        "max": {
          "$count": 62
        }
      },
      "data": {
        "name": {
          "$count": 293
        },
        "$count": 433,
        "value": {
          "$count": 219
        },
        "itemStyle": {
          "$count": 57,
          "normal": {
            "opacity": {
              "$count": 14
            },
            "color": {
              "$count": 22
            },
            "areaColor": {
              "$count": 30
            },
            "$count": 38,
            "borderColor": {
              "$count": 11
            },
            "shadowOffsetY": {
              "$count": 7
            },
            "shadowBlur": {
              "$count": 6
            },
            "borderWidth": {
              "$count": 5
            },
            "shadowColor": {
              "$count": 5
            },
            "shadowOffsetX": {
              "$count": 4
            }
          },
          "emphasisObject)": {
            "borderWidth": {
              "$count": 1
            },
            "borderColor": {
              "$count": 2
            },
            "color": {
              "$count": 1
            },
            "shadowBlur": {
              "$count": 1
            },
            "shadowOffsetX": {
              "$count": 1
            }
          },
          "emphasis": {
            "$count": 29,
            "areaColor": {
              "$count": 10
            },
            "color": {
              "$count": 8
            },
            "borderWidth": {
              "$count": 6
            },
            "borderColor": {
              "$count": 5
            },
            "shadowBlur": {
              "$count": 5
            },
            "shadowColor": {
              "$count": 6
            },
            "shadowOffsetX": {
              "$count": 2
            },
            "shadowOffsetY": {
              "$count": 2
            },
            "opacity": {
              "$count": 4
            }
          }
        }
      },
      "label": {
        "$count": 468,
        "emphasis": {
          "$count": 124,
          "textStyle": {
            "$count": 28,
            "fontSize": {
              "$count": 6
            },
            "color": {
              "$count": 8
            },
            "fontStyle": {
              "$count": 5
            },
            "fontWeight": {
              "$count": 6
            },
            "fontFamily": {
              "$count": 5
            }
          },
          "show": {
            "$count": 33
          }
        },
        "normal": {
          "$count": 206,
          "textStyle": {
            "$count": 99,
            "fontStyle": {
              "$count": 59
            },
            "fontFamily": {
              "$count": 34
            },
            "fontSize": {
              "$count": 55
            },
            "fontWeight": {
              "$count": 44
            },
            "color": {
              "$count": 55
            }
          },
          "show": {
            "$count": 86
          }
        }
      },
      "itemStyle": {
        "$count": 500,
        "emphasis": {
          "$count": 153,
          "borderColor": {
            "$count": 41
          },
          "shadowBlur": {
            "$count": 38
          },
          "borderWidth": {
            "$count": 31
          },
          "opacity": {
            "$count": 38
          },
          "shadowColor": {
            "$count": 30
          },
          "color": {
            "$count": 113
          },
          "shadowOffsetX": {
            "$count": 19
          },
          "shadowOffsetY": {
            "$count": 14
          },
          "areaColor": {
            "$count": 29
          }
        },
        "normal": {
          "$count": 191,
          "borderWidth": {
            "$count": 58
          },
          "shadowBlur": {
            "$count": 64
          },
          "shadowOffsetX": {
            "$count": 30
          },
          "shadowColor": {
            "$count": 49
          },
          "color": {
            "$count": 132
          },
          "areaColor": {
            "$count": 231
          },
          "opacity": {
            "$count": 79
          },
          "borderColor": {
            "$count": 92
          },
          "shadowOffsetY": {
            "$count": 27
          }
        }
      },
      "zlevel": {
        "$count": 182
      },
      "type": {
        "$count": 617
      },
      "showLegendSymbol": {
        "$count": 451
      },
      "mapValueCalculation": {
        "$count": 394
      },
      "top": {
        "$count": 131
      },
      "nameMap": {
        "$count": 564
      },
      "name": {
        "$count": 372
      },
      "bottom": {
        "$count": 126
      },
      "right": {
        "$count": 105
      },
      "left": {
        "$count": 215
      },
      "z": {
        "$count": 138
      },
      "silent": {
        "$count": 93
      }
    },
    "treemap": {
      "data": {
        "children": {
          "$count": 17
        },
        "$count": 95,
        "target": {
          "$count": 15
        },
        "colorAlpha": {
          "$count": 8
        },
        "visualDimension": {
          "$count": 10
        },
        "name": {
          "$count": 11
        },
        "value": {
          "$count": 26
        },
        "colorMappingBy": {
          "$count": 12
        },
        "id": {
          "$count": 9
        },
        "link": {
          "$count": 37
        },
        "itemStyle": {
          "emphasis": {
            "$count": 2
          },
          "$count": 5,
          "normal": {
            "$count": 6,
            "color": {
              "$count": 1
            }
          }
        },
        "label": {
          "normal": {
            "textStyle": {
              "fontFamily": {
                "$count": 2
              },
              "$count": 3,
              "align": {
                "$count": 4
              },
              "fontWeight": {
                "$count": 2
              },
              "fontStyle": {
                "$count": 3
              },
              "color": {
                "$count": 3
              },
              "ellipsis": {
                "$count": 3
              },
              "baseline": {
                "$count": 2
              },
              "fontSize": {
                "$count": 3
              }
            },
            "position": {
              "$count": 4
            },
            "$count": 7,
            "show": {
              "$count": 3
            }
          },
          "emphasis": {
            "textStyle": {
              "$count": 1,
              "baseline": {
                "$count": 1
              }
            },
            "show": {
              "$count": 2
            },
            "$count": 2,
            "position": {
              "$count": 1
            }
          },
          "$count": 8
        },
        "colorSaturation": {
          "$count": 5
        },
        "color": {
          "$count": 22
        },
        "visibleMin": {
          "$count": 4
        },
        "childrenVisibleMin": {
          "$count": 9
        }
      },
      "$count": 911,
      "zoomToNodeRatio": {
        "$count": 60
      },
      "nodeClick": {
        "$count": 157
      },
      "levels": {
        "colorAlpha": {
          "$count": 12
        },
        "$count": 121,
        "itemStyle": {
          "normal": {
            "colorAlpha": {
              "$count": 2
            },
            "$count": 2,
            "gapWidth": {
              "$count": 6
            },
            "borderWidth": {
              "$count": 3
            },
            "borderColor": {
              "$count": 2
            },
            "borderColorSaturation": {
              "$count": 2
            },
            "colorSaturation": {
              "$count": 1
            }
          },
          "$count": 8,
          "emphasis": {
            "colorSaturation": {
              "$count": 1
            },
            "borderWidth": {
              "$count": 2
            },
            "borderColor": {
              "$count": 1
            },
            "gapWidth": {
              "$count": 1
            },
            "$count": 1
          }
        },
        "color": {
          "$count": 13
        },
        "visualDimension": {
          "$count": 23
        },
        "visibleMin": {
          "$count": 12
        },
        "childrenVisibleMin": {
          "$count": 9
        },
        "colorMappingBy": {
          "$count": 16
        },
        "label": {
          "$count": 21,
          "normal": {
            "textStyle": {
              "baseline": {
                "$count": 2
              },
              "fontFamily": {
                "$count": 1
              },
              "fontSize": {
                "$count": 1
              },
              "fontWeight": {
                "$count": 1
              },
              "ellipsis": {
                "$count": 5
              },
              "$count": 1,
              "align": {
                "$count": 1
              }
            },
            "$count": 10
          },
          "emphasis": {
            "textStyle": {
              "ellipsis": {
                "$count": 3
              }
            },
            "$count": 1
          }
        },
        "colorSaturation": {
          "$count": 8
        }
      },
      "type": {
        "$count": 68
      },
      "zlevel": {
        "$count": 25
      },
      "colorMappingBy": {
        "$count": 25
      },
      "breadcrumb": {
        "emptyItemWidth": {
          "$count": 8
        },
        "$count": 35,
        "top": {
          "$count": 4
        },
        "height": {
          "$count": 6
        },
        "show": {
          "$count": 3
        },
        "itemStyle": {
          "$count": 3,
          "normal": {
            "$count": 2,
            "color": {
              "$count": 1
            }
          }
        }
      },
      "roam": {
        "$count": 73
      },
      "top": {
        "$count": 22
      },
      "width": {
        "$count": 34
      },
      "animationDuration": {
        "$count": 10
      },
      "z": {
        "$count": 17
      },
      "left": {
        "$count": 25
      },
      "right": {
        "$count": 11
      },
      "bottom": {
        "$count": 18
      },
      "height": {
        "$count": 30
      },
      "squareRatio": {
        "$count": 46
      },
      "visualDimension": {
        "$count": 36
      },
      "color": {
        "$count": 28
      },
      "colorAlpha": {
        "$count": 18
      },
      "colorSaturation": {
        "$count": 17
      },
      "visibleMin": {
        "$count": 24
      },
      "childrenVisibleMin": {
        "$count": 22
      },
      "label": {
        "$count": 42,
        "normal": {
          "$count": 15,
          "show": {
            "$count": 8
          },
          "position": {
            "$count": 12
          },
          "textStyle": {
            "$count": 6,
            "fontFamily": {
              "$count": 7
            },
            "color": {
              "$count": 5
            },
            "ellipsis": {
              "$count": 15
            },
            "fontSize": {
              "$count": 1
            },
            "align": {
              "$count": 3
            },
            "baseline": {
              "$count": 4
            },
            "fontStyle": {
              "$count": 6
            },
            "fontWeight": {
              "$count": 3
            }
          }
        },
        "emphasis": {
          "textStyle": {
            "ellipsis": {
              "$count": 1
            }
          },
          "$count": 5,
          "show": {
            "$count": 1
          }
        }
      },
      "itemStyle": {
        "$count": 30,
        "normal": {
          "$count": 7,
          "borderColor": {
            "$count": 3
          },
          "borderColorSaturation": {
            "$count": 2
          },
          "gapWidth": {
            "$count": 1
          },
          "color": {
            "$count": 4
          },
          "borderWidth": {
            "$count": 1
          }
        },
        "emphasis": {
          "color": {
            "$count": 2
          },
          "$count": 5,
          "colorAlpha": {
            "$count": 1
          },
          "borderWidth": {
            "$count": 1
          }
        }
      },
      "animationEasing": {
        "$count": 7
      },
      "silent": {
        "$count": 14,
        "children": {
          "$count": 7
        },
        "target": {
          "$count": 3
        },
        "link": {
          "$count": 5
        }
      }
    },
    "scatter": {
      "$count": 1994,
      "markPoint": {
        "$count": 206,
        "data": {
          "$count": 73,
          "coord": {
            "$count": 41
          },
          "valueIndex": {
            "$count": 17
          },
          "itemStyle": {
            "$count": 15,
            "normal": {
              "$count": 6,
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
              "shadowBlur": {
                "$count": 1
              },
              "borderWidth": {
                "$count": 2
              },
              "borderColor": {
                "$count": 1
              }
            },
            "emphasis": {
              "$count": 3
            }
          },
          "name": {
            "$count": 30
          },
          "x": {
            "$count": 20
          },
          "value": {
            "$count": 27
          },
          "valueDim": {
            "$count": 19
          },
          "type": {
            "$count": 25
          },
          "symbol": {
            "$count": 12
          },
          "symbolSize": {
            "$count": 11
          },
          "y": {
            "$count": 5
          },
          "symbolRotate": {
            "$count": 3
          },
          "symbolOffset": {
            "$count": 4
          },
          "label": {
            "$count": 7,
            "normal": {
              "$count": 3,
              "show": {
                "$count": 1
              },
              "position": {
                "$count": 1
              },
              "textStyle": {
                "$count": 1
              }
            },
            "emphasis": {
              "$count": 1
            }
          }
        },
        "itemStyle": {
          "$count": 30,
          "normal": {
            "$count": 12,
            "color": {
              "$count": 8
            },
            "borderColor": {
              "$count": 2
            },
            "opacity": {
              "$count": 4
            },
            "shadowOffsetY": {
              "$count": 1
            },
            "shadowOffsetX": {
              "$count": 1
            },
            "shadowColor": {
              "$count": 2
            },
            "shadowBlur": {
              "$count": 1
            }
          },
          "emphasis": {
            "$count": 8,
            "borderColor": {
              "$count": 1
            }
          }
        },
        "symbol": {
          "$count": 76
        },
        "label": {
          "normal": {
            "$count": 13,
            "textStyle": {
              "$count": 2,
              "color": {
                "$count": 1
              },
              "fontStyle": {
                "$count": 1
              },
              "fontSize": {
                "$count": 2
              }
            },
            "show": {
              "$count": 4
            },
            "formatter": {
              "$count": 11
            },
            "position": {
              "$count": 8
            }
          },
          "$count": 22,
          "emphasis": {
            "position": {
              "$count": 1
            },
            "formatter": {
              "$count": 2
            },
            "textStyle": {
              "$count": 1
            },
            "$count": 3
          }
        },
        "symbolSize": {
          "$count": 39
        },
        "symbolRotate": {
          "$count": 19
        },
        "symbolOffset": {
          "$count": 17
        },
        "animation": {
          "$count": 16
        },
        "animationDuration": {
          "$count": 7
        },
        "animationEasing": {
          "$count": 8
        },
        "animationDurationUpdate": {
          "$count": 7
        },
        "animationEasingUpdate": {
          "$count": 9
        }
      },
      "data": {
        "$count": 363,
        "value": {
          "$count": 187
        },
        "name": {
          "$count": 147
        },
        "symbol": {
          "$count": 74
        },
        "label": {
          "$count": 50,
          "normal": {
            "$count": 30,
            "position": {
              "$count": 15
            },
            "show": {
              "$count": 11
            },
            "textStyle": {
              "$count": 8,
              "color": {
                "$count": 3
              },
              "fontStyle": {
                "$count": 3
              },
              "fontSize": {
                "$count": 2
              }
            }
          },
          "emphasis": {
            "position": {
              "$count": 5
            },
            "show": {
              "$count": 3
            },
            "$count": 15,
            "textStyle": {
              "$count": 4,
              "color": {
                "$count": 2
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
                "$count": 1
              }
            }
          }
        },
        "symbolSize": {
          "$count": 62
        },
        "symbolOffset": {
          "$count": 25
        },
        "symbolRotate": {
          "$count": 25
        },
        "itemStyle": {
          "normal": {
            "opacity": {
              "$count": 12
            },
            "$count": 22,
            "borderColor": {
              "$count": 11
            },
            "borderWidth": {
              "$count": 4
            },
            "shadowColor": {
              "$count": 5
            },
            "color": {
              "$count": 22
            },
            "shadowBlur": {
              "$count": 4
            },
            "shadowOffsetY": {
              "$count": 3
            },
            "shadowOffsetX": {
              "$count": 3
            }
          },
          "emphasis": {
            "$count": 10,
            "color": {
              "$count": 3
            }
          },
          "$count": 55
        }
      },
      "markLine": {
        "$count": 167,
        "data": {
          "0": {
            "$count": 40,
            "type": {
              "$count": 25
            },
            "valueIndex": {
              "$count": 14
            },
            "valueDim": {
              "$count": 9
            },
            "coord": {
              "$count": 33
            },
            "x": {
              "$count": 16
            },
            "y": {
              "$count": 9
            },
            "symbol": {
              "$count": 27
            },
            "value": {
              "$count": 13
            },
            "lineStyle": {
              "$count": 9,
              "normal": {
                "$count": 3,
                "color": {
                  "$count": 3
                },
                "width": {
                  "$count": 1
                },
                "type": {
                  "$count": 4
                },
                "shadowBlur": {
                  "$count": 1
                },
                "opacity": {
                  "$count": 1
                },
                "curveness": {
                  "$count": 1
                }
              },
              "emphasis": {
                "$count": 3
              }
            },
            "label": {
              "$count": 8,
              "normal": {
                "position": {
                  "$count": 2
                },
                "formatter": {
                  "$count": 5
                },
                "$count": 2
              },
              "emphasis": {
                "$count": 1
              }
            },
            "symbolSize": {
              "$count": 6
            },
            "symbolRotate": {
              "$count": 2
            },
            "symbolOffset": {
              "$count": 1
            }
          },
          "1": {
            "$count": 17,
            "lineStyle": {
              "$count": 1,
              "normal": {
                "color": {
                  "$count": 1
                }
              }
            },
            "label": {
              "normal": {
                "position": {
                  "$count": 3
                },
                "formatter": {
                  "$count": 3
                },
                "show": {
                  "$count": 2
                }
              },
              "$count": 3
            },
            "coord": {
              "$count": 2
            },
            "x": {
              "$count": 1
            },
            "type": {
              "$count": 3
            },
            "symbol": {
              "$count": 5
            }
          },
          "$count": 59
        },
        "symbol": {
          "$count": 45
        },
        "lineStyle": {
          "$count": 27,
          "normal": {
            "color": {
              "$count": 11
            },
            "curveness": {
              "$count": 9
            },
            "$count": 12,
            "opacity": {
              "$count": 4
            },
            "shadowOffsetY": {
              "$count": 5
            },
            "width": {
              "$count": 8
            },
            "type": {
              "$count": 14
            },
            "shadowBlur": {
              "$count": 7
            },
            "shadowColor": {
              "$count": 5
            },
            "shadowOffsetX": {
              "$count": 5
            }
          },
          "emphasis": {
            "$count": 6,
            "shadowBlur": {
              "$count": 1
            },
            "type": {
              "$count": 1
            }
          }
        },
        "label": {
          "normal": {
            "formatter": {
              "$count": 21
            },
            "$count": 15,
            "position": {
              "$count": 16
            },
            "show": {
              "$count": 8
            }
          },
          "$count": 16,
          "emphasis": {
            "position": {
              "$count": 2
            },
            "formatter": {
              "$count": 1
            },
            "$count": 5,
            "show": {
              "$count": 2
            }
          }
        },
        "precision": {
          "$count": 17
        },
        "animation": {
          "$count": 8
        },
        "symbolSize": {
          "$count": 14
        },
        "animationDuration": {
          "$count": 4
        },
        "animationDurationUpdate": {
          "$count": 2
        },
        "animationEasing": {
          "$count": 1
        },
        "animationEasingUpdate": {
          "$count": 2
        }
      },
      "xAxisIndex": {
        "$count": 126
      },
      "yAxisIndex": {
        "$count": 70
      },
      "label": {
        "$count": 148,
        "normal": {
          "$count": 51,
          "show": {
            "$count": 26
          },
          "textStyle": {
            "$count": 27,
            "color": {
              "$count": 6
            },
            "fontStyle": {
              "$count": 13
            },
            "fontWeight": {
              "$count": 9
            },
            "fontFamily": {
              "$count": 3
            },
            "fontSize": {
              "$count": 9
            }
          },
          "formatter": {
            "$count": 80
          },
          "position": {
            "$count": 43
          }
        },
        "emphasis": {
          "$count": 20,
          "textStyle": {
            "fontWeight": {
              "$count": 2
            },
            "fontStyle": {
              "$count": 2
            },
            "fontFamily": {
              "$count": 3
            },
            "fontSize": {
              "$count": 1
            },
            "$count": 7,
            "color": {
              "$count": 2
            }
          },
          "formatter": {
            "$count": 10
          },
          "show": {
            "$count": 4
          },
          "position": {
            "$count": 2
          }
        }
      },
      "symbolOffset": {
        "$count": 73
      },
      "symbolSize": {
        "$count": 219
      },
      "symbol": {
        "$count": 236
      },
      "legendHoverLink": {
        "$count": 83
      },
      "hoverAnimation": {
        "$count": 117
      },
      "geoIndex": {
        "$count": 94
      },
      "coordinateSystem": {
        "$count": 237
      },
      "name": {
        "$count": 122
      },
      "type": {
        "$count": 304
      },
      "itemStyle": {
        "$count": 192,
        "normal": {
          "opacity": {
            "$count": 34
          },
          "borderWidth": {
            "$count": 31
          },
          "shadowOffsetX": {
            "$count": 17
          },
          "shadowColor": {
            "$count": 23
          },
          "color": {
            "$count": 89
          },
          "borderColor": {
            "$count": 42
          },
          "shadowBlur": {
            "$count": 45
          },
          "$count": 87,
          "shadowOffsetY": {
            "$count": 15
          }
        },
        "emphasis": {
          "shadowBlur": {
            "$count": 5
          },
          "$count": 44,
          "color": {
            "$count": 17
          },
          "opacity": {
            "$count": 5
          },
          "borderWidth": {
            "$count": 2
          },
          "borderColor": {
            "$count": 4
          },
          "shadowOffsetY": {
            "$count": 2
          },
          "shadowOffsetX": {
            "$count": 2
          },
          "shadowColor": {
            "$count": 1
          }
        }
      },
      "symbolRotate": {
        "$count": 80
      },
      "largeThreshold": {
        "$count": 78
      },
      "large": {
        "$count": 106
      },
      "zlevel": {
        "$count": 32
      },
      "animationEasingUpdate": {
        "$count": 19
      },
      "animation": {
        "$count": 38
      },
      "polarIndex": {
        "$count": 61
      },
      "z": {
        "$count": 23
      },
      "animationDuration": {
        "$count": 16
      },
      "animationEasing": {
        "$count": 18
      },
      "animationDurationUpdate": {
        "$count": 14
      },
      "silent": {
        "$count": 15
      }
    },
    "gauge": {
      "axisTick": {
        "splitNumber": {
          "$count": 24
        },
        "lineStyle": {
          "$count": 16,
          "shadowColor": {
            "$count": 5
          },
          "width": {
            "$count": 4
          },
          "type": {
            "$count": 4
          },
          "color": {
            "$count": 6
          },
          "shadowBlur": {
            "$count": 5
          },
          "opacity": {
            "$count": 3
          },
          "shadowOffsetX": {
            "$count": 2
          },
          "shadowOffsetY": {
            "$count": 1
          }
        },
        "$count": 215,
        "length": {
          "$count": 16
        },
        "show": {
          "$count": 14
        }
      },
      "detail": {
        "$count": 272,
        "show": {
          "$count": 35
        },
        "width": {
          "$count": 40
        },
        "textStyle": {
          "$count": 54,
          "color": {
            "$count": 22
          },
          "fontFamily": {
            "$count": 14
          },
          "fontStyle": {
            "$count": 19
          },
          "fontWeight": {
            "$count": 18
          },
          "fontSize": {
            "$count": 29
          }
        },
        "borderWidth": {
          "$count": 17
        },
        "offsetCenter": {
          "$count": 59
        },
        "borderColor": {
          "$count": 22
        },
        "backgroundColor": {
          "$count": 32
        },
        "height": {
          "$count": 23
        }
      },
      "markPoint": {
        "symbol": {
          "$count": 37
        },
        "symbolOffset": {
          "$count": 15
        },
        "label": {
          "$count": 27,
          "normal": {
            "position": {
              "$count": 4
            },
            "$count": 8,
            "show": {
              "$count": 3
            },
            "formatter": {
              "$count": 9
            },
            "textStyle": {
              "$count": 2
            }
          },
          "emphasis": {
            "$count": 1,
            "formatter": {
              "$count": 2
            },
            "position": {
              "$count": 1
            }
          }
        },
        "$count": 174,
        "data": {
          "$count": 23,
          "name": {
            "$count": 3
          },
          "x": {
            "$count": 2
          },
          "label": {
            "$count": 5,
            "normal": {
              "position": {
                "$count": 2
              },
              "$count": 2,
              "textStyle": {
                "$count": 2
              },
              "show": {
                "$count": 1
              }
            }
          },
          "symbol": {
            "$count": 4
          },
          "symbolSize": {
            "$count": 5
          },
          "symbolRotate": {
            "$count": 3
          },
          "itemStyle": {
            "$count": 7,
            "normal": {
              "$count": 3,
              "color": {
                "$count": 2
              },
              "opacity": {
                "$count": 1
              }
            },
            "emphasis": {
              "$count": 3
            }
          },
          "value": {
            "$count": 7
          },
          "symbolOffset": {
            "$count": 2
          }
        },
        "symbolSize": {
          "$count": 22
        },
        "symbolRotate": {
          "$count": 14
        },
        "itemStyle": {
          "$count": 10,
          "normal": {
            "color": {
              "$count": 1
            },
            "$count": 1
          }
        },
        "animation": {
          "$count": 1
        }
      },
      "$count": 1208,
      "axisLabel": {
        "textStyle": {
          "color": {
            "$count": 16
          },
          "$count": 43,
          "fontSize": {
            "$count": 14
          },
          "fontFamily": {
            "$count": 7
          },
          "fontWeight": {
            "$count": 10
          },
          "fontStyle": {
            "$count": 11
          }
        },
        "$count": 263,
        "formatter": {
          "$count": 66
        },
        "show": {
          "$count": 30
        },
        "color": {
          "$count": 27
        }
      },
      "pointer": {
        "$count": 234,
        "show": {
          "$count": 29
        },
        "length": {
          "$count": 40
        },
        "width": {
          "$count": 35
        }
      },
      "itemStyle": {
        "$count": 222,
        "normal": {
          "borderWidth": {
            "$count": 4
          },
          "$count": 59,
          "color": {
            "$count": 28
          },
          "opacity": {
            "$count": 10
          },
          "shadowBlur": {
            "$count": 7
          },
          "borderColor": {
            "$count": 8
          },
          "shadowOffsetX": {
            "$count": 3
          },
          "shadowColor": {
            "$count": 3
          },
          "shadowOffsetY": {
            "$count": 1
          }
        },
        "emphasis": {
          "$count": 33,
          "borderColor": {
            "$count": 5
          },
          "opacity": {
            "$count": 3
          },
          "color": {
            "$count": 5
          },
          "borderWidth": {
            "$count": 3
          },
          "shadowBlur": {
            "$count": 3
          },
          "shadowColor": {
            "$count": 3
          },
          "shadowOffsetX": {
            "$count": 2
          },
          "shadowOffsetY": {
            "$count": 4
          }
        }
      },
      "axisLine": {
        "lineStyle": {
          "color": {
            "$count": 134
          },
          "$count": 98,
          "shadowBlur": {
            "$count": 30
          },
          "shadowColor": {
            "$count": 19
          },
          "opacity": {
            "$count": 24
          },
          "width": {
            "$count": 40
          },
          "shadowOffsetX": {
            "$count": 15
          },
          "shadowOffsetY": {
            "$count": 14
          }
        },
        "$count": 343,
        "show": {
          "$count": 62
        }
      },
      "max": {
        "$count": 84
      },
      "markLine": {
        "$count": 126,
        "symbol": {
          "$count": 14
        },
        "data": {
          "0": {
            "$count": 7,
            "x": {
              "$count": 4
            },
            "y": {
              "$count": 1
            },
            "value": {
              "$count": 5
            },
            "symbol": {
              "$count": 4
            },
            "symbolSize": {
              "$count": 3
            },
            "symbolRotate": {
              "$count": 1
            },
            "symbolOffset": {
              "$count": 2
            },
            "lineStyle": {
              "$count": 4,
              "normal": {
                "$count": 1
              }
            },
            "label": {
              "$count": 3,
              "normal": {
                "position": {
                  "$count": 2
                },
                "show": {
                  "$count": 1
                },
                "formatter": {
                  "$count": 4
                },
                "$count": 1
              },
              "emphasis": {
                "formatter": {
                  "$count": 3
                }
              }
            }
          },
          "1": {
            "label": {
              "emphasis": {
                "formatter": {
                  "$count": 2
                },
                "$count": 1
              },
              "normal": {
                "formatter": {
                  "$count": 2
                }
              }
            },
            "symbolSize": {
              "$count": 1
            }
          },
          "$count": 19
        },
        "precision": {
          "$count": 13
        },
        "lineStyle": {
          "$count": 5,
          "normal": {
            "color": {
              "$count": 1
            },
            "$count": 3
          },
          "emphasis": {
            "$count": 1
          }
        },
        "label": {
          "$count": 8,
          "normal": {
            "formatter": {
              "$count": 8
            },
            "show": {
              "$count": 3
            },
            "position": {
              "$count": 5
            },
            "$count": 4
          },
          "emphasis": {
            "formatter": {
              "$count": 2
            },
            "$count": 2
          }
        },
        "symbolSize": {
          "$count": 9
        },
        "animation": {
          "$count": 4
        },
        "animationEasingUpdate": {
          "$count": 2
        },
        "animationDurationUpdate": {
          "$count": 2
        },
        "animationDuration": {
          "$count": 1
        }
      },
      "type": {
        "$count": 169
      },
      "name": {
        "$count": 143
      },
      "splitLine": {
        "$count": 237,
        "length": {
          "$count": 36
        },
        "lineStyle": {
          "type": {
            "$count": 7
          },
          "shadowBlur": {
            "$count": 4
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
          },
          "width": {
            "$count": 5
          },
          "$count": 19,
          "color": {
            "$count": 7
          }
        },
        "show": {
          "$count": 15
        }
      },
      "title": {
        "$count": 200,
        "offsetCenter": {
          "$count": 61
        },
        "show": {
          "$count": 33
        },
        "textStyle": {
          "fontWeight": {
            "$count": 10
          },
          "$count": 37,
          "fontStyle": {
            "$count": 12
          },
          "fontFamily": {
            "$count": 10
          },
          "color": {
            "$count": 18
          },
          "fontSize": {
            "$count": 9
          }
        }
      },
      "animation": {
        "$count": 42
      },
      "animationDuration": {
        "$count": 31
      },
      "splitNumber": {
        "$count": 191
      },
      "radius": {
        "$count": 239
      },
      "clockwise": {
        "$count": 164
      },
      "startAngle": {
        "$count": 171
      },
      "endAngle": {
        "$count": 124
      },
      "min": {
        "$count": 90
      },
      "animationDurationUpdate": {
        "$count": 23
      },
      "animationEasingUpdate": {
        "$count": 25
      },
      "animationEasing": {
        "$count": 24
      },
      "silent": {
        "$count": 33
      }
    },
    "lines": {
      "$count": 1511,
      "effect": {
        "$count": 207,
        "show": {
          "$count": 67
        },
        "symbol": {
          "$count": 135
        },
        "symbolSize": {
          "$count": 65
        },
        "trailLength": {
          "$count": 81
        },
        "color": {
          "$count": 62
        },
        "period": {
          "$count": 69
        }
      },
      "markPoint": {
        "data": {
          "y": {
            "$count": 4
          },
          "x": {
            "$count": 9
          },
          "value": {
            "$count": 10
          },
          "symbol": {
            "$count": 5
          },
          "symbolRotate": {
            "$count": 2
          },
          "$count": 39,
          "name": {
            "$count": 17
          },
          "label": {
            "$count": 2,
            "emphasis": {
              "$count": 1
            },
            "normal": {
              "show": {
                "$count": 1
              },
              "position": {
                "$count": 3
              }
            }
          },
          "itemStyle": {
            "normal": {
              "$count": 1,
              "color": {
                "$count": 1
              }
            },
            "$count": 4,
            "emphasis": {
              "$count": 2,
              "color": {
                "$count": 1
              },
              "borderColor": {
                "$count": 1
              }
            }
          },
          "symbolOffset": {
            "$count": 3
          },
          "symbolSize": {
            "$count": 1
          }
        },
        "$count": 141,
        "symbol": {
          "$count": 34
        },
        "label": {
          "normal": {
            "position": {
              "$count": 11
            },
            "show": {
              "$count": 1
            },
            "formatter": {
              "$count": 9
            },
            "textStyle": {
              "$count": 3,
              "fontSize": {
                "$count": 1
              }
            },
            "$count": 6
          },
          "$count": 17,
          "emphasis": {
            "position": {
              "$count": 1
            },
            "formatter": {
              "$count": 1
            }
          }
        },
        "itemStyle": {
          "$count": 6,
          "normal": {
            "color": {
              "$count": 2
            },
            "borderWidth": {
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
            "$count": 2
          },
          "emphasis": {
            "shadowBlur": {
              "$count": 1
            }
          }
        },
        "animation": {
          "$count": 2
        },
        "animationDurationUpdate": {
          "$count": 2
        },
        "animationEasingUpdate": {
          "$count": 2
        },
        "animationEasing": {
          "$count": 1
        },
        "animationDuration": {
          "$count": 1
        },
        "symbolRotate": {
          "$count": 8
        },
        "symbolSize": {
          "$count": 10
        },
        "symbolOffset": {
          "$count": 11
        }
      },
      "lineStyle": {
        "$count": 141,
        "normal": {
          "color": {
            "$count": 61
          },
          "$count": 58,
          "shadowBlur": {
            "$count": 34
          },
          "shadowColor": {
            "$count": 21
          },
          "curveness": {
            "$count": 49
          },
          "type": {
            "$count": 48
          },
          "opacity": {
            "$count": 36
          },
          "width": {
            "$count": 35
          },
          "shadowOffsetX": {
            "$count": 15
          },
          "shadowOffsetY": {
            "$count": 10
          }
        },
        "emphasis": {
          "$count": 26,
          "opacity": {
            "$count": 6
          },
          "color": {
            "$count": 4
          },
          "shadowBlur": {
            "$count": 3
          },
          "type": {
            "$count": 3
          },
          "width": {
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
          }
        }
      },
      "type": {
        "$count": 232
      },
      "markLine": {
        "data": {
          "0": {
            "$count": 33,
            "x": {
              "$count": 34
            },
            "symbol": {
              "$count": 9
            },
            "symbolSize": {
              "$count": 3
            },
            "lineStyle": {
              "$count": 4,
              "normal": {
                "$count": 1
              }
            },
            "y": {
              "$count": 20
            },
            "value": {
              "$count": 8
            },
            "symbolOffset": {
              "$count": 2
            },
            "symbolRotate": {
              "$count": 2
            },
            "label": {
              "normal": {
                "$count": 1,
                "formatter": {
                  "$count": 1
                }
              },
              "emphasis": {
                "$count": 1,
                "position": {
                  "$count": 1
                }
              },
              "$count": 1
            }
          },
          "1": {
            "$count": 12,
            "symbolSize": {
              "$count": 1
            },
            "x": {
              "$count": 1
            },
            "y": {
              "$count": 1
            },
            "lineStyle": {
              "normal": {
                "type": {
                  "$count": 1
                }
              }
            },
            "value": {
              "$count": 1
            }
          },
          "$count": 59
        },
        "label": {
          "normal": {
            "$count": 5,
            "show": {
              "$count": 5
            },
            "position": {
              "$count": 7
            },
            "formatter": {
              "$count": 7
            }
          },
          "$count": 25,
          "emphasis": {
            "$count": 2,
            "position": {
              "$count": 1
            },
            "formatter": {
              "$count": 2
            }
          }
        },
        "$count": 141,
        "symbol": {
          "$count": 53
        },
        "symbolSize": {
          "$count": 24
        },
        "precision": {
          "$count": 26
        },
        "lineStyle": {
          "$count": 21,
          "normal": {
            "$count": 10,
            "color": {
              "$count": 3
            },
            "shadowColor": {
              "$count": 3
            },
            "type": {
              "$count": 5
            },
            "shadowBlur": {
              "$count": 3
            },
            "width": {
              "$count": 5
            },
            "opacity": {
              "$count": 2
            },
            "shadowOffsetY": {
              "$count": 1
            },
            "curveness": {
              "$count": 5
            }
          },
          "emphasis": {
            "$count": 9,
            "type": {
              "$count": 1
            },
            "color": {
              "$count": 1
            }
          }
        },
        "animationEasingUpdate": {
          "$count": 5
        },
        "animationDurationUpdate": {
          "$count": 4
        },
        "animationEasing": {
          "$count": 4
        },
        "animationDuration": {
          "$count": 5
        },
        "animation": {
          "$count": 8
        }
      },
      "yAxisIndex": {
        "$count": 41
      },
      "geoIndex": {
        "$count": 74
      },
      "zlevel": {
        "$count": 31
      },
      "animation": {
        "$count": 42
      },
      "coordinateSystem": {
        "$count": 142
      },
      "xAxisIndex": {
        "$count": 81
      },
      "data": {
        "0": {
          "$count": 39,
          "value": {
            "$count": 39
          },
          "coord": {
            "$count": 44
          },
          "name": {
            "$count": 37
          },
          "lineStyle": {
            "$count": 32,
            "normal": {
              "$count": 9,
              "shadowBlur": {
                "$count": 5
              },
              "shadowColor": {
                "$count": 4
              },
              "curveness": {
                "$count": 4
              },
              "type": {
                "$count": 5
              },
              "width": {
                "$count": 5
              },
              "color": {
                "$count": 9
              },
              "shadowOffsetY": {
                "$count": 2
              },
              "shadowOffsetX": {
                "$count": 2
              },
              "opacity": {
                "$count": 1
              }
            },
            "emphasis": {
              "$count": 6,
              "color": {
                "$count": 3
              }
            }
          }
        },
        "1": {
          "$count": 24,
          "name": {
            "$count": 6
          },
          "lineStyle": {
            "$count": 6,
            "emphasis": {
              "$count": 1
            },
            "normal": {
              "type": {
                "$count": 1
              }
            }
          },
          "coord": {
            "$count": 8
          }
        },
        "$count": 122
      },
      "name": {
        "$count": 84
      },
      "label": {
        "normal": {
          "position": {
            "$count": 22
          },
          "formatter": {
            "$count": 33
          },
          "show": {
            "$count": 19
          },
          "$count": 20
        },
        "$count": 75
      },
      "animationDuration": {
        "$count": 19
      },
      "animationEasingUpdate": {
        "$count": 17
      },
      "animationEasing": {
        "$count": 16
      },
      "animationDurationUpdate": {
        "$count": 10
      },
      "z": {
        "$count": 12
      },
      "silent": {
        "$count": 7
      }
    },
    "radar": {
      "$count": 972,
      "itemStyle": {
        "$count": 97,
        "emphasis": {
          "$count": 13,
          "color": {
            "$count": 2
          },
          "borderColor": {
            "$count": 5
          },
          "borderWidth": {
            "$count": 2
          },
          "shadowBlur": {
            "$count": 1
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
            "$count": 1
          }
        },
        "normal": {
          "color": {
            "$count": 33
          },
          "borderColor": {
            "$count": 26
          },
          "borderWidth": {
            "$count": 21
          },
          "shadowBlur": {
            "$count": 13
          },
          "shadowOffsetX": {
            "$count": 8
          },
          "shadowOffsetY": {
            "$count": 7
          },
          "$count": 38,
          "opacity": {
            "$count": 15
          },
          "shadowColor": {
            "$count": 11
          }
        }
      },
      "areaStyle": {
        "$count": 72,
        "normal": {
          "color": {
            "$count": 30
          },
          "$count": 33,
          "shadowBlur": {
            "$count": 17
          },
          "shadowColor": {
            "$count": 11
          },
          "shadowOffsetY": {
            "$count": 7
          },
          "shadowOffsetX": {
            "$count": 5
          },
          "opacity": {
            "$count": 11
          }
        },
        "emphasis": {
          "shadowBlur": {
            "$count": 1
          },
          "color": {
            "$count": 3
          },
          "$count": 13,
          "shadowOffsetY": {
            "$count": 1
          },
          "shadowOffsetX": {
            "$count": 1
          },
          "shadowColor": {
            "$count": 1
          }
        }
      },
      "radarIndex": {
        "$count": 98
      },
      "lineStyle": {
        "normal": {
          "opacity": {
            "$count": 3
          },
          "width": {
            "$count": 10
          },
          "$count": 24,
          "color": {
            "$count": 21
          },
          "type": {
            "$count": 9
          },
          "shadowOffsetY": {
            "$count": 4
          },
          "shadowOffsetX": {
            "$count": 3
          },
          "shadowColor": {
            "$count": 5
          },
          "shadowBlur": {
            "$count": 2
          }
        },
        "$count": 91,
        "emphasis": {
          "$count": 8,
          "color": {
            "$count": 3
          },
          "width": {
            "$count": 2
          },
          "type": {
            "$count": 1
          },
          "shadowBlur": {
            "$count": 1
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
            "$count": 1
          }
        }
      },
      "symbol": {
        "$count": 104
      },
      "symbolSize": {
        "$count": 73
      },
      "symbolRotate": {
        "$count": 66
      },
      "label": {
        "$count": 85,
        "normal": {
          "$count": 43,
          "show": {
            "$count": 21
          },
          "formatter": {
            "$count": 32
          },
          "textStyle": {
            "fontFamily": {
              "$count": 3
            },
            "color": {
              "$count": 7
            },
            "fontSize": {
              "$count": 5
            },
            "fontStyle": {
              "$count": 2
            },
            "$count": 10,
            "fontWeight": {
              "$count": 5
            }
          },
          "position": {
            "$count": 26
          }
        },
        "emphasis": {
          "$count": 22,
          "formatter": {
            "$count": 3
          },
          "show": {
            "$count": 1
          },
          "position": {
            "$count": 3
          },
          "textStyle": {
            "$count": 1,
            "color": {
              "$count": 2
            },
            "fontWeight": {
              "$count": 1
            }
          }
        }
      },
      "data": {
        "symbol": {
          "$count": 42
        },
        "itemStyle": {
          "$count": 29,
          "normal": {
            "$count": 13,
            "color": {
              "$count": 17
            },
            "barBorderColor": {
              "$count": 10
            },
            "barBorderWidth": {
              "$count": 7
            },
            "shadowBlur": {
              "$count": 2
            },
            "opacity": {
              "$count": 3
            },
            "shadowColor": {
              "$count": 1
            }
          },
          "emphasis": {
            "$count": 3,
            "barBorderColor": {
              "$count": 2
            },
            "barBorderWidth": {
              "$count": 1
            }
          }
        },
        "lineStyle": {
          "$count": 21,
          "normal": {
            "color": {
              "$count": 14
            },
            "$count": 13,
            "type": {
              "$count": 7
            },
            "shadowBlur": {
              "$count": 2
            },
            "shadowColor": {
              "$count": 3
            },
            "width": {
              "$count": 8
            },
            "opacity": {
              "$count": 1
            }
          },
          "emphasis": {
            "color": {
              "$count": 1
            },
            "$count": 3
          }
        },
        "areaStyle": {
          "$count": 20,
          "normal": {
            "color": {
              "$count": 5
            },
            "shadowBlur": {
              "$count": 2
            },
            "$count": 3,
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
              "$count": 1
            }
          },
          "emphasis": {
            "$count": 2
          }
        },
        "$count": 60,
        "value": {
          "$count": 36
        },
        "symbolSize": {
          "$count": 18
        },
        "name": {
          "$count": 27
        },
        "symbolRotate": {
          "$count": 14
        },
        "symbolOffset": {
          "$count": 13
        },
        "label": {
          "$count": 19,
          "emphasis": {
            "$count": 6,
            "textStyle": {
              "color": {
                "$count": 1
              },
              "fontStyle": {
                "$count": 1
              }
            }
          },
          "normal": {
            "position": {
              "$count": 6
            },
            "show": {
              "$count": 6
            },
            "textStyle": {
              "$count": 7,
              "fontStyle": {
                "$count": 3
              },
              "fontWeight": {
                "$count": 1
              },
              "color": {
                "$count": 1
              }
            },
            "$count": 11
          }
        }
      },
      "name": {
        "$count": 70
      },
      "type": {
        "$count": 96
      },
      "zlevel": {
        "$count": 13
      },
      "symbolOffset": {
        "$count": 57
      },
      "z": {
        "$count": 12
      },
      "animation": {
        "$count": 11
      },
      "animationEasing": {
        "$count": 5
      },
      "animationDuration": {
        "$count": 7
      },
      "animationDurationUpdate": {
        "$count": 3
      },
      "animationEasingUpdate": {
        "$count": 3
      },
      "silent": {
        "$count": 5
      }
    },
    "boxplot": {
      "$count": 781,
      "layout": {
        "$count": 22
      },
      "type": {
        "$count": 19
      },
      "coordinateSystem": {
        "$count": 13
      },
      "xAxisIndex": {
        "$count": 8
      },
      "yAxisIndex": {
        "$count": 5
      },
      "legendHoverLink": {
        "$count": 17
      },
      "hoverAnimation": {
        "$count": 12
      },
      "markLine": {
        "$count": 10,
        "data": {
          "0": {
            "lineStyle": {
              "$count": 1
            },
            "$count": 1
          },
          "1": {
            "$count": 2
          },
          "$count": 5
        },
        "symbol": {
          "$count": 2
        },
        "lineStyle": {
          "$count": 1,
          "normal": {
            "$count": 1,
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
        "label": {
          "$count": 1
        }
      },
      "data": {
        "$count": 39,
        "itemStyle": {
          "$count": 3,
          "normal": {
            "$count": 1
          }
        },
        "value": {
          "$count": 4
        },
        "name": {
          "$count": 2
        }
      },
      "markPoint": {
        "data": {
          "$count": 2
        },
        "symbol": {
          "$count": 2
        },
        "$count": 9,
        "label": {
          "$count": 1
        },
        "itemStyle": {
          "$count": 1,
          "normal": {
            "$count": 1
          }
        }
      },
      "itemStyle": {
        "$count": 15,
        "normal": {
          "color": {
            "$count": 1
          },
          "opacity": {
            "$count": 2
          },
          "$count": 3,
          "shadowOffsetY": {
            "$count": 1
          },
          "shadowOffsetX": {
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
          "$count": 2,
          "opacity": {
            "$count": 1
          }
        }
      },
      "boxWidth": {
        "$count": 12
      },
      "name": {
        "$count": 5
      },
      "animationEasing": {
        "$count": 1
      },
      "silent": {
        "$count": 1
      },
      "z": {
        "$count": 2
      },
      "zlevel": {
        "$count": 1
      }
    },
    "candlestick": {
      "$count": 786,
      "yAxisIndex": {
        "$count": 28
      },
      "markPoint": {
        "label": {
          "normal": {
            "formatter": {
              "$count": 13
            },
            "position": {
              "$count": 2
            },
            "$count": 4
          },
          "$count": 13,
          "emphasis": {
            "$count": 1
          }
        },
        "$count": 43,
        "data": {
          "$count": 15,
          "valueIndex": {
            "$count": 4
          },
          "valueDim": {
            "$count": 3
          },
          "label": {
            "$count": 3,
            "normal": {
              "position": {
                "$count": 2
              },
              "$count": 1
            }
          },
          "itemStyle": {
            "$count": 4,
            "normal": {
              "color": {
                "$count": 3
              },
              "$count": 1
            },
            "emphasis": {
              "color": {
                "$count": 1
              }
            }
          },
          "name": {
            "$count": 5
          },
          "coord": {
            "$count": 2
          },
          "x": {
            "$count": 1
          },
          "symbol": {
            "$count": 6
          },
          "symbolRotate": {
            "$count": 2
          },
          "value": {
            "$count": 3
          },
          "symbolSize": {
            "$count": 2
          },
          "symbolOffset": {
            "$count": 2
          }
        },
        "symbolOffset": {
          "$count": 7
        },
        "symbol": {
          "$count": 14
        },
        "animation": {
          "$count": 2
        },
        "animationDuration": {
          "$count": 1
        },
        "symbolSize": {
          "$count": 5
        },
        "symbolRotate": {
          "$count": 7
        },
        "itemStyle": {
          "$count": 5,
          "normal": {
            "$count": 1
          }
        }
      },
      "itemStyle": {
        "normal": {
          "color0": {
            "$count": 35
          },
          "color": {
            "$count": 57
          },
          "$count": 29,
          "shadowBlur": {
            "$count": 16
          },
          "shadowColor": {
            "$count": 12
          },
          "opacity": {
            "$count": 13
          },
          "borderColor": {
            "$count": 23
          },
          "borderColor0": {
            "$count": 16
          },
          "borderWidth": {
            "$count": 12
          },
          "shadowOffsetY": {
            "$count": 8
          },
          "shadowOffsetX": {
            "$count": 7
          }
        },
        "$count": 51,
        "emphasis": {
          "$count": 20,
          "color": {
            "$count": 3
          },
          "color0": {
            "$count": 2
          },
          "borderColor": {
            "$count": 4
          },
          "borderWidth": {
            "$count": 3
          },
          "borderColor0": {
            "$count": 2
          },
          "shadowBlur": {
            "$count": 1
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
            "$count": 3
          }
        }
      },
      "data": {
        "$count": 61,
        "itemStyle": {
          "$count": 16,
          "color": {
            "$count": 7
          },
          "color0": {
            "$count": 4
          },
          "normal": {
            "$count": 10
          },
          "emphasis": {
            "$count": 6
          },
          "borderColor": {
            "$count": 2
          },
          "opacity": {
            "$count": 1
          },
          "borderColor0": {
            "$count": 1
          },
          "borderWidth": {
            "$count": 1
          }
        },
        "name": {
          "$count": 42
        },
        "value": {
          "$count": 33
        }
      },
      "zlevel": {
        "$count": 10
      },
      "markLine": {
        "$count": 45,
        "data": {
          "0": {
            "coord": {
              "$count": 6
            },
            "$count": 14,
            "value": {
              "$count": 5
            },
            "symbol": {
              "$count": 5
            },
            "lineStyle": {
              "$count": 3,
              "normal": {
                "type": {
                  "$count": 1
                },
                "width": {
                  "$count": 2
                },
                "color": {
                  "$count": 1
                },
                "$count": 1
              }
            },
            "valueIndex": {
              "$count": 3
            },
            "x": {
              "$count": 3
            },
            "valueDim": {
              "$count": 3
            },
            "label": {
              "$count": 1
            },
            "symbolOffset": {
              "$count": 1
            },
            "symbolRotate": {
              "$count": 1
            },
            "symbolSize": {
              "$count": 1
            }
          },
          "1": {
            "$count": 6,
            "label": {
              "emphasis": {
                "$count": 1
              }
            }
          },
          "$count": 20
        },
        "label": {
          "$count": 5
        },
        "lineStyle": {
          "$count": 18,
          "normal": {
            "$count": 6,
            "color": {
              "$count": 4
            },
            "type": {
              "$count": 4
            },
            "opacity": {
              "$count": 2
            },
            "curveness": {
              "$count": 2
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
            "width": {
              "$count": 2
            }
          },
          "emphasis": {
            "$count": 2
          }
        },
        "precision": {
          "$count": 7
        },
        "symbol": {
          "$count": 18
        },
        "symbolSize": {
          "$count": 5
        },
        "animation": {
          "$count": 5
        },
        "animationEasingUpdate": {
          "$count": 1
        },
        "animationDurationUpdate": {
          "$count": 1
        },
        "animationDuration": {
          "$count": 1
        },
        "animationEasing": {
          "$count": 1
        }
      },
      "type": {
        "$count": 65
      },
      "coordinateSystem": {
        "$count": 45
      },
      "xAxisIndex": {
        "$count": 33
      },
      "name": {
        "$count": 38
      },
      "legendHoverLink": {
        "$count": 34
      },
      "layout": {
        "$count": 42
      },
      "animationDuration": {
        "$count": 15
      },
      "animationEasing": {
        "$count": 11
      },
      "hoverAnimation": {
        "$count": 25
      },
      "z": {
        "$count": 6
      },
      "silent": {
        "$count": 11
      }
    },
    "heatmap": {
      "$count": 953,
      "yAxisIndex": {
        "$count": 16
      },
      "type": {
        "$count": 110
      },
      "coordinateSystem": {
        "$count": 86
      },
      "markLine": {
        "$count": 36,
        "precision": {
          "$count": 2
        },
        "label": {
          "$count": 2,
          "emphasis": {
            "$count": 1
          }
        },
        "data": {
          "1": {
            "lineStyle": {
              "normal": {
                "$count": 1
              }
            }
          },
          "$count": 2
        },
        "symbolSize": {
          "$count": 4
        },
        "symbol": {
          "$count": 4
        },
        "lineStyle": {
          "normal": {
            "width": {
              "$count": 1
            },
            "$count": 1
          },
          "$count": 2
        }
      },
      "markPoint": {
        "$count": 63,
        "itemStyle": {
          "$count": 5,
          "normal": {
            "color": {
              "$count": 4
            },
            "borderColor": {
              "$count": 1
            },
            "shadowColor": {
              "$count": 1
            },
            "shadowBlur": {
              "$count": 1
            }
          },
          "emphasis": {
            "color": {
              "$count": 1
            }
          }
        },
        "symbol": {
          "$count": 10
        },
        "symbolSize": {
          "$count": 11
        },
        "label": {
          "emphasis": {
            "show": {
              "$count": 1
            },
            "textStyle": {
              "fontWeight": {
                "$count": 1
              },
              "fontFamily": {
                "$count": 1
              }
            }
          },
          "normal": {
            "formatter": {
              "$count": 6
            },
            "position": {
              "$count": 2
            },
            "textStyle": {
              "$count": 1,
              "color": {
                "$count": 1
              }
            },
            "$count": 6,
            "show": {
              "$count": 3
            }
          },
          "$count": 12
        },
        "symbolRotate": {
          "$count": 6
        },
        "symbolOffset": {
          "$count": 4
        },
        "data": {
          "$count": 8,
          "itemStyle": {
            "normal": {
              "$count": 2,
              "color": {
                "$count": 1
              }
            }
          },
          "symbol": {
            "$count": 2
          },
          "name": {
            "$count": 2
          },
          "x": {
            "$count": 2
          },
          "y": {
            "$count": 3
          },
          "value": {
            "$count": 2
          },
          "symbolSize": {
            "$count": 1
          },
          "symbolRotate": {
            "$count": 1
          }
        },
        "animation": {
          "$count": 4
        },
        "animationDuration": {
          "$count": 2
        },
        "animationEasing": {
          "$count": 1
        },
        "animationDurationUpdate": {
          "$count": 2
        },
        "animationEasingUpdate": {
          "$count": 1
        }
      },
      "data": {
        "$count": 111,
        "value": {
          "$count": 64
        },
        "itemStyle": {
          "normal": {
            "shadowColor": {
              "$count": 8
            },
            "$count": 35,
            "color": {
              "$count": 22
            },
            "borderColor": {
              "$count": 10
            },
            "borderWidth": {
              "$count": 10
            },
            "shadowBlur": {
              "$count": 5
            },
            "shadowOffsetX": {
              "$count": 5
            },
            "shadowOffsetY": {
              "$count": 4
            },
            "opacity": {
              "$count": 5
            }
          },
          "$count": 49,
          "emphasis": {
            "opacity": {
              "$count": 5
            },
            "shadowOffsetY": {
              "$count": 4
            },
            "shadowOffsetX": {
              "$count": 4
            },
            "shadowColor": {
              "$count": 6
            },
            "shadowBlur": {
              "$count": 4
            },
            "borderWidth": {
              "$count": 4
            },
            "borderColor": {
              "$count": 6
            },
            "color": {
              "$count": 7
            },
            "$count": 26
          }
        },
        "name": {
          "$count": 41
        },
        "label": {
          "$count": 56,
          "emphasis": {
            "position": {
              "$count": 7
            },
            "textStyle": {
              "$count": 7,
              "color": {
                "$count": 1
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
            },
            "show": {
              "$count": 6
            },
            "$count": 9
          },
          "normal": {
            "$count": 27,
            "show": {
              "$count": 9
            },
            "position": {
              "$count": 8
            },
            "textStyle": {
              "$count": 8,
              "color": {
                "$count": 2
              },
              "fontSize": {
                "$count": 1
              }
            }
          }
        }
      },
      "name": {
        "$count": 56
      },
      "maxOpacity": {
        "$count": 38
      },
      "xAxisIndex": {
        "$count": 42
      },
      "geoIndex": {
        "$count": 67
      },
      "blurSize": {
        "$count": 64
      },
      "minOpacity": {
        "$count": 48
      },
      "zlevel": {
        "$count": 17
      },
      "z": {
        "$count": 16
      },
      "silent": {
        "$count": 11
      }
    },
    "parallel": {
      "$count": 776,
      "type": {
        "$count": 20
      },
      "coordinateSystem": {
        "$count": 14
      },
      "name": {
        "$count": 7
      },
      "lineStyle": {
        "$count": 16,
        "normal": {
          "width": {
            "$count": 5
          },
          "$count": 9,
          "type": {
            "$count": 4
          },
          "color": {
            "$count": 7
          },
          "shadowBlur": {
            "$count": 2
          },
          "shadowColor": {
            "$count": 1
          },
          "shadowOffsetX": {
            "$count": 1
          }
        },
        "emphasis": {
          "$count": 10,
          "width": {
            "$count": 3
          },
          "shadowBlur": {
            "$count": 1
          },
          "shadowColor": {
            "$count": 1
          },
          "color": {
            "$count": 2
          },
          "type": {
            "$count": 1
          }
        }
      },
      "data": {
        "$count": 17,
        "lineStyle": {
          "$count": 2,
          "color": {
            "$count": 1
          },
          "normal": {
            "$count": 1
          }
        }
      },
      "activeOpacity": {
        "$count": 8
      },
      "parallelIndex": {
        "$count": 8
      },
      "inactiveOpacity": {
        "$count": 8
      },
      "animation": {
        "$count": 6
      },
      "animationDuration": {
        "$count": 3
      },
      "animationEasingUpdate": {
        "$count": 1
      },
      "animationDurationUpdate": {
        "$count": 2
      },
      "animationEasing": {
        "$count": 2
      },
      "z": {
        "$count": 2
      },
      "zlevel": {
        "$count": 2
      },
      "silent": {
        "$count": 1
      }
    },
    "sankey": {
      "$count": 823,
      "links": {
        "$count": 47,
        "source": {
          "$count": 17
        },
        "target": {
          "$count": 11
        },
        "value": {
          "$count": 14
        },
        "lineStyle": {
          "$count": 8,
          "emphasis": {
            "$count": 2,
            "curveness": {
              "$count": 1
            },
            "shadowOffsetY": {
              "$count": 1
            },
            "color": {
              "$count": 1
            }
          },
          "normal": {
            "shadowOffsetY": {
              "$count": 1
            },
            "shadowOffsetX": {
              "$count": 1
            },
            "shadowBlur": {
              "$count": 1
            },
            "curveness": {
              "$count": 2
            },
            "opacity": {
              "$count": 2
            },
            "$count": 3,
            "color": {
              "$count": 1
            }
          }
        }
      },
      "lineStyle": {
        "normal": {
          "$count": 8,
          "opacity": {
            "$count": 5
          },
          "color": {
            "$count": 5
          },
          "shadowColor": {
            "$count": 2
          },
          "curveness": {
            "$count": 2
          },
          "shadowBlur": {
            "$count": 1
          },
          "shadowOffsetX": {
            "$count": 1
          },
          "shadowOffsetY": {
            "$count": 1
          }
        },
        "$count": 19,
        "emphasis": {
          "$count": 2
        }
      },
      "color(Array": {
        "<string>)": {
          "$count": 45
        }
      },
      "width": {
        "$count": 12
      },
      "label": {
        "$count": 40,
        "normal": {
          "$count": 15,
          "formatter": {
            "$count": 11
          },
          "show": {
            "$count": 5
          },
          "textStyle": {
            "$count": 6,
            "color": {
              "$count": 3
            },
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
          "position": {
            "$count": 16
          }
        },
        "emphasis": {
          "$count": 10,
          "show": {
            "$count": 1
          },
          "position": {
            "$count": 4
          }
        }
      },
      "layoutIterations": {
        "$count": 22
      },
      "type": {
        "$count": 41
      },
      "nodeGap": {
        "$count": 18
      },
      "itemStyle": {
        "normal": {
          "$count": 9,
          "color": {
            "$count": 10
          },
          "shadowOffsetX": {
            "$count": 2
          },
          "opacity": {
            "$count": 1
          },
          "borderColor": {
            "$count": 1
          },
          "borderWidth": {
            "$count": 1
          },
          "shadowBlur": {
            "$count": 1
          },
          "shadowColor": {
            "$count": 1
          },
          "shadowOffsetY": {
            "$count": 1
          }
        },
        "$count": 25,
        "emphasis": {
          "$count": 4,
          "color": {
            "$count": 2
          }
        }
      },
      "data": {
        "$count": 68,
        "label": {
          "$count": 13,
          "normal": {
            "textStyle": {
              "$count": 4
            },
            "$count": 3,
            "show": {
              "$count": 6
            },
            "position": {
              "$count": 7
            }
          },
          "emphasis": {
            "$count": 1
          }
        },
        "itemStyle": {
          "$count": 11,
          "normal": {
            "$count": 4,
            "opacity": {
              "$count": 1
            },
            "color": {
              "$count": 7
            }
          },
          "emphasis": {
            "$count": 2,
            "opacity": {
              "$count": 1
            }
          }
        },
        "name": {
          "$count": 20
        },
        "value": {
          "$count": 17
        }
      },
      "nodes": {
        "$count": 48
      },
      "edges": {
        "$count": 23
      },
      "animation": {
        "$count": 10
      },
      "zlevel": {
        "$count": 22
      },
      "z": {
        "$count": 11
      },
      "left": {
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
        "$count": 13
      },
      "right": {
        "$count": 12
      },
      "bottom": {
        "$count": 6
      },
      "top": {
        "$count": 10
      },
      "height": {
        "$count": 12
      },
      "nodeWidth": {
        "$count": 15
      },
      "silent": {
        "$count": 5
      }
    },
    "funnel": {
      "$count": 848,
      "label": {
        "normal": {
          "$count": 17,
          "textStyle": {
            "fontSize": {
              "$count": 3
            },
            "$count": 9,
            "color": {
              "$count": 3
            },
            "fontStyle": {
              "$count": 1
            },
            "fontWeight": {
              "$count": 1
            }
          },
          "formatter": {
            "$count": 22
          },
          "position": {
            "$count": 23
          },
          "show": {
            "$count": 12
          }
        },
        "emphasis": {
          "$count": 18,
          "formatter": {
            "$count": 15
          },
          "textStyle": {
            "$count": 6,
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
            },
            "color": {
              "$count": 1
            }
          },
          "show": {
            "$count": 9
          }
        },
        "$count": 43
      },
      "type": {
        "$count": 37
      },
      "itemStyle": {
        "$count": 23,
        "emphasis": {
          "$count": 6,
          "shadowOffsetX": {
            "$count": 1
          },
          "shadowColor": {
            "$count": 2
          },
          "shadowBlur": {
            "$count": 3
          },
          "color": {
            "$count": 2
          },
          "borderColor": {
            "$count": 2
          },
          "shadowOffsetY": {
            "$count": 1
          }
        },
        "normal": {
          "color": {
            "$count": 6
          },
          "$count": 7,
          "opacity": {
            "$count": 4
          },
          "shadowBlur": {
            "$count": 7
          },
          "borderColor": {
            "$count": 9
          },
          "borderWidth": {
            "$count": 7
          },
          "shadowColor": {
            "$count": 3
          },
          "shadowOffsetY": {
            "$count": 2
          },
          "shadowOffsetX": {
            "$count": 2
          }
        }
      },
      "markLine": {
        "$count": 13,
        "data": {
          "0": {
            "x": {
              "$count": 5
            },
            "y": {
              "$count": 3
            },
            "value": {
              "$count": 5
            },
            "symbol": {
              "$count": 2
            },
            "$count": 1,
            "label": {
              "emphasis": {
                "show": {
                  "$count": 1
                },
                "formatter": {
                  "$count": 1
                },
                "$count": 1
              }
            },
            "symbolSize": {
              "$count": 2
            },
            "symbolOffset": {
              "$count": 1
            },
            "lineStyle": {
              "normal": {
                "$count": 1
              }
            }
          },
          "1": {
            "label": {
              "normal": {
                "position": {
                  "$count": 1
                }
              },
              "emphasis": {
                "position": {
                  "$count": 1
                }
              }
            },
            "symbolSize": {
              "$count": 1
            }
          },
          "$count": 4
        },
        "symbol": {
          "$count": 2
        },
        "symbolSize": {
          "$count": 2
        },
        "precision": {
          "$count": 2
        },
        "label": {
          "$count": 1
        }
      },
      "sort": {
        "$count": 66
      },
      "gap": {
        "$count": 30
      },
      "data": {
        "$count": 31,
        "name": {
          "$count": 18
        },
        "label": {
          "$count": 12,
          "normal": {
            "$count": 13,
            "textStyle": {
              "fontStyle": {
                "$count": 2
              },
              "$count": 2
            },
            "show": {
              "$count": 3
            },
            "position": {
              "$count": 3
            }
          },
          "emphasis": {
            "$count": 5,
            "show": {
              "$count": 2
            },
            "textStyle": {
              "fontStyle": {
                "$count": 1
              }
            }
          }
        },
        "value": {
          "$count": 18
        },
        "labelLine": {
          "$count": 11,
          "normal": {
            "$count": 3,
            "show": {
              "$count": 2
            },
            "lineStyle": {
              "$count": 1
            }
          },
          "emphasis": {
            "$count": 1
          }
        },
        "itemStyle": {
          "$count": 12,
          "normal": {
            "$count": 5,
            "color": {
              "$count": 10
            },
            "opacity": {
              "$count": 8
            },
            "borderWidth": {
              "$count": 7
            },
            "shadowOffsetY": {
              "$count": 2
            },
            "borderColor": {
              "$count": 7
            },
            "shadowBlur": {
              "$count": 3
            },
            "shadowColor": {
              "$count": 2
            },
            "shadowOffsetX": {
              "$count": 2
            }
          },
          "emphasis": {
            "$count": 9,
            "opacity": {
              "$count": 4
            },
            "shadowOffsetY": {
              "$count": 1
            },
            "color": {
              "$count": 2
            },
            "borderColor": {
              "$count": 1
            }
          }
        }
      },
      "min": {
        "$count": 23
      },
      "minSize": {
        "$count": 24
      },
      "animation": {
        "$count": 10
      },
      "legendHoverLink": {
        "$count": 36
      },
      "maxSize": {
        "$count": 26
      },
      "labelLine": {
        "$count": 31,
        "normal": {
          "$count": 9,
          "show": {
            "$count": 4
          },
          "length": {
            "$count": 2
          },
          "lineStyle": {
            "$count": 2
          }
        },
        "emphasis": {
          "$count": 1
        }
      },
      "animationDuration": {
        "$count": 8
      },
      "markPoint": {
        "$count": 11,
        "symbolRotate": {
          "$count": 1
        },
        "symbolSize": {
          "$count": 1
        },
        "symbol": {
          "$count": 1
        },
        "label": {
          "emphasis": {
            "formatter": {
              "$count": 1
            }
          }
        },
        "data": {
          "itemStyle": {
            "$count": 1
          },
          "$count": 2
        },
        "itemStyle": {
          "$count": 1
        }
      },
      "max": {
        "$count": 19
      },
      "name": {
        "$count": 18
      },
      "funnelAlign": {
        "$count": 43
      },
      "animationEasingUpdate": {
        "$count": 5
      },
      "animationDurationUpdate": {
        "$count": 5
      },
      "animationEasing": {
        "$count": 5
      },
      "silent": {
        "$count": 4
      }
    }
  },
  "visualMap": {
    "$count": 5547,
    "continuous": {
      "$count": 971,
      "calculable": {
        "$count": 616
      },
      "backgroundColor": {
        "$count": 105
      },
      "type": {
        "$count": 537
      },
      "min": {
        "$count": 246
      },
      "seriesIndex": {
        "$count": 376
      },
      "max": {
        "$count": 167
      },
      "precision": {
        "$count": 179
      },
      "align": {
        "$count": 131
      },
      "handlePosition": {
        "$count": 103
      },
      "orient": {
        "$count": 92
      },
      "formatter": {
        "$count": 153
      },
      "inRange": {
        "$count": 508
      },
      "outOfRange": {
        "$count": 252
      },
      "color": {
        "$count": 254
      },
      "textGap": {
        "$count": 117
      },
      "realtime": {
        "$count": 165
      },
      "inverse": {
        "$count": 193
      },
      "itemWidth": {
        "$count": 132
      },
      "itemHeight": {
        "$count": 109
      },
      "text": {
        "$count": 144
      },
      "show": {
        "$count": 136
      },
      "dimension": {
        "$count": 252
      },
      "right": {
        "$count": 44
      },
      "textStyle": {
        "$count": 88,
        "color": {
          "$count": 26
        },
        "fontStyle": {
          "$count": 13
        },
        "fontWeight": {
          "$count": 8
        },
        "fontFamily": {
          "$count": 5
        },
        "fontSize": {
          "$count": 9
        }
      },
      "borderWidth": {
        "$count": 54
      },
      "bottom": {
        "$count": 46
      },
      "padding": {
        "$count": 55
      },
      "left": {
        "$count": 79
      },
      "top": {
        "$count": 56
      },
      "borderColor": {
        "$count": 64
      },
      "zlevel": {
        "$count": 62
      },
      "z": {
        "$count": 39
      },
      "range": {
        "$count": 279
      }
    },
    "piecewise": {
      "align": {
        "$count": 67
      },
      "text": {
        "$count": 73
      },
      "itemSymbol": {
        "$count": 234
      },
      "inRange": {
        "$count": 224
      },
      "precision": {
        "$count": 90
      },
      "inverse": {
        "$count": 77
      },
      "selectedMode": {
        "$count": 135
      },
      "color": {
        "$count": 87
      },
      "outOfRange": {
        "$count": 86
      },
      "splitNumber": {
        "$count": 216
      },
      "pieces": {
        "$count": 319
      },
      "dimension": {
        "$count": 92
      },
      "$count": 740,
      "seriesIndex": {
        "$count": 121
      },
      "categories": {
        "$count": 292
      },
      "textGap": {
        "$count": 61
      },
      "textStyle": {
        "$count": 43,
        "color": {
          "$count": 8
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
          "$count": 5
        }
      },
      "formatter": {
        "$count": 90
      },
      "type": {
        "$count": 344
      },
      "min": {
        "$count": 99
      },
      "max": {
        "$count": 83
      },
      "top": {
        "$count": 38
      },
      "itemHeight": {
        "$count": 55
      },
      "left": {
        "$count": 34
      },
      "itemWidth": {
        "$count": 80
      },
      "show": {
        "$count": 68
      },
      "itemGap = 10": {
        "$count": 40
      },
      "backgroundColor": {
        "$count": 52
      },
      "bottom": {
        "$count": 25
      },
      "borderColor": {
        "$count": 35
      },
      "borderWidth": {
        "$count": 31
      },
      "zlevel": {
        "$count": 38
      },
      "padding": {
        "$count": 30
      },
      "orient": {
        "$count": 44
      },
      "seriesIndex(number|Array": {
        "<number>)": {
          "$count": 1
        }
      },
      "right": {
        "$count": 23
      },
      "z": {
        "$count": 20
      },
      "itemGap": {
        "$count": 12
      }
    }
  },
  "tooltip": {
    "$count": 9002,
    "showContent": {
      "$count": 1374
    },
    "formatter": {
      "$count": 3594
    },
    "trigger": {
      "$count": 2845
    },
    "enterable": {
      "$count": 746
    },
    "position": {
      "$count": 1204
    },
    "transitionDuration": {
      "$count": 774
    },
    "axisPointer": {
      "$count": 1507,
      "type": {
        "$count": 478
      },
      "axis": {
        "$count": 297
      },
      "animation": {
        "$count": 189
      },
      "animationEasingUpdate": {
        "$count": 79
      },
      "crossStyle": {
        "width": {
          "$count": 31
        },
        "$count": 142,
        "textStyle": {
          "color": {
            "$count": 10
          },
          "fontWeight": {
            "$count": 9
          },
          "fontFamily": {
            "$count": 10
          },
          "fontSize": {
            "$count": 11
          },
          "$count": 25,
          "fontStyle": {
            "$count": 10
          }
        },
        "type": {
          "$count": 43
        },
        "opacity": {
          "$count": 26
        },
        "shadowBlur": {
          "$count": 34
        },
        "color": {
          "$count": 44
        },
        "shadowColor": {
          "$count": 24
        },
        "shadowOffsetX": {
          "$count": 21
        },
        "shadowOffsetY": {
          "$count": 20
        }
      },
      "lineStyle": {
        "$count": 208,
        "shadowBlur": {
          "$count": 33
        },
        "opacity": {
          "$count": 45
        },
        "type": {
          "$count": 73
        },
        "color": {
          "$count": 62
        },
        "shadowOffsetY": {
          "$count": 24
        },
        "shadowOffsetX": {
          "$count": 21
        },
        "shadowColor": {
          "$count": 23
        },
        "width": {
          "$count": 31
        }
      },
      "shadowStyle": {
        "$count": 127,
        "color": {
          "$count": 47
        },
        "shadowBlur": {
          "$count": 29
        },
        "shadowColor": {
          "$count": 22
        },
        "opacity": {
          "$count": 26
        },
        "shadowOffsetX": {
          "$count": 21
        },
        "shadowOffsetY": {
          "$count": 14
        }
      },
      "animationEasing": {
        "$count": 80
      },
      "animationDuration": {
        "$count": 84
      },
      "animationDurationUpdate": {
        "$count": 65
      }
    },
    "show": {
      "$count": 1805
    },
    "alwaysShowContent": {
      "$count": 905
    },
    "backgroundColor": {
      "$count": 701
    },
    "extraCssText": {
      "$count": 670
    },
    "triggerOn": {
      "$count": 1273
    },
    "hideDelay": {
      "$count": 693
    },
    "textStyle": {
      "$count": 747,
      "fontWeight": {
        "$count": 77
      },
      "fontFamily": {
        "$count": 70
      },
      "color": {
        "$count": 132
      },
      "fontStyle": {
        "$count": 89
      },
      "fontSize": {
        "$count": 84
      }
    },
    "padding": {
      "$count": 453
    },
    "borderWidth": {
      "$count": 395
    },
    "borderColor": {
      "$count": 449
    },
    "showDelay": {
      "$count": 187
    }
  },
  "title": {
    "$count": 6510,
    "show": {
      "$count": 1883
    },
    "textStyle": {
      "$count": 1716,
      "fontStyle": {
        "$count": 458
      },
      "fontWeight": {
        "$count": 452
      },
      "fontSize": {
        "$count": 467
      },
      "fontFamily": {
        "$count": 371
      },
      "color": {
        "$count": 599
      }
    },
    "text": {
      "$count": 1651
    },
    "left": {
      "$count": 1135
    },
    "target": {
      "$count": 918
    },
    "link": {
      "$count": 947
    },
    "sublink": {
      "$count": 527
    },
    "backgroundColor": {
      "$count": 542
    },
    "subtext": {
      "$count": 1054
    },
    "subtarget": {
      "$count": 483
    },
    "itemGap": {
      "$count": 659
    },
    "padding": {
      "$count": 904
    },
    "bottom": {
      "$count": 504
    },
    "z": {
      "$count": 442
    },
    "zlevel": {
      "$count": 546
    },
    "borderWidth": {
      "$count": 343
    },
    "top": {
      "$count": 706
    },
    "right": {
      "$count": 459
    },
    "shadowBlur": {
      "$count": 396
    },
    "subtextStyle": {
      "$count": 881,
      "color": {
        "$count": 234
      },
      "fontSize": {
        "$count": 106
      },
      "fontWeight": {
        "$count": 95
      },
      "fontFamily": {
        "$count": 84
      },
      "fontStyle": {
        "$count": 96
      }
    },
    "shadowColor": {
      "$count": 321
    },
    "shadowOffsetX": {
      "$count": 279
    },
    "shadowOffsetY": {
      "$count": 243
    },
    "borderColor": {
      "$count": 402
    }
  },
  "grid": {
    "$count": 10519,
    "top": {
      "$count": 776
    },
    "left": {
      "$count": 1048
    },
    "containLabel": {
      "$count": 1214
    },
    "shadowOffsetY": {
      "$count": 235
    },
    "backgroundColor": {
      "$count": 737
    },
    "borderColor": {
      "$count": 631
    },
    "z": {
      "$count": 466
    },
    "zlevel": {
      "$count": 608
    },
    "borderWidth": {
      "$count": 518
    },
    "show": {
      "$count": 1542
    },
    "right": {
      "$count": 581
    },
    "width": {
      "$count": 715
    },
    "bottom": {
      "$count": 561
    },
    "height": {
      "$count": 544
    },
    "shadowOffsetX": {
      "$count": 327
    },
    "shadowBlur": {
      "$count": 420
    },
    "shadowColor": {
      "$count": 356
    }
  },
  "textStyle": {
    "$count": 3308,
    "fontSize": {
      "$count": 184
    },
    "fontFamily": {
      "$count": 160
    },
    "fontWeight": {
      "$count": 172
    },
    "fontStyle": {
      "$count": 235
    },
    "color": {
      "$count": 323
    }
  },
  "yAxis": {
    "$count": 7594,
    "type": {
      "$count": 1837
    },
    "name": {
      "$count": 1177
    },
    "nameLocation": {
      "$count": 1212
    },
    "nameTextStyle": {
      "$count": 1177,
      "fontSize": {
        "$count": 101
      },
      "fontStyle": {
        "$count": 113
      },
      "fontFamily": {
        "$count": 77
      },
      "color": {
        "$count": 175
      },
      "fontWeight": {
        "$count": 88
      }
    },
    "inverse": {
      "$count": 902
    },
    "boundaryGap": {
      "$count": 1252
    },
    "min": {
      "$count": 1075
    },
    "scale": {
      "$count": 1086
    },
    "interval": {
      "$count": 1149
    },
    "splitNumber": {
      "$count": 1245
    },
    "axisLabel": {
      "formatter": {
        "$count": 621
      },
      "$count": 1439,
      "interval": {
        "$count": 307
      },
      "margin": {
        "$count": 194
      },
      "inside": {
        "$count": 183
      },
      "rotate": {
        "$count": 147
      },
      "textStyle": {
        "$count": 230,
        "fontFamily": {
          "$count": 23
        },
        "fontSize": {
          "$count": 47
        },
        "color": {
          "$count": 47
        },
        "fontStyle": {
          "$count": 31
        },
        "fontWeight": {
          "$count": 21
        }
      },
      "show": {
        "$count": 200
      }
    },
    "axisTick": {
      "show": {
        "$count": 117
      },
      "$count": 940,
      "lineStyle": {
        "type": {
          "$count": 16
        },
        "$count": 110,
        "shadowColor": {
          "$count": 12
        },
        "color": {
          "$count": 28
        },
        "opacity": {
          "$count": 13
        },
        "shadowBlur": {
          "$count": 13
        },
        "shadowOffsetX": {
          "$count": 9
        },
        "shadowOffsetY": {
          "$count": 3
        },
        "width": {
          "$count": 15
        }
      },
      "length": {
        "$count": 112
      },
      "inside": {
        "$count": 85
      },
      "interval": {
        "$count": 159
      }
    },
    "axisLine": {
      "$count": 1238,
      "lineStyle": {
        "color": {
          "$count": 93
        },
        "$count": 239,
        "width": {
          "$count": 63
        },
        "type": {
          "$count": 61
        },
        "shadowBlur": {
          "$count": 40
        },
        "opacity": {
          "$count": 45
        },
        "shadowColor": {
          "$count": 36
        },
        "shadowOffsetX": {
          "$count": 28
        },
        "shadowOffsetY": {
          "$count": 26
        }
      },
      "onZero": {
        "$count": 214
      },
      "show": {
        "$count": 208
      }
    },
    "gridIndex": {
      "$count": 1412
    },
    "position": {
      "$count": 1522
    },
    "nameGap": {
      "$count": 1094
    },
    "splitLine": {
      "$count": 830,
      "lineStyle": {
        "shadowBlur": {
          "$count": 17
        },
        "shadowColor": {
          "$count": 11
        },
        "shadowOffsetX": {
          "$count": 11
        },
        "opacity": {
          "$count": 22
        },
        "type": {
          "$count": 51
        },
        "$count": 136,
        "shadowOffsetY": {
          "$count": 9
        },
        "color": {
          "$count": 62
        },
        "width": {
          "$count": 35
        }
      },
      "interval": {
        "$count": 122
      },
      "show": {
        "$count": 97
      }
    },
    "splitArea": {
      "$count": 607,
      "interval": {
        "$count": 77
      },
      "show": {
        "$count": 51
      },
      "areaStyle": {
        "$count": 87,
        "color": {
          "$count": 58
        },
        "opacity": {
          "$count": 13
        },
        "shadowOffsetY": {
          "$count": 10
        },
        "shadowOffsetX": {
          "$count": 9
        },
        "shadowColor": {
          "$count": 7
        },
        "shadowBlur": {
          "$count": 13
        }
      }
    },
    "data": {
      "$count": 972,
      "textStyle": {
        "color": {
          "$count": 91
        },
        "align": {
          "$count": 66
        },
        "$count": 250,
        "baseline": {
          "$count": 81
        },
        "fontWeight": {
          "$count": 25
        },
        "fontStyle": {
          "$count": 31
        },
        "fontFamily": {
          "$count": 25
        },
        "fontSize": {
          "$count": 40
        }
      },
      "value": {
        "$count": 471
      }
    },
    "max": {
      "$count": 840
    },
    "silent": {
      "$count": 284
    }
  },
  "timeline": {
    "$count": 3722,
    "label": {
      "emphasis": {
        "formatter": {
          "$count": 11
        },
        "$count": 24,
        "textStyle": {
          "$count": 8,
          "color": {
            "$count": 3
          }
        },
        "show": {
          "$count": 6
        },
        "interval": {
          "$count": 2
        },
        "rotate": {
          "$count": 3
        }
      },
      "normal": {
        "formatter": {
          "$count": 79
        },
        "interval": {
          "$count": 30
        },
        "rotate": {
          "$count": 18
        },
        "$count": 44,
        "textStyle": {
          "$count": 17,
          "color": {
            "$count": 5
          },
          "fontSize": {
            "$count": 5
          },
          "fontFamily": {
            "$count": 4
          },
          "fontStyle": {
            "$count": 3
          },
          "fontWeight": {
            "$count": 2
          }
        },
        "show": {
          "$count": 16
        }
      },
      "position": {
        "$count": 87
      },
      "$count": 123
    },
    "padding": {
      "$count": 55
    },
    "itemStyle": {
      "$count": 148,
      "normal": {
        "color": {
          "$count": 26
        },
        "$count": 39,
        "borderColor": {
          "$count": 4
        },
        "borderWidth": {
          "$count": 3
        },
        "opacity": {
          "$count": 7
        },
        "shadowOffsetY": {
          "$count": 4
        },
        "shadowOffsetX": {
          "$count": 6
        },
        "shadowColor": {
          "$count": 6
        },
        "shadowBlur": {
          "$count": 4
        }
      },
      "emphasis": {
        "color": {
          "$count": 12
        },
        "shadowBlur": {
          "$count": 4
        },
        "$count": 28,
        "opacity": {
          "$count": 5
        },
        "shadowOffsetY": {
          "$count": 3
        },
        "borderColor": {
          "$count": 6
        },
        "borderWidth": {
          "$count": 4
        },
        "shadowOffsetX": {
          "$count": 4
        },
        "shadowColor": {
          "$count": 1
        }
      }
    },
    "checkpointStyle": {
      "symbol": {
        "$count": 53
      },
      "$count": 86,
      "color": {
        "$count": 15
      },
      "symbolRotate": {
        "$count": 29
      },
      "symbolSize": {
        "$count": 64
      },
      "animation": {
        "$count": 12
      },
      "symbolOffset": {
        "$count": 26
      },
      "animationEasing": {
        "$count": 5
      },
      "animationDuration": {
        "$count": 5
      },
      "borderWidth": {
        "$count": 6
      },
      "borderColor": {
        "$count": 5
      }
    },
    "symbol": {
      "$count": 184
    },
    "show": {
      "$count": 273
    },
    "symbolSize": {
      "$count": 160
    },
    "data": {
      "$count": 151
    },
    "controlPosition": {
      "$count": 90
    },
    "controlStyle": {
      "position": {
        "$count": 21
      },
      "$count": 73,
      "stopIcon": {
        "$count": 9
      },
      "playIcon": {
        "$count": 18
      },
      "showPlayBtn": {
        "$count": 11
      },
      "showPrevBtn": {
        "$count": 6
      },
      "showNextBtn": {
        "$count": 5
      },
      "itemGap": {
        "$count": 14
      },
      "emphasis": {
        "$count": 15,
        "color": {
          "$count": 3
        },
        "borderWidth": {
          "$count": 2
        },
        "borderColor": {
          "$count": 2
        }
      },
      "normal": {
        "$count": 8,
        "borderWidth": {
          "$count": 3
        },
        "color": {
          "$count": 1
        },
        "borderColor": {
          "$count": 2
        }
      },
      "itemSize": {
        "$count": 11
      },
      "nextIcon": {
        "$count": 7
      },
      "show": {
        "$count": 7
      },
      "prevIcon": {
        "$count": 7
      }
    },
    "axisType": {
      "$count": 199
    },
    "left": {
      "$count": 66
    },
    "lineStyle": {
      "$count": 90,
      "color": {
        "$count": 12
      },
      "type": {
        "$count": 15
      },
      "show": {
        "$count": 10
      },
      "width": {
        "$count": 10
      },
      "shadowBlur": {
        "$count": 9
      },
      "shadowColor": {
        "$count": 2
      },
      "shadowOffsetX": {
        "$count": 4
      },
      "opacity": {
        "$count": 5
      },
      "shadowOffsetY": {
        "$count": 2
      }
    },
    "orient": {
      "$count": 75
    },
    "playInterval": {
      "$count": 104
    },
    "inverse": {
      "$count": 64
    },
    "realtime": {
      "$count": 86
    },
    "type": {
      "$count": 178
    },
    "currentIndex": {
      "$count": 114
    },
    "autoPlay": {
      "$count": 107
    },
    "rewind": {
      "$count": 93
    },
    "loop": {
      "$count": 80
    },
    "bottom": {
      "$count": 35
    },
    "symbolRotate": {
      "$count": 91
    },
    "symbolOffset": {
      "$count": 86
    },
    "zlevel": {
      "$count": 55
    },
    "z": {
      "$count": 52
    },
    "right": {
      "$count": 30
    },
    "top": {
      "$count": 56
    }
  },
  "color": {
    "$count": 5912
  },
  "geo": {
    "$count": 4654,
    "itemStyle": {
      "$count": 664,
      "normal": {
        "opacity": {
          "$count": 74
        },
        "color": {
          "$count": 147
        },
        "$count": 226,
        "borderWidth": {
          "$count": 69
        },
        "shadowColor": {
          "$count": 50
        },
        "borderColor": {
          "$count": 82
        },
        "shadowBlur": {
          "$count": 61
        },
        "shadowOffsetX": {
          "$count": 40
        },
        "shadowOffsetY": {
          "$count": 39
        }
      },
      "emphasis": {
        "$count": 125,
        "color": {
          "$count": 49
        },
        "borderColor": {
          "$count": 26
        },
        "opacity": {
          "$count": 17
        },
        "shadowBlur": {
          "$count": 15
        },
        "borderWidth": {
          "$count": 19
        },
        "shadowColor": {
          "$count": 19
        },
        "shadowOffsetX": {
          "$count": 12
        },
        "shadowOffsetY": {
          "$count": 8
        }
      }
    },
    "label": {
      "$count": 450,
      "emphasis": {
        "textStyle": {
          "$count": 42,
          "color": {
            "$count": 15
          },
          "fontWeight": {
            "$count": 11
          },
          "fontStyle": {
            "$count": 10
          },
          "fontSize": {
            "$count": 12
          },
          "fontFamily": {
            "$count": 10
          }
        },
        "$count": 129,
        "show": {
          "$count": 46
        }
      },
      "normal": {
        "$count": 175,
        "textStyle": {
          "$count": 67,
          "color": {
            "$count": 28
          },
          "fontWeight": {
            "$count": 13
          },
          "fontStyle": {
            "$count": 15
          },
          "fontFamily": {
            "$count": 17
          },
          "fontSize": {
            "$count": 15
          }
        },
        "show": {
          "$count": 81
        }
      }
    },
    "map": {
      "$count": 879
    },
    "show": {
      "$count": 533
    },
    "roam": {
      "$count": 566
    },
    "scaleLimit": {
      "$count": 434,
      "min": {
        "$count": 138
      },
      "max": {
        "$count": 81
      }
    },
    "zlevel": {
      "$count": 159
    },
    "nameMap": {
      "$count": 453
    },
    "z": {
      "$count": 105
    },
    "left": {
      "$count": 160
    },
    "top": {
      "$count": 88
    },
    "right": {
      "$count": 71
    },
    "bottom": {
      "$count": 80
    }
  },
  "parallel": {
    "$count": 2903,
    "parallelAxisDefault": {
      "inverse": {
        "$count": 6
      },
      "boundaryGap": {
        "$count": 15
      },
      "$count": 43,
      "type": {
        "$count": 13
      },
      "name": {
        "$count": 6
      },
      "axisLabel": {
        "formatter": {
          "$count": 14
        },
        "$count": 8,
        "inside": {
          "$count": 2
        },
        "margin": {
          "$count": 3
        },
        "interval": {
          "$count": 3
        },
        "rotate": {
          "$count": 4
        },
        "textStyle": {
          "$count": 3,
          "color": {
            "$count": 1
          }
        },
        "show": {
          "$count": 1
        }
      },
      "data": {
        "$count": 19,
        "value": {
          "$count": 5
        },
        "textStyle": {
          "$count": 4,
          "fontFamily": {
            "$count": 1
          }
        }
      },
      "splitNumber": {
        "$count": 5
      },
      "interval": {
        "$count": 6
      },
      "axisLine": {
        "$count": 10,
        "lineStyle": {
          "color": {
            "$count": 2
          },
          "$count": 3,
          "shadowBlur": {
            "$count": 1
          },
          "width": {
            "$count": 1
          },
          "type": {
            "$count": 2
          },
          "shadowColor": {
            "$count": 1
          }
        },
        "show": {
          "$count": 1
        }
      },
      "axisTick": {
        "$count": 3,
        "interval": {
          "$count": 2
        },
        "lineStyle": {
          "$count": 1,
          "type": {
            "$count": 1
          }
        }
      },
      "nameLocation": {
        "$count": 6
      },
      "nameTextStyle": {
        "$count": 6
      },
      "scale": {
        "$count": 3
      },
      "nameGap": {
        "$count": 3
      },
      "min": {
        "$count": 2
      },
      "max": {
        "$count": 3
      },
      "silent": {
        "$count": 4
      }
    },
    "z": {
      "$count": 14
    },
    "left": {
      "$count": 17
    },
    "right": {
      "$count": 7
    },
    "width": {
      "$count": 9
    },
    "height": {
      "$count": 16
    },
    "layout": {
      "$count": 27
    },
    "zlevel": {
      "$count": 46
    },
    "top": {
      "$count": 8
    },
    "bottom": {
      "$count": 8
    }
  },
  "legend": {
    "$count": 13852,
    "show": {
      "$count": 2070
    },
    "top": {
      "$count": 1265
    },
    "data": {
      "$count": 2308,
      "icon": {
        "$count": 1415
      },
      "textStyle": {
        "$count": 1344
      },
      "name": {
        "$count": 1108
      }
    },
    "backgroundColor": {
      "$count": 888
    },
    "selected": {
      "$count": 1590
    },
    "textStyle": {
      "$count": 1428,
      "color": {
        "$count": 449
      },
      "fontStyle": {
        "$count": 248
      },
      "fontFamily": {
        "$count": 177
      },
      "fontWeight": {
        "$count": 184
      },
      "fontSize": {
        "$count": 226
      }
    },
    "zlevel": {
      "$count": 1063
    },
    "z": {
      "$count": 820
    },
    "left": {
      "$count": 1694
    },
    "right": {
      "$count": 938
    },
    "bottom": {
      "$count": 1205
    },
    "width": {
      "$count": 985
    },
    "height": {
      "$count": 787
    },
    "orient": {
      "$count": 2039
    },
    "align": {
      "$count": 1418
    },
    "padding": {
      "$count": 1098
    },
    "itemGap": {
      "$count": 1251
    },
    "itemWidth": {
      "$count": 1025
    },
    "itemHeight": {
      "$count": 784
    },
    "selectedMode": {
      "$count": 1451
    },
    "formatter": {
      "$count": 1802
    },
    "borderColor": {
      "$count": 616
    },
    "borderWidth": {
      "$count": 442
    },
    "shadowBlur": {
      "$count": 427
    },
    "shadowColor": {
      "$count": 428
    },
    "shadowOffsetX": {
      "$count": 350
    },
    "shadowOffsetY": {
      "$count": 267
    }
  },
  "toolbox": {
    "$count": 5731,
    "feature": {
      "restore": {
        "$count": 468,
        "show": {
          "$count": 31
        },
        "iconStyle": {
          "emphasis": {
            "shadowOffsetY": {
              "$count": 1
            },
            "shadowBlur": {
              "$count": 2
            },
            "borderWidth": {
              "$count": 1
            },
            "$count": 24,
            "borderColor": {
              "$count": 3
            },
            "opacity": {
              "$count": 1
            },
            "shadowOffsetX": {
              "$count": 1
            }
          },
          "$count": 17,
          "normal": {
            "$count": 13,
            "borderColor": {
              "$count": 4
            },
            "shadowBlur": {
              "$count": 3
            },
            "shadowColor": {
              "$count": 2
            },
            "shadowOffsetY": {
              "$count": 2
            },
            "opacity": {
              "$count": 3
            },
            "shadowOffsetX": {
              "$count": 1
            },
            "color": {
              "$count": 2
            },
            "borderWidth": {
              "$count": 2
            }
          }
        },
        "title": {
          "$count": 19
        },
        "icon": {
          "$count": 28
        }
      },
      "$count": 1038,
      "dataZoom": {
        "$count": 718,
        "xAxisIndex": {
          "$count": 58
        },
        "icon": {
          "zoom": {
            "$count": 24
          },
          "$count": 29,
          "back": {
            "$count": 11
          }
        },
        "title": {
          "back": {
            "$count": 35
          },
          "$count": 53,
          "zoom": {
            "$count": 39
          }
        },
        "show": {
          "$count": 82
        },
        "yAxisIndex": {
          "$count": 37
        },
        "iconStyle": {
          "$count": 32,
          "normal": {
            "$count": 15,
            "borderWidth": {
              "$count": 4
            },
            "color": {
              "$count": 9
            },
            "borderColor": {
              "$count": 9
            },
            "shadowBlur": {
              "$count": 2
            },
            "shadowColor": {
              "$count": 2
            },
            "shadowOffsetX": {
              "$count": 1
            },
            "opacity": {
              "$count": 1
            }
          },
          "emphasis": {
            "$count": 14,
            "color": {
              "$count": 5
            },
            "opacity": {
              "$count": 1
            },
            "borderColor": {
              "$count": 4
            },
            "borderWidth": {
              "$count": 1
            },
            "shadowBlur": {
              "$count": 1
            }
          }
        }
      },
      "magicType": {
        "title": {
          "stack": {
            "$count": 113
          },
          "line": {
            "$count": 34
          },
          "$count": 79,
          "bar": {
            "$count": 48
          },
          "tiled": {
            "$count": 14
          }
        },
        "option": {
          "stack": {
            "$count": 113
          },
          "line": {
            "$count": 102
          },
          "$count": 151,
          "bar": {
            "$count": 101
          },
          "tiled": {
            "$count": 36
          }
        },
        "$count": 756,
        "type": {
          "$count": 202
        },
        "icon": {
          "line": {
            "$count": 25
          },
          "stack": {
            "$count": 56
          },
          "bar": {
            "$count": 30
          },
          "tiled": {
            "$count": 9
          },
          "$count": 39
        },
        "seriesIndex": {
          "line": {
            "$count": 39
          },
          "stack": {
            "$count": 66
          },
          "$count": 74,
          "bar": {
            "$count": 42
          },
          "tiled": {
            "$count": 13
          }
        },
        "show": {
          "$count": 61
        },
        "iconStyle": {
          "$count": 35,
          "normal": {
            "$count": 12,
            "opacity": {
              "$count": 4
            },
            "borderColor": {
              "$count": 3
            },
            "borderWidth": {
              "$count": 3
            },
            "color": {
              "$count": 2
            },
            "shadowOffsetX": {
              "$count": 1
            },
            "shadowOffsetY": {
              "$count": 3
            },
            "shadowColor": {
              "$count": 1
            },
            "shadowBlur": {
              "$count": 1
            }
          },
          "emphasis": {
            "$count": 13,
            "color": {
              "$count": 2
            },
            "borderColor": {
              "$count": 4
            },
            "shadowBlur": {
              "$count": 5
            },
            "borderWidth": {
              "$count": 3
            },
            "shadowColor": {
              "$count": 4
            },
            "shadowOffsetY": {
              "$count": 2
            },
            "opacity": {
              "$count": 2
            },
            "shadowOffsetX": {
              "$count": 3
            }
          }
        }
      },
      "dataView": {
        "$count": 676,
        "lang": {
          "$count": 84
        },
        "contentToOption": {
          "$count": 92
        },
        "readOnly": {
          "$count": 87
        },
        "optionToContent": {
          "$count": 178
        },
        "icon": {
          "$count": 53
        },
        "title": {
          "$count": 71
        },
        "show": {
          "$count": 58
        },
        "buttonColor": {
          "$count": 30
        },
        "buttonTextColor": {
          "$count": 26
        },
        "iconStyle": {
          "$count": 43,
          "normal": {
            "$count": 20,
            "borderWidth": {
              "$count": 2
            },
            "shadowBlur": {
              "$count": 1
            },
            "shadowColor": {
              "$count": 2
            },
            "borderColor": {
              "$count": 2
            },
            "shadowOffsetX": {
              "$count": 1
            },
            "opacity": {
              "$count": 1
            },
            "color": {
              "$count": 4
            }
          },
          "emphasis": {
            "$count": 18
          }
        },
        "backgroundColor": {
          "$count": 43
        },
        "textareaBorderColor": {
          "$count": 23
        },
        "textColor": {
          "$count": 27
        },
        "textareaColor": {
          "$count": 33
        }
      },
      "saveAsImage": {
        "$count": 736,
        "type": {
          "$count": 102
        },
        "name": {
          "$count": 104
        },
        "backgroundColor": {
          "$count": 86
        },
        "excludeComponents": {
          "$count": 88
        },
        "show": {
          "$count": 67
        },
        "title": {
          "$count": 79
        },
        "icon": {
          "$count": 110
        },
        "iconStyle": {
          "normal": {
            "$count": 55,
            "color": {
              "$count": 17
            },
            "borderColor": {
              "$count": 21
            },
            "borderWidth": {
              "$count": 20
            },
            "shadowBlur": {
              "$count": 8
            },
            "shadowColor": {
              "$count": 5
            },
            "shadowOffsetX": {
              "$count": 6
            },
            "opacity": {
              "$count": 5
            },
            "shadowOffsetY": {
              "$count": 1
            }
          },
          "emphasis": {
            "$count": 69,
            "color": {
              "$count": 15
            },
            "borderColor": {
              "$count": 11
            },
            "borderWidth": {
              "$count": 11
            },
            "shadowColor": {
              "$count": 7
            },
            "shadowOffsetX": {
              "$count": 9
            },
            "shadowOffsetY": {
              "$count": 8
            },
            "shadowBlur": {
              "$count": 8
            },
            "opacity": {
              "$count": 7
            }
          },
          "$count": 70
        },
        "pixelRatio": {
          "$count": 60
        }
      }
    },
    "orient": {
      "$count": 476
    },
    "show": {
      "$count": 675
    },
    "iconStyle": {
      "$count": 316,
      "normal": {
        "$count": 111,
        "borderColor": {
          "$count": 22
        },
        "color": {
          "$count": 34
        },
        "borderWidth": {
          "$count": 11
        },
        "shadowBlur": {
          "$count": 13
        },
        "shadowColor": {
          "$count": 7
        },
        "shadowOffsetX": {
          "$count": 6
        },
        "shadowOffsetY": {
          "$count": 6
        },
        "opacity": {
          "$count": 8
        }
      },
      "emphasis": {
        "$count": 66,
        "color": {
          "$count": 16
        },
        "borderColor": {
          "$count": 8
        },
        "borderWidth": {
          "$count": 4
        },
        "shadowBlur": {
          "$count": 8
        },
        "shadowColor": {
          "$count": 5
        },
        "shadowOffsetX": {
          "$count": 5
        },
        "shadowOffsetY": {
          "$count": 5
        },
        "opacity": {
          "$count": 6
        }
      }
    },
    "top": {
      "$count": 102
    },
    "itemSize": {
      "$count": 339
    },
    "itemGap": {
      "$count": 284
    },
    "showTitle": {
      "$count": 333
    },
    "left": {
      "$count": 153
    },
    "zlevel": {
      "$count": 105
    },
    "height": {
      "$count": 73
    },
    "z": {
      "$count": 73
    },
    "bottom": {
      "$count": 75
    },
    "right": {
      "$count": 107
    },
    "width": {
      "$count": 90
    }
  },
  "dataZoom": {
    "slider": {
      "dataBackgroundColor": {
        "$count": 149
      },
      "backgroundColor": {
        "$count": 195
      },
      "filterMode": {
        "$count": 135
      },
      "$count": 941,
      "xAxisIndex": {
        "$count": 156
      },
      "showDataShadow": {
        "$count": 138
      },
      "yAxisIndex": {
        "$count": 97
      },
      "type": {
        "$count": 469
      },
      "top": {
        "$count": 102
      },
      "left": {
        "$count": 90
      },
      "show": {
        "$count": 159
      },
      "showDetail": {
        "$count": 174
      },
      "start": {
        "$count": 142
      },
      "z": {
        "$count": 61
      },
      "fillerColor": {
        "$count": 135
      },
      "realtime": {
        "$count": 202
      },
      "throttle": {
        "$count": 79
      },
      "angleAxisIndex": {
        "$count": 78
      },
      "handleColor": {
        "$count": 134
      },
      "handleSize": {
        "$count": 167
      },
      "labelPrecision": {
        "$count": 157
      },
      "labelFormatter": {
        "$count": 174
      },
      "textStyle": {
        "$count": 127,
        "fontStyle": {
          "$count": 8
        },
        "fontWeight": {
          "$count": 11
        },
        "fontSize": {
          "$count": 9
        },
        "fontFamily": {
          "$count": 12
        },
        "color": {
          "$count": 28
        }
      },
      "end": {
        "$count": 69
      },
      "startValue": {
        "$count": 105
      },
      "endValue": {
        "$count": 54
      },
      "zlevel": {
        "$count": 61
      },
      "radiusAxisIndex": {
        "$count": 71
      },
      "zoomLock": {
        "$count": 106
      },
      "orient": {
        "$count": 100
      },
      "right": {
        "$count": 43
      },
      "bottom": {
        "$count": 77
      }
    },
    "inside": {
      "throttle": {
        "$count": 192
      },
      "filterMode": {
        "$count": 269
      },
      "zoomLock": {
        "$count": 208
      },
      "orient": {
        "$count": 210
      },
      "xAxisIndex": {
        "$count": 434
      },
      "$count": 1330,
      "radiusAxisIndex": {
        "$count": 124
      },
      "type": {
        "$count": 745
      },
      "startValue": {
        "$count": 245
      },
      "angleAxisIndex": {
        "$count": 168
      },
      "start": {
        "$count": 379
      },
      "yAxisIndex": {
        "$count": 253
      },
      "end": {
        "$count": 171
      },
      "endValue": {
        "$count": 123
      }
    },
    "$count": 5969
  },
  "polar": {
    "$count": 4195,
    "center": {
      "$count": 202
    },
    "zlevel": {
      "$count": 186
    },
    "z": {
      "$count": 88
    },
    "radius": {
      "$count": 245
    }
  },
  "radiusAxis": {
    "$count": 3761,
    "axisLabel": {
      "formatter": {
        "$count": 61
      },
      "$count": 42,
      "show": {
        "$count": 4
      },
      "margin": {
        "$count": 5
      },
      "rotate": {
        "$count": 8
      },
      "interval": {
        "$count": 7
      },
      "inside": {
        "$count": 4
      },
      "textStyle": {
        "$count": 4,
        "fontStyle": {
          "$count": 1
        },
        "color": {
          "$count": 1
        }
      }
    },
    "data": {
      "textStyle": {
        "baseline": {
          "$count": 11
        },
        "fontFamily": {
          "$count": 1
        },
        "align": {
          "$count": 2
        },
        "$count": 10,
        "color": {
          "$count": 1
        }
      },
      "$count": 50,
      "value": {
        "$count": 18
      }
    },
    "axisLine": {
      "lineStyle": {
        "$count": 13,
        "color": {
          "$count": 14
        },
        "width": {
          "$count": 8
        },
        "type": {
          "$count": 3
        },
        "shadowOffsetX": {
          "$count": 3
        },
        "shadowBlur": {
          "$count": 5
        },
        "shadowColor": {
          "$count": 4
        },
        "opacity": {
          "$count": 2
        },
        "shadowOffsetY": {
          "$count": 1
        }
      },
      "$count": 43,
      "show": {
        "$count": 10
      }
    },
    "boundaryGap": {
      "$count": 50
    },
    "polarIndex": {
      "$count": 132
    },
    "nameTextStyle": {
      "$count": 53,
      "color": {
        "$count": 15
      },
      "fontStyle": {
        "$count": 6
      },
      "fontWeight": {
        "$count": 5
      },
      "fontFamily": {
        "$count": 6
      },
      "fontSize": {
        "$count": 6
      }
    },
    "type": {
      "$count": 88
    },
    "name": {
      "$count": 52
    },
    "nameLocation": {
      "$count": 52
    },
    "nameGap": {
      "$count": 49
    },
    "inverse": {
      "$count": 39
    },
    "min": {
      "$count": 34
    },
    "max": {
      "$count": 25
    },
    "splitNumber": {
      "$count": 41
    },
    "interval": {
      "$count": 37
    },
    "axisTick": {
      "show": {
        "$count": 1
      },
      "$count": 26,
      "lineStyle": {
        "$count": 7,
        "width": {
          "$count": 2
        },
        "color": {
          "$count": 3
        },
        "type": {
          "$count": 3
        },
        "shadowBlur": {
          "$count": 1
        }
      },
      "interval": {
        "$count": 7
      },
      "inside": {
        "$count": 3
      },
      "length": {
        "$count": 2
      }
    },
    "splitLine": {
      "$count": 34,
      "show": {
        "$count": 5
      },
      "interval": {
        "$count": 11
      },
      "lineStyle": {
        "$count": 10,
        "color": {
          "$count": 2
        },
        "type": {
          "$count": 2
        },
        "shadowColor": {
          "$count": 1
        }
      }
    },
    "splitArea": {
      "$count": 26,
      "areaStyle": {
        "$count": 9,
        "opacity": {
          "$count": 3
        },
        "shadowOffsetY": {
          "$count": 1
        },
        "color": {
          "$count": 13
        },
        "shadowBlur": {
          "$count": 2
        },
        "shadowColor": {
          "$count": 1
        }
      },
      "interval": {
        "$count": 7
      },
      "show": {
        "$count": 2
      }
    },
    "scale": {
      "$count": 33
    },
    "silent": {
      "$count": 13
    }
  },
  "radar": {
    "axisTick": {
      "$count": 113,
      "show": {
        "$count": 19
      },
      "inside": {
        "$count": 12
      },
      "length": {
        "$count": 15
      },
      "lineStyle": {
        "$count": 11,
        "color": {
          "$count": 4
        },
        "width": {
          "$count": 4
        },
        "type": {
          "$count": 7
        },
        "shadowBlur": {
          "$count": 3
        },
        "shadowColor": {
          "$count": 3
        },
        "shadowOffsetX": {
          "$count": 3
        },
        "shadowOffsetY": {
          "$count": 3
        },
        "opacity": {
          "$count": 2
        }
      }
    },
    "$count": 3523,
    "axisLine": {
      "$count": 144,
      "show": {
        "$count": 15
      },
      "lineStyle": {
        "$count": 24,
        "color": {
          "$count": 15
        },
        "type": {
          "$count": 16
        },
        "shadowBlur": {
          "$count": 6
        },
        "shadowColor": {
          "$count": 5
        },
        "opacity": {
          "$count": 5
        },
        "width": {
          "$count": 7
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
      "$count": 172,
      "formatter": {
        "$count": 157
      },
      "show": {
        "$count": 65
      }
    },
    "startAngle": {
      "$count": 144
    },
    "radius": {
      "$count": 211
    },
    "center": {
      "$count": 171
    },
    "z": {
      "$count": 68
    },
    "zlevel": {
      "$count": 138
    },
    "nameGap": {
      "$count": 205,
      "shape": {
        "$count": 65
      },
      "splitNumber": {
        "$count": 51
      },
      "textStyle": {
        "$count": 72,
        "color": {
          "$count": 22
        },
        "fontSize": {
          "$count": 9
        },
        "fontStyle": {
          "$count": 7
        },
        "fontFamily": {
          "$count": 2
        },
        "fontWeight": {
          "$count": 3
        }
      },
      "scale": {
        "$count": 25
      }
    },
    "axisLabel": {
      "formatter": {
        "$count": 50
      },
      "$count": 163,
      "show": {
        "$count": 21
      },
      "rotate": {
        "$count": 18
      },
      "inside": {
        "$count": 12
      },
      "textStyle": {
        "color": {
          "$count": 9
        },
        "fontStyle": {
          "$count": 3
        },
        "fontWeight": {
          "$count": 2
        },
        "fontFamily": {
          "$count": 4
        },
        "fontSize": {
          "$count": 5
        },
        "$count": 26
      },
      "margin": {
        "$count": 13
      }
    },
    "indicator": {
      "$count": 205,
      "name": {
        "$count": 82
      },
      "max": {
        "$count": 58
      },
      "min": {
        "$count": 44
      }
    },
    "splitArea": {
      "$count": 134,
      "show": {
        "$count": 25
      },
      "areaStyle": {
        "$count": 45,
        "color": {
          "$count": 27
        },
        "shadowBlur": {
          "$count": 8
        },
        "shadowColor": {
          "$count": 4
        },
        "shadowOffsetX": {
          "$count": 3
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
      "$count": 128,
      "show": {
        "color": {
          "$count": 14
        },
        "opacity": {
          "$count": 1
        },
        "$count": 24,
        "shadowColor": {
          "$count": 2
        },
        "shadowBlur": {
          "$count": 4
        },
        "width": {
          "$count": 8
        },
        "type": {
          "$count": 11
        },
        "shadowOffsetX": {
          "$count": 1
        }
      }
    },
    "silent": {
      "$count": 45
    }
  },
  "backgroundColor": {
    "$count": 3387
  },
  "angleAxis": {
    "$count": 3233,
    "startAngle": {
      "$count": 77
    },
    "polarIndex": {
      "$count": 84
    },
    "axisLabel": {
      "formatter": {
        "$count": 44
      },
      "$count": 37,
      "textStyle": {
        "$count": 7,
        "color": {
          "$count": 1
        }
      },
      "inside": {
        "$count": 3
      },
      "margin": {
        "$count": 8
      },
      "interval": {
        "$count": 2
      },
      "show": {
        "$count": 3
      }
    },
    "max": {
      "$count": 18
    },
    "min": {
      "$count": 25
    },
    "boundaryGap": {
      "$count": 39
    },
    "splitNumber": {
      "$count": 26
    },
    "interval": {
      "$count": 34
    },
    "clockwise": {
      "$count": 59
    },
    "data": {
      "$count": 35,
      "textStyle": {
        "baseline": {
          "$count": 6
        },
        "align": {
          "$count": 3
        },
        "$count": 8,
        "color": {
          "$count": 5
        },
        "fontStyle": {
          "$count": 1
        },
        "fontWeight": {
          "$count": 1
        },
        "fontFamily": {
          "$count": 1
        }
      },
      "value": {
        "$count": 8
      }
    },
    "type": {
      "$count": 54
    },
    "scale": {
      "$count": 35
    },
    "axisLine": {
      "lineStyle": {
        "type": {
          "$count": 3
        },
        "color": {
          "$count": 7
        },
        "width": {
          "$count": 4
        },
        "$count": 13,
        "opacity": {
          "$count": 1
        },
        "shadowColor": {
          "$count": 2
        },
        "shadowBlur": {
          "$count": 2
        },
        "shadowOffsetX": {
          "$count": 1
        },
        "shadowOffsetY": {
          "$count": 1
        }
      },
      "$count": 37,
      "show": {
        "$count": 5
      }
    },
    "axisTick": {
      "interval": {
        "$count": 7
      },
      "$count": 20,
      "lineStyle": {
        "color": {
          "$count": 1
        },
        "width": {
          "$count": 1
        },
        "type": {
          "$count": 3
        },
        "$count": 5,
        "shadowOffsetX": {
          "$count": 1
        }
      },
      "show": {
        "$count": 6
      },
      "inside": {
        "$count": 3
      },
      "length": {
        "$count": 5
      }
    },
    "splitLine": {
      "$count": 21,
      "lineStyle": {
        "shadowBlur": {
          "$count": 2
        },
        "$count": 11,
        "color": {
          "$count": 4
        },
        "opacity": {
          "$count": 2
        },
        "type": {
          "$count": 3
        }
      },
      "show": {
        "$count": 2
      },
      "interval": {
        "$count": 4
      }
    },
    "splitArea": {
      "$count": 25,
      "areaStyle": {
        "$count": 13,
        "shadowBlur": {
          "$count": 5
        },
        "shadowColor": {
          "$count": 2
        },
        "color": {
          "$count": 7
        },
        "shadowOffsetX": {
          "$count": 2
        },
        "shadowOffsetY": {
          "$count": 2
        },
        "opacity": {
          "$count": 3
        }
      },
      "interval": {
        "$count": 4
      },
      "show": {
        "$count": 3
      }
    },
    "silent": {
      "$count": 9
    }
  },
  "parallelAxis": {
    "$count": 2600,
    "name": {
      "$count": 9
    },
    "type": {
      "$count": 27
    },
    "axisLabel": {
      "textStyle": {
        "$count": 3,
        "color": {
          "$count": 1
        }
      },
      "formatter": {
        "$count": 13
      },
      "$count": 18,
      "interval": {
        "$count": 4
      },
      "show": {
        "$count": 3
      },
      "margin": {
        "$count": 1
      },
      "rotate": {
        "$count": 7
      }
    },
    "boundaryGap": {
      "$count": 11
    },
    "dim": {
      "$count": 80
    },
    "parallelIndex": {
      "$count": 38
    },
    "areaSelectStyle": {
      "width": {
        "$count": 4
      },
      "borderWidth": {
        "$count": 5
      },
      "$count": 33,
      "borderColor": {
        "$count": 3
      },
      "color": {
        "$count": 3
      },
      "opacity": {
        "$count": 2
      }
    },
    "max": {
      "$count": 7
    },
    "nameTextStyle": {
      "$count": 16,
      "fontStyle": {
        "$count": 2
      },
      "fontWeight": {
        "$count": 2
      },
      "fontFamily": {
        "$count": 2
      },
      "color": {
        "$count": 1
      },
      "fontSize": {
        "$count": 1
      }
    },
    "data": {
      "$count": 28,
      "textStyle": {
        "$count": 3,
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
        },
        "baseline": {
          "$count": 1
        }
      },
      "value": {
        "$count": 3
      }
    },
    "interval": {
      "$count": 15
    },
    "axisTick": {
      "$count": 16,
      "show": {
        "$count": 2
      },
      "interval": {
        "$count": 4
      },
      "inside": {
        "$count": 2
      },
      "length": {
        "$count": 2
      },
      "lineStyle": {
        "$count": 2,
        "width": {
          "$count": 1
        }
      }
    },
    "axisLine": {
      "lineStyle": {
        "$count": 9,
        "color": {
          "$count": 6
        },
        "shadowBlur": {
          "$count": 3
        },
        "type": {
          "$count": 2
        },
        "shadowColor": {
          "$count": 2
        },
        "shadowOffsetY": {
          "$count": 1
        },
        "shadowOffsetX": {
          "$count": 1
        },
        "width": {
          "$count": 1
        }
      },
      "$count": 24,
      "show": {
        "$count": 3
      }
    },
    "nameGap": {
      "$count": 10
    },
    "min": {
      "$count": 10
    },
    "splitNumber": {
      "$count": 6
    },
    "nameLocation": {
      "$count": 9
    },
    "inverse": {
      "$count": 5
    },
    "scale": {
      "$count": 3
    },
    "silent": {
      "$count": 1
    }
  },
  "animationDurationUpdate": {
    "$count": 1609
  },
  "animation": {
    "$count": 2532
  },
  "animationDuration": {
    "$count": 1962
  },
  "animationEasing": {
    "$count": 1763
  },
  "animationEasingUpdate": {
    "$count": 1534
  }
};
myChart.hideLoading();
  function convert(source, target, basePath) {
    for (let key in source) {
      let path = basePath ? basePath + '.' + key : key;
      if (!key.match(/^\$/)) {
        target.children = target.children || [];
        const child = {
          name: path
        };
        target.children.push(child);
        convert(source[key], child, path);
      }
    }
    if (!target.children) {
      target.value = source.$count || 1;
    } else {
      target.children.push({
        name: basePath,
        value: source.$count
      });
    }
  }
  const data = {
    children: []
  };
  convert(rawData, data, '');
  myChart.setOption(
    (option = {
      title: {
        text: 'ECharts Options',
        subtext: '2016/04',
        left: 'leafDepth'
      },
      tooltip: {},
      series: [
        {
          name: 'option',
          type: 'treemap',
          visibleMin: 300,
          data: data.children,
          leafDepth: 2,
          levels: [
            {
              itemStyle: {
                borderColor: '#555',
                borderWidth: 4,
                gapWidth: 4
              }
            },
            {
              colorSaturation: [0.3, 0.6],
              itemStyle: {
                borderColorSaturation: 0.7,
                gapWidth: 2,
                borderWidth: 2
              }
            },
            {
              colorSaturation: [0.3, 0.5],
              itemStyle: {
                borderColorSaturation: 0.6,
                gapWidth: 1
              }
            },
            {
              colorSaturation: [0.3, 0.5]
            }
          ]
        }
      ]
    })
  );

```
