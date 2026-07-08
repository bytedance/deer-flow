# treemap-sunburst-transition

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=treemap-sunburst-transition
**Chart Type:** `treemap`

## User Data Requirements

Columns needed: need nested **name+value** or **name+children**

## Data Arrays — Replacement Guide

The code contains **0 data array(s)** to replace:


## External Data Format

This example uses external data. Format from `echarts-package-size.json`:

```json
[
  {
    "name": "action",
    "size": 2307,
    "children": [
      {
        "name": "action/roamHelper.ts",
        "size": 2307,
        "value": 2307
      }
    ],
    "value": 2307
  },
  {
    "name": "animation",
    "size": 44515,
    "children": [
      {
        "name": "animation/basicTrasition.ts",
        "size": 11322,
        "value": 11322
      },
      {
        "name": "animation/morphTransitionHelper.ts",
        "size": 8706,
        "value": 8706
      },
      {
       
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
title: Transition between Treemap and Sunburst
category: treemap
titleCN: 矩形树图和旭日图的动画过渡
difficulty: 4
videoStart: 3000
videoEnd: 9000
*/
var data = {
  "name": "echarts",
  "size": 3835461,
  "children": [
    {
      "name": "action",
      "size": 2307,
      "children": [
        {
          "name": "action/roamHelper.ts",
          "size": 2307,
          "value": 2307
        }
      ],
      "value": 2307
    },
    {
      "name": "animation",
      "size": 44515,
      "children": [
        {
          "name": "animation/basicTrasition.ts",
          "size": 11322,
          "value": 11322
        },
        {
          "name": "animation/morphTransitionHelper.ts",
          "size": 8706,
          "value": 8706
        },
        {
          "name": "animation/universalTransition.ts",
          "size": 24487,
          "value": 24487
        }
      ],
      "value": 44515
    },
    {
      "name": "chart",
      "size": 1059597,
      "children": [
        {
          "name": "chart/bar",
          "size": 90538,
          "children": [
            {
              "name": "chart/bar/BarSeries.ts",
              "size": 4489,
              "value": 4489
            },
            {
              "name": "chart/bar/BarView.ts",
              "size": 41509,
              "value": 41509
            },
            {
              "name": "chart/bar/BaseBarSeries.ts",
              "size": 3754,
              "value": 3754
            },
            {
              "name": "chart/bar/PictorialBarSeries.ts",
              "size": 5194,
              "value": 5194
            },
            {
              "name": "chart/bar/PictorialBarView.ts",
              "size": 31640,
              "value": 31640
            },
            {
              "name": "chart/bar/install.ts",
              "size": 2627,
              "value": 2627
            },
            {
              "name": "chart/bar/installPictorialBar.ts",
              "size": 1325,
              "value": 1325
            }
          ],
          "value": 90538
        },
        {
          "name": "chart/bar.ts",
          "size": 885,
          "value": 885
        },
        {
          "name": "chart/boxplot",
          "size": 24408,
          "children": [
            {
              "name": "chart/boxplot/BoxplotSeries.ts",
              "size": 3891,
              "value": 3891
            },
            {
              "name": "chart/boxplot/BoxplotView.ts",
              "size": 5968,
              "value": 5968
            },
            {
              "name": "chart/boxplot/boxplotLayout.ts",
              "size": 6718,
              "value": 6718
            },
            {
              "name": "chart/boxplot/boxplotTransform.ts",
              "size": 2073,
              "value": 2073
            },
            {
              "name": "chart/boxplot/boxplotVisual.ts",
              "size": 1024,
              "value": 1024
            },
            {
              "name": "chart/boxplot/install.ts",
              "size": 1411,
              "value": 1411
            },
            {
              "name": "chart/boxplot/prepareBoxplotData.ts",
              "size": 3323,
              "value": 3323
            }
          ],
          "value": 24408
        },
        {
          "name": "chart/boxplot.ts",
          "size": 889,
          "value": 889
        },
        {
          "name": "chart/candlestick",
          "size": 31115,
          "children": [
            {
              "name": "chart/candlestick/CandlestickSeries.ts",
              "size": 4548,
              "value": 4548
            },
            {
              "name": "chart/candlestick/CandlestickView.ts",
              "size": 11680,
              "value": 11680
            },
            {
              "name": "chart/candlestick/candlestickLayout.ts",
              "size": 9182,
              "value": 9182
            },
            {
              "name": "chart/candlestick/candlestickVisual.ts",
              "size": 2990,
              "value": 2990
            },
            {
              "name": "chart/candlestick/install.ts",
              "size": 1447,
              "value": 1447
            },
            {
              "name": "chart/candlestick/preprocessor.ts",
              "size": 1268,
              "value": 1268
            }
          ],
          "value": 31115
        },
        {
          "name": "chart/candlestick.ts",
          "size": 891,
          "value": 891
        },
        {
          "name": "chart/custom",
          "size": 87227,
          "children": [
            {
              "name": "chart/custom/CustomSeries.ts",
              "size": 12400,
              "value": 12400
            },
            {
              "name": "chart/custom/CustomView.ts",
              "size": 60468,
              "value": 60468
            },
            {
              "name": "chart/custom/install.ts",
              "size": 1129,
              "value": 1129
            },
            {
              "name": "chart/custom/prepare.ts",
              "size": 13230,
              "value": 13230
            }
          ],
          "value": 87227
        },
        {
          "name": "chart/custom.ts",
          "size": 887,
          "value": 887
        },
        {
          "name": "chart/effectScatter",
          "size": 8799,
          "children": [
            {
              "name": "chart/effectScatter/EffectScatterSeries.ts",
              "size": 4446,
              "value": 4446
            },
            {
              "name": "chart/effectScatter/EffectScatterView.ts",
              "size": 3082,
              "value": 3082
            },
            {
              "name": "chart/effectScatter/install.ts",
              "size": 1271,
              "value": 1271
            }
          ],
          "value": 8799
        },
        {
          "name": "chart/effectScatter.ts",
          "size": 893,
          "value": 893
        },
        {
          "name": "chart/funnel",
          "size": 28181,
          "children": [
            {
              "name": "chart/funnel/FunnelSeries.ts",
              "size": 5960,
              "value": 5960
            },
            {
              "name": "chart/funnel/FunnelView.ts",
              "size": 6781,
              "value": 6781
            },
            {
              "name": "chart/funnel/funnelLayout.ts",
              "size": 14126,
              "value": 14126
            },
            {
              "name": "chart/funnel/install.ts",
              "size": 1314,
              "value": 1314
            }
          ],
          "value": 28181
        },
        {
          "name": "chart/funnel.ts",
          "size": 886,
          "value": 886
        },
        {
          "name": "chart/gauge",
          "size": 37230,
          "children": [
            {
              "name": "chart/gauge/GaugeSeries.ts",
              "size": 7859,
              "value": 7859
            },
            {
              "name": "chart/gauge/GaugeView.ts",
              "size": 26107,
              "value": 26107
            },
            {
              "name": "chart/gauge/PointerPath.ts",
              "size": 2151,
              "value": 2151
            },
            {
              "name": "chart/gauge/install.ts",
              "size": 1113,
              "value": 1113
            }
          ],
          "value": 37230
        },
        {
          "name": "chart/gauge.ts",
          "size": 885,
          "value": 885
        },
        {
          "name": "chart/graph",
          "size": 74973,
          "children": [
            {
              "name": "chart/graph/GraphSeries.ts",
              "size": 14275,
              "value": 14275
            },
            {
              "name": "chart/graph/GraphView.ts",
              "size": 10843,
              "value": 10843
            },
            {
              "name": "chart/graph/adjustEdge.ts",
              "size": 6122,
              "value": 6122
            },
            {
              "name": "chart/graph/categoryFilter.ts",
              "size": 2191,
              "value": 2191
            },
            {
              "name": "chart/graph/categoryVisual.ts",
              "size": 3546,
              "value": 3546
            },
            {
              "name": "chart/graph/circularLayout.ts",
              "size": 1220,
              "value": 1220
            },
            {
              "name": "chart/graph/circularLayoutHelper.ts",
              "size": 5653,
              "value": 5653
            },
            {
              "name": "chart/graph/createView.ts",
              "size": 3700,
              "value": 3700
            },
            {
              "name": "chart/graph/edgeVisual.ts",
              "size": 3507,
              "value": 3507
            },
            {
              "name": "chart/graph/forceHelper.ts",
              "size": 7070,
              "value": 7070
            },
            {
              "name": "chart/graph/forceLayout.ts",
              "size": 7295,
              "value": 7295
            },
            {
              "name": "chart/graph/graphHelper.ts",
              "size": 1616,
              "value": 1616
            },
            {
              "name": "chart/graph/install.ts",
              "size": 3086,
              "value": 3086
            },
            {
              "name": "chart/graph/simpleLayout.ts",
              "size": 2582,
              "value": 2582
            },
            {
              "name": "chart/graph/simpleLayoutHelper.ts",
              "size": 2267,
              "value": 2267
            }
          ],
          "value": 74973
        },
        {
          "name": "chart/graph.ts",
          "size": 886,
          "value": 886
        },
        {
          "name": "chart/heatmap",
          "size": 24819,
          "children": [
            {
              "name": "chart/heatmap/HeatmapLayer.ts",
              "size": 6056,
              "value": 6056
            },
            {
              "name": "chart/heatmap/HeatmapSeries.ts",
              "size": 3602,
              "value": 3602
            },
            {
              "name": "chart/heatmap/HeatmapView.ts",
              "size": 14036,
              "value": 14036
            },
            {
              "name": "chart/heatmap/install.ts",
              "size": 1125,
              "value": 1125
            }
          ],
          "value": 24819
        },
        {
          "name": "chart/heatmap.ts",
          "size": 888,
          "value": 888
        },
        {
          "name": "chart/helper",
          "size": 133086,
          "children": [
            {
              "name": "chart/helper/EffectLine.ts",
              "size": 8279,
              "value": 8279
            },
            {
              "name": "chart/helper/EffectPolyline.ts",
              "size": 3707,
              "value": 3707
            },
            {
              "name": "chart/helper/EffectSymbol.ts",
              "size": 8513,
              "value": 8513
            },
            {
              "name": "chart/helper/LargeLineDraw.ts",
              "size": 8490,
              "value": 8490
            },
            {
              "name": "chart/helper/LargeSymbolDraw.ts",
              "size": 9624,
              "value": 9624
            },
            {
              "name": "chart/helper/Line.ts",
              "size": 18271,
              "value": 18271
            },
            {
              "name": "chart/helper/LineDraw.ts",
              "size": 7187,
              "value": 7187
            },
            {
              "name": "chart/helper/LinePath.ts",
              "size": 2836,
              "value": 2836
            },
            {
              "name": "chart/helper/Polyline.ts",
              "size": 3035,
              "value": 3035
            },
            {
              "name": "chart/helper/Symbol.ts",
              "size": 13637,
              "value": 13637
            },
            {
              "name": "chart/helper/SymbolDraw.ts",
              "size": 10007,
              "value": 10007
            },
            {
              "name": "chart/helper/createClipPathFromCoordSys.ts",
              "size": 4784,
              "value": 4784
            },
            {
              "name": "chart/helper/createGraphFromNodeEdge.ts",
              "size": 3956,
              "value": 3956
            },
            {
              "name": "chart/helper/createListFromArray.ts",
              "size": 5728,
              "value": 5728
            },
            {
              "name": "chart/helper/createListSimply.ts",
              "size": 1701,
              "value": 1701
            },
            {
              "name": "chart/helper/createRenderPlanner.ts",
              "size": 2050,
              "value": 2050
            },
            {
              "name": "chart/helper/enableAriaDecalForTree.ts",
              "size": 1578,
              "value": 1578
            },
            {
              "name": "chart/helper/labelHelper.ts",
              "size": 2193,
              "value": 2193
            },
            {
              "name": "chart/helper/multipleGraphEdgeHelper.ts",
              "size": 7494,
              "value": 7494
            },
            {
              "name": "chart/helper/pieHelper.ts",
              "size": 1510,
              "value": 1510
            },
            {
              "name": "chart/helper/treeHelper.ts",
              "size": 2724,
              "value": 2724
            },
            {
              "name": "chart/helper/whiskerBoxCommon.ts",
              "size": 5782,
              "value": 5782
            }
          ],
          "value": 133086
        },
        {
          "name": "chart/line",
          "size": 78825,
          "children": [
            {
              "name": "chart/line/LineSeries.ts",
              "size": 7339,
              "value": 7339
            },
            {
              "name": "chart/line/LineView.ts",
              "size": 46175,
              "value": 46175
            },
            {
              "name": "chart/line/helper.ts",
              "size": 4127,
              "value": 4127
            },
            {
              "name": "chart/line/install.ts",
              "size": 2049,
              "value": 2049
            },
            {
              "name": "chart/line/lineAnimationDiff.ts",
              "size": 6738,
              "value": 6738
            },
            {
              "name": "chart/line/poly.ts",
              "size": 12397,
              "value": 12397
            }
          ],
          "value": 78825
        },
        {
          "name": "chart/line.ts",
          "size": 884,
          "value": 884
        },
        {
          "name": "chart/lines",
          "size": 28837,
          "children": [
            {
              "name": "chart/lines/LinesSeries.ts",
              "size": 12955,
              "value": 12955
            },
            {
              "name": "chart/lines/LinesView.ts",
              "size": 7716,
              "value": 7716
            },
            {
              "name": "chart/lines/install.ts",
              "size": 1281,
              "value": 1281
            },
            {
              "name": "chart/lines/linesLayout.ts",
              "size": 4123,
              "value": 4123
            },
            {
              "name": "chart/lines/linesVisual.ts",
              "size": 2762,
              "value": 2762
            }
          ],
          "value": 28837
        },
        {
          "name": "chart/lines.ts",
          "size": 886,
          "value": 886
        },
        {
          "name": "chart/map",
          "size": 25765,
          "children": [
            {
              "name": "chart/map/MapSeries.ts",
              "size": 10347,
              "value": 10347
            },
            {
              "name": "chart/map/MapView.ts",
              "size": 7234,
              "value": 7234
            },
            {
              "name": "chart/map/install.ts",
              "size": 1568,
              "value": 1568
            },
            {
              "name": "chart/map/mapDataStatistic.ts",
              "size": 3612,
              "value": 3612
            },
            {
              "name": "chart/map/mapSymbolLayout.ts",
              "size": 3004,
              "value": 3004
            }
          ],
          "value": 25765
        },
        {
          "name": "chart/map.ts",
          "size": 883,
          "value": 883
        },
        {
          "name": "chart/parallel",
          "size": 16811,
          "children": [
            {
              "name": "chart/parallel/ParallelSeries.ts",
              "size": 5234,
              "value": 5234
            },
            {
              "name": "chart/parallel/ParallelView.ts",
              "size": 8006,
              "value": 8006
            },
            {
              "name": "chart/parallel/install.ts",
              "size": 1385,
              "value": 1385
            },
            {
              "name": "chart/parallel/parallelVisual.ts",
              "size": 2186,
              "value": 2186
            }
          ],
          "value": 16811
        },
        {
          "name": "chart/parallel.ts",
          "size": 888,
          "value": 888
        },
        {
          "name": "chart/pictorialBar.ts",
          "size": 895,
          "value": 895
        },
        {
          "name": "chart/pie",
          "size": 44655,
          "children": [
            {
              "name": "chart/pie/PieSeries.ts",
              "size": 9492,
              "value": 9492
            },
            {
              "name": "chart/pie/PieView.ts",
              "size": 10737,
              "value": 10737
            },
            {
              "name": "chart/pie/install.ts",
              "size": 1625,
              "value": 1625
            },
            {
              "name": "chart/pie/labelLayout.ts",
              "size": 16039,
              "value": 16039
            },
            {
              "name": "chart/pie/pieLayout.ts",
              "size": 6762,
              "value": 6762
            }
          ],
          "value": 44655
        },
        {
          "name": "chart/pie.ts",
          "size": 883,
          "value": 883
        },
        {
          "name": "chart/radar",
          "size": 22389,
          "children": [
            {
              "name": "chart/radar/RadarSeries.ts",
              "size": 5383,
              "value": 5383
            },
            {
              "name": "chart/radar/RadarView.ts",
              "size": 10797,
              "value": 10797
            },
            {
              "name": "chart/radar/backwardCompat.ts",
              "size": 1940,
              "value": 1940
            },
            {
              "name": "chart/radar/install.ts",
              "size": 1538,
              "value": 1538
            },
            {
              "name": "chart/radar/radarLayout.ts",
              "size": 2731,
              "value": 2731
            }
          ],
          "value": 22389
        },
        {
          "name": "chart/radar.ts",
          "size": 885,
          "value": 885
        },
        {
          "name": "chart/sankey",
          "size": 44323,
          "children": [
            {
              "name": "chart/sankey/SankeySeries.ts",
              "size": 9638,
              "value": 9638
            },
            {
              "name": "chart/sankey/SankeyView.ts",
              "size": 11909,
              "value": 11909
            },
            {
              "name": "chart/sankey/install.ts",
              "size": 2033,
              "value": 2033
            },
            {
              "name": "chart/sankey/sankeyLayout.ts",
              "size": 18170,
              "value": 18170
            },
            {
              "name": "chart/sankey/sankeyVisual.ts",
              "size": 2573,
              "value": 2573
            }
          ],
          "value": 44323
        },
        {
          "name": "chart/sankey.ts",
          "size": 886,
          "value": 886
        },
        {
          "name": "chart/scatter",
          "size": 10739,
          "children": [
            {
              "name": "chart/scatter/ScatterSeries.ts",
              "size": 4719,
              "value": 4719
            },
            {
              "name": "chart/scatter/ScatterView.ts",
              "size": 4618,
              "value": 4618
            },
            {
              "name": "chart/scatter/install.ts",
              "size": 1402,
              "value": 1402
            }
          ],
          "value": 10739
        },
        {
          "name": "chart/scatter.ts",
          "size": 887,
          "value": 887
        },
        {
          "name": "chart/sunburst",
          "size": 43908,
          "children": [
            {
              "name": "chart/sunburst/SunburstPiece.ts",
              "size": 10202,
              "value": 10202
            },
            {
              "name": "chart/sunburst/SunburstSeries.ts",
              "size": 9448,
              "value": 9448
            },
            {
              "name": "chart/sunburst/SunburstView.ts",
              "size": 8236,
              "value": 8236
            },
            {
              "name": "chart/sunburst/install.ts",
              "size": 1596,
              "value": 1596
            },
            {
              "name": "chart/sunburst/sunburstAction.ts",
              "size": 4014,
              "value": 4014
            },
            {
              "name": "chart/sunburst/sunburstLayout.ts",
              "size": 7908,
              "value": 7908
            },
            {
              "name": "chart/sunburst/sunburstVisual.ts",
              "size": 2504,
              "value": 2504
            }
          ],
          "value": 43908
        },
        {
          "name": "chart/sunburst.ts",
          "size": 888,
          "value": 888
        },
        {
          "name": "chart/themeRiver",
          "size": 23557,
          "children": [
            {
              "name": "chart/themeRiver/ThemeRiverSeries.ts",
              "size": 10023,
              "value": 10023
            },
            {
              "name": "chart/themeRiver/ThemeRiverView.ts",
              "size": 6867,
              "value": 6867
            },
            {
              "name": "chart/themeRiver/install.ts",
              "size": 1355,
              "value": 1355
            },
            {
              "name": "chart/themeRiver/themeRiverLayout.ts",
              "size": 5312,
              "value": 5312
            }
          ],
          "value": 23557
        },
        {
          "name": "chart/themeRiver.ts",
          "size": 890,
          "value": 890
        },
        {
          "name": "chart/tree",
          "size": 58277,
          "children": [
            {
              "name": "chart/tree/TreeSeries.ts",
              "size": 8544,
              "value": 8544
            },
            {
              "name": "chart/tree/TreeView.ts",
              "size": 25453,
              "value": 25453
            },
            {
              "name": "chart/tree/install.ts",
              "size": 1352,
              "value": 1352
            },
            {
              "name": "chart/tree/layoutHelper.ts",
              "size": 11766,
              "value": 11766
            },
            {
              "name": "chart/tree/traversalHelper.ts",
              "size": 2085,
              "value": 2085
            },
            {
              "name": "chart/tree/treeAction.ts",
              "size": 2758,
              "value": 2758
            },
            {
              "name": "chart/tree/treeLayout.ts",
              "size": 4787,
              "value": 4787
            },
            {
              "name": "chart/tree/treeVisual.ts",
              "size": 1532,
              "value": 1532
            }
          ],
          "value": 58277
        },
        {
          "name": "chart/tree.ts",
          "size": 884,
          "value": 884
        },
        {
          "name": "chart/treemap",
          "size": 101619,
          "children": [
            {
              "name": "chart/treemap/Breadcrumb.ts",
              "size": 7862,
              "value": 7862
            },
            {
              "name": "chart/treemap/TreemapSeries.ts",
              "size": 18371,
              "value": 18371
            },
            {
              "name": "chart/treemap/TreemapView.ts",
              "size": 39544,
              "value": 39544
            },
            {
              "name": "chart/treemap/install.ts",
              "size": 1400,
              "value": 1400
            },
            {
              "name": "chart/treemap/treemapAction.ts",
              "size": 2938,
              "value": 2938
            },
            {
              "name": "chart/treemap/treemapLayout.ts",
              "size": 22173,
              "value": 22173
            },
            {
              "name": "chart/treemap/treemapVisual.ts",
              "size": 9331,
              "value": 9331
            }
          ],
          "value": 101619
        },
        {
          "name": "chart/treemap.ts",
          "size": 887,
          "value": 887
        }
      ],
      "value": 1059597
    },
    {
      "name": "component",
      "size": 1100395,
      "children": [
        {
          "name": "component/aria",
          "size": 2687,
          "children": [
            {
              "name": "component/aria/install.ts",
              "size": 1152,
              "value": 1152
            },
            {
              "name": "component/aria/preprocessor.ts",
              "size": 1535,
              "value": 1535
            }
          ],
          "value": 2687
        },
        {
          "name": "component/aria.ts",
          "size": 884,
          "value": 884
        },
        {
          "name": "component/axis",
          "size": 80026,
          "children": [
            {
              "name": "component/axis/AngleAxisView.ts",
              "size": 14332,
              "value": 14332
            },
            {
              "name": "component/axis/AxisBuilder.ts",
              "size": 26066,
              "value": 26066
            },
            {
              "name": "component/axis/AxisView.ts",
              "size": 3960,
              "value": 3960
            },
            {
              "name": "component/axis/CartesianAxisView.ts",
              "size": 8399,
              "value": 8399
            },
            {
              "name": "component/axis/ParallelAxisView.ts",
              "size": 7567,
              "value": 7567
            },
            {
              "name": "component/axis/RadiusAxisView.ts",
              "size": 7861,
              "value": 7861
            },
            {
              "name": "component/axis/SingleAxisView.ts",
              "size": 5187,
              "value": 5187
            },
            {
              "name": "component/axis/axisSplitHelper.ts",
              "size": 4375,
              "value": 4375
            },
            {
              "name": "component/axis/parallelAxisAction.ts",
              "size": 2279,
              "value": 2279
            }
          ],
          "value": 80026
        },
        {
          "name": "component/axisPointer",
          "size": 99148,
          "children": [
            {
              "name": "component/axisPointer/AxisPointer.ts",
              "size": 1491,
              "value": 1491
            },
            {
              "name": "component/axisPointer/AxisPointerModel.ts",
              "size": 4442,
              "value": 4442
            },
            {
              "name": "component/axisPointer/AxisPointerView.ts",
              "size": 2598,
              "value": 2598
            },
            {
              "name": "component/axisPointer/BaseAxisPointer.ts",
              "size": 17229,
              "value": 17229
            },
            {
              "name": "component/axisPointer/CartesianAxisPointer.ts",
              "size": 6283,
              "value": 6283
            },
            {
              "name": "component/axisPointer/PolarAxisPointer.ts",
              "size": 6579,
              "value": 6579
            },
            {
              "name": "component/axisPointer/SingleAxisPointer.ts",
              "size": 5990,
              "value": 5990
            },
            {
              "name": "component/axisPointer/axisTrigger.ts",
              "size": 18648,
              "value": 18648
            },
            {
              "name": "component/axisPointer/findPointFromSeries.ts",
              "size": 3490,
              "value": 3490
            },
            {
              "name": "component/axisPointer/globalListener.ts",
              "size": 5144,
              "value": 5144
            },
            {
              "name": "component/axisPointer/install.ts",
              "size": 3050,
              "value": 3050
            },
            {
              "name": "component/axisPointer/modelHelper.ts",
              "size": 15289,
              "value": 15289
            },
            {
              "name": "component/axisPointer/viewHelper.ts",
              "size": 8915,
              "value": 8915
            }
          ],
          "value": 99148
        },
        {
          "name": "component/axisPointer.ts",
          "size": 891,
          "value": 891
        },
        {
          "name": "component/brush",
          "size": 37924,
          "children": [
            {
              "name": "component/brush/BrushModel.ts",
              "size": 8228,
              "value": 8228
            },
            {
              "name": "component/brush/BrushView.ts",
              "size": 4239,
              "value": 4239
            },
            {
              "name": "component/brush/install.ts",
              "size": 2960,
              "value": 2960
            },
            {
              "name": "component/brush/preprocessor.ts",
              "size": 2767,
              "value": 2767
            },
            {
              "name": "component/brush/selector.ts",
              "size": 6254,
              "value": 6254
            },
            {
              "name": "component/brush/visualEncoding.ts",
              "size": 13476,
              "value": 13476
            }
          ],
          "value": 37924
        },
        {
          "name": "component/brush.ts",
          "size": 885,
          "value": 885
        },
        {
          "name": "component/calendar",
          "size": 17456,
          "children": [
            {
              "name": "component/calendar/CalendarView.ts",
              "size": 16196,
              "value": 16196
            },
            {
              "name": "component/calendar/install.ts",
              "size": 1260,
              "value": 1260
            }
          ],
          "value": 17456
        },
        {
          "name": "component/calendar.ts",
          "size": 888,
          "value": 888
        },
        {
          "name": "component/dataZoom",
          "size": 133546,
          "children": [
            {
              "name": "component/dataZoom/AxisProxy.ts",
              "size": 17411,
              "value": 17411
            },
            {
              "name": "component/dataZoom/DataZoomModel.ts",
              "size": 21669,
              "value": 21669
            },
            {
              "name": "component/dataZoom/DataZoomView.ts",
              "size": 1411,
              "value": 1411
            },
            {
              "name": "component/dataZoom/InsideZoomModel.ts",
              "size": 1923,
              "value": 1923
            },
            {
              "name": "component/dataZoom/InsideZoomView.ts",
              "size": 10023,
              "value": 10023
            },
            {
              "name": "component/dataZoom/SelectZoomModel.ts",
              "size": 1000,
              "value": 1000
            },
            {
              "name": "component/dataZoom/SelectZoomView.ts",
              "size": 994,
              "value": 994
            },
            {
              "name": "component/dataZoom/SliderZoomModel.ts",
              "size": 6001,
              "value": 6001
            },
            {
              "name": "component/dataZoom/SliderZoomView.ts",
              "size": 36931,
              "value": 36931
            },
            {
              "name": "component/dataZoom/dataZoomAction.ts",
              "size": 1553,
              "value": 1553
            },
            {
              "name": "component/dataZoom/dataZoomProcessor.ts",
              "size": 5800,
              "value": 5800
            },
            {
              "name": "component/dataZoom/helper.ts",
              "size": 7323,
              "value": 7323
            },
            {
              "name": "component/dataZoom/history.ts",
              "size": 3585,
              "value": 3585
            },
            {
              "name": "component/dataZoom/install.ts",
              "size": 1242,
              "value": 1242
            },
            {
              "name": "component/dataZoom/installCommon.ts",
              "size": 1422,
              "value": 1422
            },
            {
              "name": "component/dataZoom/installDataZoomInside.ts",
              "size": 1314,
              "value": 1314
            },
            {
              "name": "component/dataZoom/installDataZoomSelect.ts",
              "size": 1214,
              "value": 1214
            },
            {
              "name": "component/dataZoom/installDataZoomSlider.ts",
              "size": 1214,
              "value": 1214
            },
            {
              "name": "component/dataZoom/roams.ts",
              "size": 11516,
              "value": 11516
            }
          ],
          "value": 133546
        },
        {
          "name": "component/dataZoom.ts",
          "size": 889,
          "value": 889
        },
        {
          "name": "component/dataZoomInside.ts",
          "size": 902,
          "value": 902
        },
        {
          "name": "component/dataZoomSelect.ts",
          "size": 992,
          "value": 992
        },
        {
          "name": "component/dataZoomSlider.ts",
          "size": 903,
          "value": 903
        },
        {
          "name": "component/dataset",
          "size": 3390,
          "children": [
            {
              "name": "component/dataset/install.ts",
              "size": 3390,
              "value": 3390
            }
          ],
          "value": 3390
        },
        {
          "name": "component/dataset.ts",
          "size": 887,
          "value": 887
        },
        {
          "name": "component/geo",
          "size": 8403,
          "children": [
            {
              "name": "component/geo/GeoView.ts",
              "size": 3395,
              "value": 3395
            },
            {
              "name": "component/geo/install.ts",
              "size": 5008,
              "value": 5008
            }
          ],
          "value": 8403
        },
        {
          "name": "component/geo.ts",
          "size": 885,
          "value": 885
        },
        {
          "name": "component/graphic",
          "size": 27689,
          "children": [
            {
              "name": "component/graphic/install.ts",
              "size": 27689,
              "value": 27689
            }
          ],
          "value": 27689
        },
        {
          "name": "component/graphic.ts",
          "size": 887,
          "value": 887
        },
        {
          "name": "component/grid",
          "size": 3988,
          "children": [
            {
              "name": "component/grid/install.ts",
              "size": 1119,
              "value": 1119
            },
            {
              "name": "component/grid/installSimple.ts",
              "size": 2869,
              "value": 2869
            }
          ],
          "value": 3988
        },
        {
          "name": "component/grid.ts",
          "size": 885,
          "value": 885
        },
        {
          "name": "component/gridSimple.ts",
          "size": 890,
          "value": 890
        },
        {
          "name": "component/helper",
          "size": 113305,
          "children": [
            {
              "name": "component/helper/BrushController.ts",
              "size": 35862,
              "value": 35862
            },
            {
              "name": "component/helper/BrushTargetManager.ts",
              "size": 19989,
              "value": 19989
            },
            {
              "name": "component/helper/MapDraw.ts",
              "size": 31814,
              "value": 31814
            },
            {
              "name": "component/helper/RoamController.ts",
              "size": 10950,
              "value": 10950
            },
            {
              "name": "component/helper/brushHelper.ts",
              "size": 2232,
              "value": 2232
            },
            {
              "name": "component/helper/cursorHelper.ts",
              "size": 1725,
              "value": 1725
            },
            {
              "name": "component/helper/interactionMutex.ts",
              "size": 1670,
              "value": 1670
            },
            {
              "name": "component/helper/listComponent.ts",
              "size": 2756,
              "value": 2756
            },
            {
              "name": "component/helper/roamHelper.ts",
              "size": 2050,
              "value": 2050
            },
            {
              "name": "component/helper/sliderMove.ts",
              "size": 4257,
              "value": 4257
            }
          ],
          "value": 113305
        },
        {
          "name": "component/legend",
          "size": 75921,
          "children": [
            {
              "name": "component/legend/LegendModel.ts",
              "size": 14508,
              "value": 14508
            },
            {
              "name": "component/legend/LegendView.ts",
              "size": 26173,
              "value": 26173
            },
            {
              "name": "component/legend/ScrollableLegendModel.ts",
              "size": 3847,
              "value": 3847
            },
            {
              "name": "component/legend/ScrollableLegendView.ts",
              "size": 20132,
              "value": 20132
            },
            {
              "name": "component/legend/install.ts",
              "size": 1135,
              "value": 1135
            },
            {
              "name": "component/legend/installLegendPlain.ts",
              "size": 1434,
              "value": 1434
            },
            {
              "name": "component/legend/installLegendScroll.ts",
              "size": 1393,
              "value": 1393
            },
            {
              "name": "component/legend/legendAction.ts",
              "size": 4035,
              "value": 4035
            },
            {
              "name": "component/legend/legendFilter.ts",
              "size": 1599,
              "value": 1599
            },
            {
              "name": "component/legend/scrollableLegendAction.ts",
              "size": 1665,
              "value": 1665
            }
          ],
          "value": 75921
        },
        {
          "name": "component/legend.ts",
          "size": 947,
          "value": 947
        },
        {
          "name": "component/legendPlain.ts",
          "size": 958,
          "value": 958
        },
        {
          "name": "component/legendScroll.ts",
          "size": 939,
          "value": 939
        },
        {
          "name": "component/markArea.ts",
          "size": 894,
          "value": 894
        },
        {
          "name": "component/markLine.ts",
          "size": 894,
          "value": 894
        },
        {
          "name": "component/markPoint.ts",
          "size": 937,
          "value": 937
        },
        {
          "name": "component/marker",
          "size": 74821,
          "children": [
            {
              "name": "component/marker/MarkAreaModel.ts",
              "size": 3082,
              "value": 3082
            },
            {
              "name": "component/marker/MarkAreaView.ts",
              "size": 15177,
              "value": 15177
            },
            {
              "name": "component/marker/MarkLineModel.ts",
              "size": 3865,
              "value": 3865
            },
            {
              "name": "component/marker/MarkLineView.ts",
              "size": 17059,
              "value": 17059
            },
            {
              "name": "component/marker/MarkPointModel.ts",
              "size": 2690,
              "value": 2690
            },
            {
              "name": "component/marker/MarkPointView.ts",
              "size": 7311,
              "value": 7311
            },
            {
              "name": "component/marker/MarkerModel.ts",
              "size": 7620,
              "value": 7620
            },
            {
              "name": "component/marker/MarkerView.ts",
              "size": 3120,
              "value": 3120
            },
            {
              "name": "component/marker/checkMarkerInSeries.ts",
              "size": 1501,
              "value": 1501
            },
            {
              "name": "component/marker/installMarkArea.ts",
              "size": 1414,
              "value": 1414
            },
            {
              "name": "component/marker/installMarkLine.ts",
              "size": 1413,
              "value": 1413
            },
            {
              "name": "component/marker/installMarkPoint.ts",
              "size": 1423,
              "value": 1423
            },
            {
              "name": "component/marker/markerHelper.ts",
              "size": 9146,
              "value": 9146
            }
          ],
          "value": 74821
        },
        {
          "name": "component/parallel",
          "size": 7529,
          "children": [
            {
              "name": "component/parallel/ParallelView.ts",
              "size": 5251,
              "value": 5251
            },
            {
              "name": "component/parallel/install.ts",
              "size": 2278,
              "value": 2278
            }
          ],
          "value": 7529
        },
        {
          "name": "component/parallel.ts",
          "size": 889,
          "value": 889
        },
        {
          "name": "component/polar",
          "size": 2653,
          "children": [
            {
              "name": "component/polar/install.ts",
              "size": 2653,
              "value": 2653
            }
          ],
          "value": 2653
        },
        {
          "name": "component/polar.ts",
          "size": 885,
          "value": 885
        },
        {
          "name": "component/radar",
          "size": 9763,
          "children": [
            {
              "name": "component/radar/RadarView.ts",
              "size": 8014,
              "value": 8014
            },
            {
              "name": "component/radar/install.ts",
              "size": 1749,
              "value": 1749
            }
          ],
          "value": 9763
        },
        {
          "name": "component/radar.ts",
          "size": 886,
          "value": 886
        },
        {
          "name": "component/singleAxis",
          "size": 1939,
          "children": [
            {
              "name": "component/singleAxis/install.ts",
              "size": 1939,
              "value": 1939
            }
          ],
          "value": 1939
        },
        {
          "name": "component/singleAxis.ts",
          "size": 890,
          "value": 890
        },
        {
          "name": "component/timeline",
          "size": 54918,
          "children": [
            {
              "name": "component/timeline/SliderTimelineModel.ts",
              "size": 5956,
              "value": 5956
            },
            {
              "name": "component/timeline/SliderTimelineView.ts",
              "size": 30481,
              "value": 30481
            },
            {
              "name": "component/timeline/TimelineAxis.ts",
              "size": 1696,
              "value": 1696
            },
            {
              "name": "component/timeline/TimelineModel.ts",
              "size": 8618,
              "value": 8618
            },
            {
              "name": "component/timeline/TimelineView.ts",
              "size": 978,
              "value": 978
            },
            {
              "name": "component/timeline/install.ts",
              "size": 1478,
              "value": 1478
            },
            {
              "name": "component/timeline/preprocessor.ts",
              "size": 3026,
              "value": 3026
            },
            {
              "name": "component/timeline/timelineAction.ts",
              "size": 2685,
              "value": 2685
            }
          ],
          "value": 54918
        },
        {
          "name": "component/timeline.ts",
          "size": 925,
          "value": 925
        },
        {
          "name": "component/title",
          "size": 8511,
          "children": [
            {
              "name": "component/title/install.ts",
              "size": 8511,
              "value": 8511
            }
          ],
          "value": 8511
        },
        {
          "name": "component/title.ts",
          "size": 885,
          "value": 885
        },
        {
          "name": "component/toolbox",
          "size": 77259,
          "children": [
            {
              "name": "component/toolbox/ToolboxModel.ts",
              "size": 3544,
              "value": 3544
            },
            {
              "name": "component/toolbox/ToolboxView.ts",
              "size": 14463,
              "value": 14463
            },
            {
              "name": "component/toolbox/feature",
              "size": 53725,
              "children": [
                {
                  "name": "component/toolbox/feature/Brush.ts",
                  "size": 6558,
                  "value": 6558
                },
                {
                  "name": "component/toolbox/feature/DataView.ts",
                  "size": 17627,
                  "value": 17627
                },
                {
                  "name": "component/toolbox/feature/DataZoom.ts",
                  "size": 12177,
                  "value": 12177
                },
                {
                  "name": "component/toolbox/feature/MagicType.ts",
                  "size": 9202,
                  "value": 9202
                },
                {
                  "name": "component/toolbox/feature/Restore.ts",
                  "size": 2184,
                  "value": 2184
                },
                {
                  "name": "component/toolbox/feature/SaveAsImage.ts",
                  "size": 5977,
                  "value": 5977
                }
              ],
              "value": 53725
            },
            {
              "name": "component/toolbox/featureManager.ts",
              "size": 3745,
              "value": 3745
            },
            {
              "name": "component/toolbox/install.ts",
              "size": 1782,
              "value": 1782
            }
          ],
          "value": 77259
        },
        {
          "name": "component/toolbox.ts",
          "size": 887,
          "value": 887
        },
        {
          "name": "component/tooltip",
          "size": 103659,
          "children": [
            {
              "name": "component/tooltip/TooltipHTMLContent.ts",
              "size": 17954,
              "value": 17954
            },
            {
              "name": "component/tooltip/TooltipModel.ts",
              "size": 5171,
              "value": 5171
            },
            {
              "name": "component/tooltip/TooltipRichContent.ts",
              "size": 7836,
              "value": 7836
            },
            {
              "name": "component/tooltip/TooltipView.ts",
              "size": 41776,
              "value": 41776
            },
            {
              "name": "component/tooltip/helper.ts",
              "size": 2525,
              "value": 2525
            },
            {
              "name": "component/tooltip/install.ts",
              "size": 1825,
              "value": 1825
            },
            {
              "name": "component/tooltip/seriesFormatTooltip.ts",
              "size": 6035,
              "value": 6035
            },
            {
              "name": "component/tooltip/tooltipMarkup.ts",
              "size": 20537,
              "value": 20537
            }
          ],
          "value": 103659
        },
        {
          "name": "component/tooltip.ts",
          "size": 887,
          "value": 887
        },
        {
          "name": "component/transform",
          "size": 11994,
          "children": [
            {
              "name": "component/transform/filterTransform.ts",
              "size": 3787,
              "value": 3787
            },
            {
              "name": "component/transform/install.ts",
              "size": 1129,
              "value": 1129
            },
            {
              "name": "component/transform/sortTransform.ts",
              "size": 7078,
              "value": 7078
            }
          ],
          "value": 11994
        },
        {
          "name": "component/transform.ts",
          "size": 889,
          "value": 889
        },
        {
          "name": "component/visualMap",
          "size": 115902,
          "children": [
            {
              "name": "component/visualMap/ContinuousModel.ts",
              "size": 10417,
              "value": 10417
            },
            {
              "name": "component/visualMap/ContinuousView.ts",
              "size": 33304,
              "value": 33304
            },
            {
              "name": "component/visualMap/PiecewiseModel.ts",
              "size": 20174,
              "value": 20174
            },
            {
              "name": "component/visualMap/PiecewiseView.ts",
              "size": 8244,
              "value": 8244
            },
            {
              "name": "component/visualMap/VisualMapModel.ts",
              "size": 19339,
              "value": 19339
            },
            {
              "name": "component/visualMap/VisualMapView.ts",
              "size": 5532,
              "value": 5532
            },
            {
              "name": "component/visualMap/helper.ts",
              "size": 3204,
              "value": 3204
            },
            {
              "name": "component/visualMap/install.ts",
              "size": 1268,
              "value": 1268
            },
            {
              "name": "component/visualMap/installCommon.ts",
              "size": 2407,
              "value": 2407
            },
            {
              "name": "component/visualMap/installVisualMapContinuous.ts",
              "size": 1213,
              "value": 1213
            },
            {
              "name": "component/visualMap/installVisualMapPiecewise.ts",
              "size": 1207,
              "value": 1207
            },
            {
              "name": "component/visualMap/preprocessor.ts",
              "size": 1969,
              "value": 1969
            },
            {
              "name": "component/visualMap/typeDefaulter.ts",
              "size": 1645,
              "value": 1645
            },
            {
              "name": "component/visualMap/visualEncoding.ts",
              "size": 4633,
              "value": 4633
            },
            {
              "name": "component/visualMap/visualMapAction.ts",
              "size": 1346,
              "value": 1346
            }
          ],
          "value": 115902
        },
        {
          "name": "component/visualMap.ts",
          "size": 889,
          "value": 889
        },
        {
          "name": "component/visualMapContinuous.ts",
          "size": 908,
          "value": 908
        },
        {
          "name": "component/visualMapPiecewise.ts",
          "size": 907,
          "value": 907
        }
      ],
      "value": 1100395
    },
    {
      "name": "coord",
      "size": 347267,
      "children": [
        {
          "name": "coord/Axis.ts",
          "size": 10739,
          "value": 10739
        },
        {
          "name": "coord/AxisBaseModel.ts",
          "size": 1315,
          "value": 1315
        },
        {
          "name": "coord/CoordinateSystem.ts",
          "size": 5980,
          "value": 5980
        },
        {
          "name": "coord/View.ts",
          "size": 10106,
          "value": 10106
        },
        {
          "name": "coord/axisCommonTypes.ts",
          "size": 7385,
          "value": 7385
        },
        {
          "name": "coord/axisDefault.ts",
          "size": 4901,
          "value": 4901
        },
        {
          "name": "coord/axisHelper.ts",
          "size": 15047,
          "value": 15047
        },
        {
          "name": "coord/axisModelCommonMixin.ts",
          "size": 1479,
          "value": 1479
        },
        {
          "name": "coord/axisModelCreator.ts",
          "size": 4611,
          "value": 4611
        },
        {
          "name": "coord/axisTickLabelBuilder.ts",
          "size": 15664,
          "value": 15664
        },
        {
          "name": "coord/calendar",
          "size": 25306,
          "children": [
            {
              "name": "coord/calendar/Calendar.ts",
              "size": 16219,
              "value": 16219
            },
            {
              "name": "coord/calendar/CalendarModel.ts",
              "size": 7389,
              "value": 7389
            },
            {
              "name": "coord/calendar/prepareCustom.ts",
              "size": 1698,
              "value": 1698
            }
          ],
          "value": 25306
        },
        {
          "name": "coord/cartesian",
          "size": 55677,
          "children": [
            {
              "name": "coord/cartesian/Axis2D.ts",
              "size": 3598,
              "value": 3598
            },
            {
              "name": "coord/cartesian/AxisModel.ts",
              "size": 2365,
              "value": 2365
            },
            {
              "name": "coord/cartesian/Cartesian.ts",
              "size": 2900,
              "value": 2900
            },
            {
              "name": "coord/cartesian/Cartesian2D.ts",
              "size": 6469,
              "value": 6469
            },
            {
              "name": "coord/cartesian/Grid.ts",
              "size": 20952,
              "value": 20952
            },
            {
              "name": "coord/cartesian/GridModel.ts",
              "size": 2093,
              "value": 2093
            },
            {
              "name": "coord/cartesian/cartesianAxisHelper.ts",
              "size": 4715,
              "value": 4715
            },
            {
              "name": "coord/cartesian/defaultAxisExtentFromData.ts",
              "size": 10529,
              "value": 10529
            },
            {
              "name": "coord/cartesian/prepareCustom.ts",
              "size": 2056,
              "value": 2056
            }
          ],
          "value": 55677
        },
        {
          "name": "coord/geo",
          "size": 74301,
          "children": [
            {
              "name": "coord/geo/Geo.ts",
              "size": 6598,
              "value": 6598
            },
            {
              "name": "coord/geo/GeoJSONResource.ts",
              "size": 5590,
              "value": 5590
            },
            {
              "name": "coord/geo/GeoModel.ts",
              "size": 8762,
              "value": 8762
            },
            {
              "name": "coord/geo/GeoSVGResource.ts",
              "size": 14611,
              "value": 14611
            },
            {
              "name": "coord/geo/Region.ts",
              "size": 7708,
              "value": 7708
            },
            {
              "name": "coord/geo/fix",
              "size": 7069,
              "children": [
                {
                  "name": "coord/geo/fix/diaoyuIsland.ts",
                  "size": 1510,
                  "value": 1510
                },
                {
                  "name": "coord/geo/fix/geoCoord.ts",
                  "size": 1371,
                  "value": 1371
                },
                {
                  "name": "coord/geo/fix/nanhai.ts",
                  "size": 2706,
                  "value": 2706
                },
                {
                  "name": "coord/geo/fix/textCoord.ts",
                  "size": 1482,
                  "value": 1482
                }
              ],
              "value": 7069
            },
            {
              "name": "coord/geo/geoCreator.ts",
              "size": 8364,
              "value": 8364
            },
            {
              "name": "coord/geo/geoSourceManager.ts",
              "size": 4532,
              "value": 4532
            },
            {
              "name": "coord/geo/geoTypes.ts",
              "size": 4145,
              "value": 4145
            },
            {
              "name": "coord/geo/parseGeoJson.ts",
              "size": 4812,
              "value": 4812
            },
            {
              "name": "coord/geo/prepareCustom.ts",
              "size": 2110,
              "value": 2110
            }
          ],
          "value": 74301
        },
        {
          "name": "coord/parallel",
          "size": 36731,
          "children": [
            {
              "name": "coord/parallel/AxisModel.ts",
              "size": 4949,
              "value": 4949
            },
            {
              "name": "coord/parallel/Parallel.ts",
              "size": 19683,
              "value": 19683
            },
            {
              "name": "coord/parallel/ParallelAxis.ts",
              "size": 1622,
              "value": 1622
            },
            {
              "name": "coord/parallel/ParallelModel.ts",
              "size": 5725,
              "value": 5725
            },
            {
              "name": "coord/parallel/parallelCreator.ts",
              "size": 2335,
              "value": 2335
            },
            {
              "name": "coord/parallel/parallelPreprocessor.ts",
              "size": 2417,
              "value": 2417
            }
          ],
          "value": 36731
        },
        {
          "name": "coord/polar",
          "size": 27609,
          "children": [
            {
              "name": "coord/polar/AngleAxis.ts",
              "size": 4232,
              "value": 4232
            },
            {
              "name": "coord/polar/AxisModel.ts",
              "size": 2777,
              "value": 2777
            },
            {
              "name": "coord/polar/Polar.ts",
              "size": 7817,
              "value": 7817
            },
            {
              "name": "coord/polar/PolarModel.ts",
              "size": 2057,
              "value": 2057
            },
            {
              "name": "coord/polar/RadiusAxis.ts",
              "size": 1539,
              "value": 1539
            },
            {
              "name": "coord/polar/polarCreator.ts",
              "size": 6577,
              "value": 6577
            },
            {
              "name": "coord/polar/prepareCustom.ts",
              "size": 2610,
              "value": 2610
            }
          ],
          "value": 27609
        },
        {
          "name": "coord/radar",
          "size": 18756,
          "children": [
            {
              "name": "coord/radar/IndicatorAxis.ts",
              "size": 1335,
              "value": 1335
            },
            {
              "name": "coord/radar/Radar.ts",
              "size": 10466,
              "value": 10466
            },
            {
              "name": "coord/radar/RadarModel.ts",
              "size": 6955,
              "value": 6955
            }
          ],
          "value": 18756
        },
        {
          "name": "coord/scaleRawExtentInfo.ts",
          "size": 11853,
          "value": 11853
        },
        {
          "name": "coord/single",
          "size": 19807,
          "children": [
            {
              "name": "coord/single/AxisModel.ts",
              "size": 3039,
              "value": 3039
            },
            {
              "name": "coord/single/Single.ts",
              "size": 7563,
              "value": 7563
            },
            {
              "name": "coord/single/SingleAxis.ts",
              "size": 2246,
              "value": 2246
            },
            {
              "name": "coord/single/prepareCustom.ts",
              "size": 1875,
              "value": 1875
            },
            {
              "name": "coord/single/singleAxisHelper.ts",
              "size": 2801,
              "value": 2801
            },
            {
              "name": "coord/single/singleCreator.ts",
              "size": 2283,
              "value": 2283
            }
          ],
          "value": 19807
        }
      ],
      "value": 347267
    },
    {
      "name": "core",
      "size": 158407,
      "children": [
        {
          "name": "core/CoordinateSystem.ts",
          "size": 2238,
          "value": 2238
        },
        {
          "name": "core/ExtensionAPI.ts",
          "size": 2758,
          "value": 2758
        },
        {
          "name": "core/Scheduler.ts",
          "size": 26263,
          "value": 26263
        },
        {
          "name": "core/echarts.ts",
          "size": 105836,
          "value": 105836
        },
        {
          "name": "core/lifecycle.ts",
          "size": 2905,
          "value": 2905
        },
        {
          "name": "core/locale.ts",
          "size": 2757,
          "value": 2757
        },
        {
          "name": "core/task.ts",
          "size": 15650,
          "value": 15650
        }
      ],
      "value": 158407
    },
    {
      "name": "data",
      "size": 257880,
      "children": [
        {
          "name": "data/DataDiffer.ts",
          "size": 11383,
          "value": 11383
        },
        {
          "name": "data/DataDimensionInfo.ts",
          "size": 3819,
          "value": 3819
        },
        {
          "name": "data/Graph.ts",
          "size": 13419,
          "value": 13419
        },
        {
          "name": "data/List.ts",
          "size": 80255,
          "value": 80255
        },
        {
          "name": "data/OrdinalMeta.ts",
          "size": 4280,
          "value": 4280
        },
        {
          "name": "data/Source.ts",
          "size": 17104,
          "value": 17104
        },
        {
          "name": "data/Tree.ts",
          "size": 13459,
          "value": 13459
        },
        {
          "name": "data/helper",
          "size": 114161,
          "children": [
            {
              "name": "data/helper/completeDimensions.ts",
              "size": 13826,
              "value": 13826
            },
            {
              "name": "data/helper/createDimensions.ts",
              "size": 3109,
              "value": 3109
            },
            {
              "name": "data/helper/dataProvider.ts",
              "size": 17686,
              "value": 17686
            },
            {
              "name": "data/helper/dataStackHelper.ts",
              "size": 6541,
              "value": 6541
            },
            {
              "name": "data/helper/dataValueHelper.ts",
              "size": 9894,
              "value": 9894
            },
            {
              "name": "data/helper/dimensionHelper.ts",
              "size": 6249,
              "value": 6249
            },
            {
              "name": "data/helper/linkList.ts",
              "size": 5908,
              "value": 5908
            },
            {
              "name": "data/helper/sourceHelper.ts",
              "size": 16203,
              "value": 16203
            },
            {
              "name": "data/helper/sourceManager.ts",
              "size": 14546,
              "value": 14546
            },
            {
              "name": "data/helper/transform.ts",
              "size": 20199,
              "value": 20199
            }
          ],
          "value": 114161
        }
      ],
      "value": 257880
    },
    {
      "name": "echarts.all.ts",
      "size": 7676,
      "value": 7676
    },
    {
      "name": "echarts.blank.ts",
      "size": 818,
      "value": 818
    },
    {
      "name": "echarts.common.ts",
      "size": 2624,
      "value": 2624
    },
    {
      "name": "echarts.simple.ts",
      "size": 1481,
      "value": 1481
    },
    {
      "name": "echarts.ts",
      "size": 1727,
      "value": 1727
    },
    {
      "name": "export",
      "size": 43462,
      "children": [
        {
          "name": "export/all.ts",
          "size": 905,
          "value": 905
        },
        {
          "name": "export/api",
          "size": 9766,
          "children": [
            {
              "name": "export/api/format.ts",
              "size": 1004,
              "value": 1004
            },
            {
              "name": "export/api/graphic.ts",
              "size": 1287,
              "value": 1287
            },
            {
              "name": "export/api/helper.ts",
              "size": 4467,
              "value": 4467
            },
            {
              "name": "export/api/number.ts",
              "size": 1147,
              "value": 1147
            },
            {
              "name": "export/api/time.ts",
              "size": 886,
              "value": 886
            },
            {
              "name": "export/api/util.ts",
              "size": 975,
              "value": 975
            }
          ],
          "value": 9766
        },
        {
          "name": "export/api.ts",
          "size": 3749,
          "value": 3749
        },
        {
          "name": "export/charts.ts",
          "size": 4745,
          "value": 4745
        },
        {
          "name": "export/components.ts",
          "size": 3847,
          "value": 3847
        },
        {
          "name": "export/core.ts",
          "size": 4759,
          "value": 4759
        },
        {
          "name": "export/features.ts",
          "size": 1022,
          "value": 1022
        },
        {
          "name": "export/option.ts",
          "size": 13730,
          "value": 13730
        },
        {
          "name": "export/renderers.ts",
          "size": 939,
          "value": 939
        }
      ],
      "value": 43462
    },
    {
      "name": "extension.ts",
      "size": 3976,
      "value": 3976
    },
    {
      "name": "global.d.ts",
      "size": 824,
      "value": 824
    },
    {
      "name": "i18n",
      "size": 40367,
      "children": [
        {
          "name": "i18n/langCS.ts",
          "size": 4517,
          "value": 4517
        },
        {
          "name": "i18n/langDE.ts",
          "size": 4549,
          "value": 4549
        },
        {
          "name": "i18n/langEN.ts",
          "size": 4381,
          "value": 4381
        },
        {
          "name": "i18n/langES.ts",
          "size": 2543,
          "value": 2543
        },
        {
          "name": "i18n/langFI.ts",
          "size": 2603,
          "value": 2603
        },
        {
          "name": "i18n/langFR.ts",
          "size": 4556,
          "value": 4556
        },
        {
          "name": "i18n/langJA.ts",
          "size": 4846,
          "value": 4846
        },
        {
          "name": "i18n/langSI.ts",
          "size": 4565,
          "value": 4565
        },
        {
          "name": "i18n/langTH.ts",
          "size": 3388,
          "value": 3388
        },
        {
          "name": "i18n/langZH.ts",
          "size": 4419,
          "value": 4419
        }
      ],
      "value": 40367
    },
    {
      "name": "label",
      "size": 80551,
      "children": [
        {
          "name": "label/LabelManager.ts",
          "size": 20409,
          "value": 20409
        },
        {
          "name": "label/installLabelLayout.ts",
          "size": 1185,
          "value": 1185
        },
        {
          "name": "label/labelGuideHelper.ts",
          "size": 21067,
          "value": 21067
        },
        {
          "name": "label/labelLayoutHelper.ts",
          "size": 11492,
          "value": 11492
        },
        {
          "name": "label/labelStyle.ts",
          "size": 26398,
          "value": 26398
        }
      ],
      "value": 80551
    },
    {
      "name": "layout",
      "size": 38780,
      "children": [
        {
          "name": "layout/barGrid.ts",
          "size": 23261,
          "value": 23261
        },
        {
          "name": "layout/barPolar.ts",
          "size": 11394,
          "value": 11394
        },
        {
          "name": "layout/points.ts",
          "size": 4125,
          "value": 4125
        }
      ],
      "value": 38780
    },
    {
      "name": "legacy",
      "size": 6326,
      "children": [
        {
          "name": "legacy/dataSelectAction.ts",
          "size": 4747,
          "value": 4747
        },
        {
          "name": "legacy/getTextRect.ts",
          "size": 1579,
          "value": 1579
        }
      ],
      "value": 6326
    },
    {
      "name": "loading",
      "size": 4935,
      "children": [
        {
          "name": "loading/default.ts",
          "size": 4935,
          "value": 4935
        }
      ],
      "value": 4935
    },
    {
      "name": "model",
      "size": 140931,
      "children": [
        {
          "name": "model/Component.ts",
          "size": 11309,
          "value": 11309
        },
        {
          "name": "model/Global.ts",
          "size": 38114,
          "value": 38114
        },
        {
          "name": "model/Model.ts",
          "size": 9975,
          "value": 9975
        },
        {
          "name": "model/OptionManager.ts",
          "size": 18599,
          "value": 18599
        },
        {
          "name": "model/Series.ts",
          "size": 24069,
          "value": 24069
        },
        {
          "name": "model/globalDefault.ts",
          "size": 4656,
          "value": 4656
        },
        {
          "name": "model/internalComponentCreator.ts",
          "size": 3007,
          "value": 3007
        },
        {
          "name": "model/mixin",
          "size": 23864,
          "children": [
            {
              "name": "model/mixin/areaStyle.ts",
              "size": 1770,
              "value": 1770
            },
            {
              "name": "model/mixin/dataFormat.ts",
              "size": 8562,
              "value": 8562
            },
            {
              "name": "model/mixin/itemStyle.ts",
              "size": 2193,
              "value": 2193
            },
            {
              "name": "model/mixin/lineStyle.ts",
              "size": 2023,
              "value": 2023
            },
            {
              "name": "model/mixin/makeStyleMapper.ts",
              "size": 2035,
              "value": 2035
            },
            {
              "name": "model/mixin/palette.ts",
              "size": 4309,
              "value": 4309
            },
            {
              "name": "model/mixin/textStyle.ts",
              "size": 2972,
              "value": 2972
            }
          ],
          "value": 23864
        },
        {
          "name": "model/referHelper.ts",
          "size": 7338,
          "value": 7338
        }
      ],
      "value": 140931
    },
    {
      "name": "preprocessor",
      "size": 21470,
      "children": [
        {
          "name": "preprocessor/backwardCompat.ts",
          "size": 9187,
          "value": 9187
        },
        {
          "name": "preprocessor/helper",
          "size": 12283,
          "children": [
            {
              "name": "preprocessor/helper/compatStyle.ts",
              "size": 12283,
              "value": 12283
            }
          ],
          "value": 12283
        }
      ],
      "value": 21470
    },
    {
      "name": "processor",
      "size": 13789,
      "children": [
        {
          "name": "processor/dataFilter.ts",
          "size": 1742,
          "value": 1742
        },
        {
          "name": "processor/dataSample.ts",
          "size": 4292,
          "value": 4292
        },
        {
          "name": "processor/dataStack.ts",
          "size": 6276,
          "value": 6276
        },
        {
          "name": "processor/negativeDataFilter.ts",
          "size": 1479,
          "value": 1479
        }
      ],
      "value": 13789
    },
    {
      "name": "renderer",
      "size": 2072,
      "children": [
        {
          "name": "renderer/installCanvasRenderer.ts",
          "size": 1042,
          "value": 1042
        },
        {
          "name": "renderer/installSVGRenderer.ts",
          "size": 1030,
          "value": 1030
        }
      ],
      "value": 2072
    },
    {
      "name": "scale",
      "size": 56173,
      "children": [
        {
          "name": "scale/Interval.ts",
          "size": 9480,
          "value": 9480
        },
        {
          "name": "scale/Log.ts",
          "size": 6383,
          "value": 6383
        },
        {
          "name": "scale/Ordinal.ts",
          "size": 9362,
          "value": 9362
        },
        {
          "name": "scale/Scale.ts",
          "size": 5235,
          "value": 5235
        },
        {
          "name": "scale/Time.ts",
          "size": 22179,
          "value": 22179
        },
        {
          "name": "scale/helper.ts",
          "size": 3534,
          "value": 3534
        }
      ],
      "value": 56173
    },
    {
      "name": "theme",
      "size": 6143,
      "children": [
        {
          "name": "theme/dark.ts",
          "size": 4867,
          "value": 4867
        },
        {
          "name": "theme/light.ts",
          "size": 1276,
          "value": 1276
        }
      ],
      "value": 6143
    },
    {
      "name": "util",
      "size": 306511,
      "children": [
        {
          "name": "util/ECEventProcessor.ts",
          "size": 5900,
          "value": 5900
        },
        {
          "name": "util/KDTree.ts",
          "size": 8723,
          "value": 8723
        },
        {
          "name": "util/animation.ts",
          "size": 3488,
          "value": 3488
        },
        {
          "name": "util/clazz.ts",
          "size": 12608,
          "value": 12608
        },
        {
          "name": "util/component.ts",
          "size": 8501,
          "value": 8501
        },
        {
          "name": "util/conditionalExpression.ts",
          "size": 14702,
          "value": 14702
        },
        {
          "name": "util/decal.ts",
          "size": 14753,
          "value": 14753
        },
        {
          "name": "util/event.ts",
          "size": 1223,
          "value": 1223
        },
        {
          "name": "util/format.ts",
          "size": 10989,
          "value": 10989
        },
        {
          "name": "util/graphic.ts",
          "size": 19902,
          "value": 19902
        },
        {
          "name": "util/innerStore.ts",
          "size": 1939,
          "value": 1939
        },
        {
          "name": "util/layout.ts",
          "size": 17818,
          "value": 17818
        },
        {
          "name": "util/log.ts",
          "size": 4417,
          "value": 4417
        },
        {
          "name": "util/model.ts",
          "size": 37198,
          "value": 37198
        },
        {
          "name": "util/number.ts",
          "size": 19583,
          "value": 19583
        },
        {
          "name": "util/quickSelect.ts",
          "size": 2920,
          "value": 2920
        },
        {
          "name": "util/shape",
          "size": 2905,
          "children": [
            {
              "name": "util/shape/sausage.ts",
              "size": 2905,
              "value": 2905
            }
          ],
          "value": 2905
        },
        {
          "name": "util/states.ts",
          "size": 29540,
          "value": 29540
        },
        {
          "name": "util/styleCompat.ts",
          "size": 11390,
          "value": 11390
        },
        {
          "name": "util/symbol.ts",
          "size": 10302,
          "value": 10302
        },
        {
          "name": "util/throttle.ts",
          "size": 5384,
          "value": 5384
        },
        {
          "name": "util/time.ts",
          "size": 11356,
          "value": 11356
        },
        {
          "name": "util/types.ts",
          "size": 49661,
          "value": 49661
        },
        {
          "name": "util/vendor.ts",
          "size": 1309,
          "value": 1309
        }
      ],
      "value": 306511
    },
    {
      "name": "view",
      "size": 13542,
      "children": [
        {
          "name": "view/Chart.ts",
          "size": 9239,
          "value": 9239
        },
        {
          "name": "view/Component.ts",
          "size": 4303,
          "value": 4303
        }
      ],
      "value": 13542
    },
    {
      "name": "visual",
      "size": 70915,
      "children": [
        {
          "name": "visual/LegendVisualProvider.ts",
          "size": 2598,
          "value": 2598
        },
        {
          "name": "visual/VisualMapping.ts",
          "size": 24898,
          "value": 24898
        },
        {
          "name": "visual/aria.ts",
          "size": 10732,
          "value": 10732
        },
        {
          "name": "visual/commonVisualTypes.ts",
          "size": 1264,
          "value": 1264
        },
        {
          "name": "visual/decal.ts",
          "size": 1774,
          "value": 1774
        },
        {
          "name": "visual/helper.ts",
          "size": 3039,
          "value": 3039
        },
        {
          "name": "visual/style.ts",
          "size": 9355,
          "value": 9355
        },
        {
          "name": "visual/symbol.ts",
          "size": 6643,
          "value": 6643
        },
        {
          "name": "visual/visualDefault.ts",
          "size": 2061,
          "value": 2061
        },
        {
          "name": "visual/visualSolution.ts",
          "size": 8551,
          "value": 8551
        }
      ],
      "value": 70915
    },
    {
      "name": "zrender",
      "children": [
        {
          "name": "Element.ts",
          "size": 62570,
          "value": 62570
        },
        {
          "name": "Handler.ts",
          "size": 16369,
          "value": 16369
        },
        {
          "name": "PainterBase.ts",
          "size": 1043,
          "value": 1043
        },
        {
          "name": "Storage.ts",
          "size": 7345,
          "value": 7345
        },
        {
          "name": "animation",
          "size": 51765,
          "children": [
            {
              "name": "animation/Animation.ts",
              "size": 5960,
              "value": 5960
            },
            {
              "name": "animation/Animator.ts",
              "size": 33681,
              "value": 33681
            },
            {
              "name": "animation/Clip.ts",
              "size": 3788,
              "value": 3788
            },
            {
              "name": "animation/easing.ts",
              "size": 7646,
              "value": 7646
            },
            {
              "name": "animation/requestAnimationFrame.ts",
              "size": 690,
              "value": 690
            }
          ],
          "value": 51765
        },
        {
          "name": "canvas",
          "size": 79635,
          "children": [
            {
              "name": "canvas/Layer.ts",
              "size": 17024,
              "value": 17024
            },
            {
              "name": "canvas/Painter.ts",
              "size": 32574,
              "value": 32574
            },
            {
              "name": "canvas/canvas.ts",
              "size": 113,
              "value": 113
            },
            {
              "name": "canvas/graphic.ts",
              "size": 27228,
              "value": 27228
            },
            {
              "name": "canvas/helper.ts",
              "size": 2696,
              "value": 2696
            }
          ],
          "value": 79635
        },
        {
          "name": "config.ts",
          "size": 800,
          "value": 800
        },
        {
          "name": "contain",
          "size": 25900,
          "children": [
            {
              "name": "contain/arc.ts",
              "size": 1168,
              "value": 1168
            },
            {
              "name": "contain/cubic.ts",
              "size": 838,
              "value": 838
            },
            {
              "name": "contain/line.ts",
              "size": 981,
              "value": 981
            },
            {
              "name": "contain/path.ts",
              "size": 12770,
              "value": 12770
            },
            {
              "name": "contain/polygon.ts",
              "size": 722,
              "value": 722
            },
            {
              "name": "contain/quadratic.ts",
              "size": 753,
              "value": 753
            },
            {
              "name": "contain/text.ts",
              "size": 7844,
              "value": 7844
            },
            {
              "name": "contain/util.ts",
              "size": 170,
              "value": 170
            },
            {
              "name": "contain/windingLine.ts",
              "size": 654,
              "value": 654
            }
          ],
          "value": 25900
        },
        {
          "name": "core",
          "size": 182134,
          "children": [
            {
              "name": "core/BoundingRect.ts",
              "size": 7805,
              "value": 7805
            },
            {
              "name": "core/Eventful.ts",
              "size": 9493,
              "value": 9493
            },
            {
              "name": "core/GestureMgr.ts",
              "size": 3179,
              "value": 3179
            },
            {
              "name": "core/LRU.ts",
              "size": 3498,
              "value": 3498
            },
            {
              "name": "core/OrientedBoundingRect.ts",
              "size": 5917,
              "value": 5917
            },
            {
              "name": "core/PathProxy.ts",
              "size": 36414,
              "value": 36414
            },
            {
              "name": "core/Point.ts",
              "size": 4097,
              "value": 4097
            },
            {
              "name": "core/Transformable.ts",
              "size": 9273,
              "value": 9273
            },
            {
              "name": "core/WeakMap.ts",
              "size": 1216,
              "value": 1216
            },
            {
              "name": "core/arrayDiff.ts",
              "size": 6082,
              "value": 6082
            },
            {
              "name": "core/bbox.ts",
              "size": 5038,
              "value": 5038
            },
            {
              "name": "core/curve.ts",
              "size": 12552,
              "value": 12552
            },
            {
              "name": "core/dom.ts",
              "size": 5970,
              "value": 5970
            },
            {
              "name": "core/env.ts",
              "size": 3281,
              "value": 3281
            },
            {
              "name": "core/event.ts",
              "size": 12491,
              "value": 12491
            },
            {
              "name": "core/fourPointsTransform.ts",
              "size": 3622,
              "value": 3622
            },
            {
              "name": "core/matrix.ts",
              "size": 3136,
              "value": 3136
            },
            {
              "name": "core/timsort.ts",
              "size": 17183,
              "value": 17183
            },
            {
              "name": "core/types.ts",
              "size": 3240,
              "value": 3240
            },
            {
              "name": "core/util.ts",
              "size": 24309,
              "value": 24309
            },
            {
              "name": "core/vector.ts",
              "size": 4338,
              "value": 4338
            }
          ],
          "value": 182134
        },
        {
          "name": "debug",
          "size": 3492,
          "children": [
            {
              "name": "debug/showDebugDirtyRect.ts",
              "size": 3492,
              "value": 3492
            }
          ],
          "value": 3492
        },
        {
          "name": "dom",
          "size": 22220,
          "children": [
            {
              "name": "dom/HandlerProxy.ts",
              "size": 22220,
              "value": 22220
            }
          ],
          "value": 22220
        },
        {
          "name": "export.ts",
          "size": 3317,
          "value": 3317
        },
        {
          "name": "graphic",
          "size": 169365,
          "children": [
            {
              "name": "graphic/CompoundPath.ts",
              "size": 1606,
              "value": 1606
            },
            {
              "name": "graphic/Displayable.ts",
              "size": 19541,
              "value": 19541
            },
            {
              "name": "graphic/Gradient.ts",
              "size": 754,
              "value": 754
            },
            {
              "name": "graphic/Group.ts",
              "size": 7645,
              "value": 7645
            },
            {
              "name": "graphic/Image.ts",
              "size": 3227,
              "value": 3227
            },
            {
              "name": "graphic/IncrementalDisplayable.ts",
              "size": 4426,
              "value": 4426
            },
            {
              "name": "graphic/LinearGradient.ts",
              "size": 1096,
              "value": 1096
            },
            {
              "name": "graphic/Path.ts",
              "size": 21284,
              "value": 21284
            },
            {
              "name": "graphic/Pattern.ts",
              "size": 1721,
              "value": 1721
            },
            {
              "name": "graphic/RadialGradient.ts",
              "size": 1020,
              "value": 1020
            },
            {
              "name": "graphic/TSpan.ts",
              "size": 2844,
              "value": 2844
            },
            {
              "name": "graphic/Text.ts",
              "size": 33862,
              "value": 33862
            },
            {
              "name": "graphic/constants.ts",
              "size": 168,
              "value": 168
            },
            {
              "name": "graphic/helper",
              "size": 47692,
              "children": [
                {
                  "name": "graphic/helper/dashStyle.ts",
                  "size": 503,
                  "value": 503
                },
                {
                  "name": "graphic/helper/image.ts",
                  "size": 2989,
                  "value": 2989
                },
                {
                  "name": "graphic/helper/parseText.ts",
                  "size": 23755,
                  "value": 23755
                },
                {
                  "name": "graphic/helper/poly.ts",
                  "size": 1510,
                  "value": 1510
                },
                {
                  "name": "graphic/helper/roundRect.ts",
                  "size": 2138,
                  "value": 2138
                },
                {
                  "name": "graphic/helper/roundSector.ts",
                  "size": 8730,
                  "value": 8730
                },
                {
                  "name": "graphic/helper/smoothBezier.ts",
                  "size": 2607,
                  "value": 2607
                },
                {
                  "name": "graphic/helper/smoothSpline.ts",
                  "size": 1599,
                  "value": 1599
                },
                {
                  "name": "graphic/helper/subPixelOptimize.ts",
                  "size": 3861,
                  "value": 3861
                }
              ],
              "value": 47692
            },
            {
              "name": "graphic/shape",
              "size": 22479,
              "children": [
                {
                  "name": "graphic/shape/Arc.ts",
                  "size": 1122,
                  "value": 1122
                },
                {
                  "name": "graphic/shape/BezierCurve.ts",
                  "size": 3363,
                  "value": 3363
                },
                {
                  "name": "graphic/shape/Circle.ts",
                  "size": 1081,
                  "value": 1081
                },
                {
                  "name": "graphic/shape/Droplet.ts",
                  "size": 1070,
                  "value": 1070
                },
                {
                  "name": "graphic/shape/Ellipse.ts",
                  "size": 1222,
                  "value": 1222
                },
                {
                  "name": "graphic/shape/Heart.ts",
                  "size": 950,
                  "value": 950
                },
                {
                  "name": "graphic/shape/Isogon.ts",
                  "size": 1096,
                  "value": 1096
                },
                {
                  "name": "graphic/shape/Line.ts",
                  "size": 1985,
                  "value": 1985
                },
                {
                  "name": "graphic/shape/Polygon.ts",
                  "size": 811,
                  "value": 811
                },
                {
                  "name": "graphic/shape/Polyline.ts",
                  "size": 1023,
                  "value": 1023
                },
                {
                  "name": "graphic/shape/Rect.ts",
                  "size": 1927,
                  "value": 1927
                },
                {
                  "name": "graphic/shape/Ring.ts",
                  "size": 781,
                  "value": 781
                },
                {
                  "name": "graphic/shape/Rose.ts",
                  "size": 1484,
                  "value": 1484
                },
                {
                  "name": "graphic/shape/Sector.ts",
                  "size": 889,
                  "value": 889
                },
                {
                  "name": "graphic/shape/Star.ts",
                  "size": 1698,
                  "value": 1698
                },
                {
                  "name": "graphic/shape/Trochoid.ts",
                  "size": 1977,
                  "value": 1977
                }
              ],
              "value": 22479
            }
          ],
          "value": 169365
        },
        {
          "name": "mixin",
          "size": 3505,
          "children": [
            {
              "name": "mixin/Draggable.ts",
              "size": 3505,
              "value": 3505
            }
          ],
          "value": 3505
        },
        {
          "name": "svg",
          "size": 63006,
          "children": [
            {
              "name": "svg/Painter.ts",
              "size": 15932,
              "value": 15932
            },
            {
              "name": "svg/core.ts",
              "size": 120,
              "value": 120
            },
            {
              "name": "svg/graphic.ts",
              "size": 13503,
              "value": 13503
            },
            {
              "name": "svg/helper",
              "size": 33341,
              "children": [
                {
                  "name": "svg/helper/ClippathManager.ts",
                  "size": 5600,
                  "value": 5600
                },
                {
                  "name": "svg/helper/Definable.ts",
                  "size": 7152,
                  "value": 7152
                },
                {
                  "name": "svg/helper/GradientManager.ts",
                  "size": 8044,
                  "value": 8044
                },
                {
                  "name": "svg/helper/PatternManager.ts",
                  "size": 7269,
                  "value": 7269
                },
                {
                  "name": "svg/helper/ShadowManager.ts",
                  "size": 5276,
                  "value": 5276
                }
              ],
              "value": 33341
            },
            {
              "name": "svg/svg.ts",
              "size": 110,
              "value": 110
            }
          ],
          "value": 63006
        },
        {
          "name": "tool",
          "size": 122091,
          "children": [
            {
              "name": "tool/color.ts",
              "size": 19085,
              "value": 19085
            },
            {
              "name": "tool/convertPath.ts",
              "size": 8959,
              "value": 8959
            },
            {
              "name": "tool/dividePath.ts",
              "size": 12704,
              "value": 12704
            },
            {
              "name": "tool/morphPath.ts",
              "size": 28139,
              "value": 28139
            },
            {
              "name": "tool/parseSVG.ts",
              "size": 33804,
              "value": 33804
            },
            {
              "name": "tool/parseXML.ts",
              "size": 692,
              "value": 692
            },
            {
              "name": "tool/path.ts",
              "size": 16023,
              "value": 16023
            },
            {
              "name": "tool/transformPath.ts",
              "size": 2685,
              "value": 2685
            }
          ],
          "value": 122091
        },
        {
          "name": "vml",
          "size": 42681,
          "children": [
            {
              "name": "vml/Painter.ts",
              "size": 5103,
              "value": 5103
            },
            {
              "name": "vml/core.ts",
              "size": 1242,
              "value": 1242
            },
            {
              "name": "vml/graphic.ts",
              "size": 36190,
              "value": 36190
            },
            {
              "name": "vml/vml.ts",
              "size": 146,
              "value": 146
            }
          ],
          "value": 42681
        },
        {
          "name": "zrender.ts",
          "size": 13102,
          "value": 13102
        }
      ]
    }
  ],
  "value": 3835461
};
const treemapOption = {
      series: [
        {
          type: 'treemap',
          id: 'echarts-package-size',
          animationDurationUpdate: 1000,
          roam: false,
          nodeClick: undefined,
          data: data.children,
          universalTransition: true,
          label: {
            show: true
          },
          breadcrumb: {
            show: false
          }
        }
      ]
    };
    const sunburstOption = {
      series: [
        {
          type: 'sunburst',
          id: 'echarts-package-size',
          radius: ['20%', '90%'],
          animationDurationUpdate: 1000,
          nodeClick: undefined,
          data: data.children,
          universalTransition: true,
          itemStyle: {
            borderWidth: 1,
            borderColor: 'rgba(255,255,255,.5)'
          },
          label: {
            show: false
          }
        }
      ]
    };
    let currentOption = treemapOption;
    myChart.setOption(currentOption);
    setInterval(function () {
      currentOption =
        currentOption === treemapOption ? sunburstOption : treemapOption;
      myChart.setOption(currentOption);
    }, 3000);

```
