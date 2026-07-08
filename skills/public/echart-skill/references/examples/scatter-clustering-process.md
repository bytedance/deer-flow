# scatter-clustering-process

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=scatter-clustering-process
**Chart Type:** `circle`

## User Data Requirements

Columns needed: check data arrays in reference code for required format

## Data Arrays — Complete Replacement Guide

**1 array(s)** to replace with real data:

### [0] `data` (context: root)
```
data: []
```

## Agent Workflow

1. **Analyze** user table → identify columns matching the required format above
2. **Query DuckDB** → transform to match each data array's format
3. **Replace**: use **bracket-counting** to find each `data: [...]` → replace with real data
4. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: Clustering Process
category: scatter
titleCN: 聚合过程可视化
difficulty: 1
*/
var originalData = [
  [3.275154, 2.957587],
  [-3.344465, 2.603513],
  [0.355083, -3.376585],
  [1.852435, 3.547351],
  [-2.078973, 2.552013],
  [-0.993756, -0.884433],
  [2.682252, 4.007573],
  [-3.087776, 2.878713],
  [-1.565978, -1.256985],
  [2.441611, 0.444826],
  [-0.659487, 3.111284],
  [-0.459601, -2.618005],
  [2.17768, 2.387793],
  [-2.920969, 2.917485],
  [-0.028814, -4.168078],
  [3.625746, 2.119041],
  [-3.912363, 1.325108],
  [-0.551694, -2.814223],
  [2.855808, 3.483301],
  [-3.594448, 2.856651],
  [0.421993, -2.372646],
  [1.650821, 3.407572],
  [-2.082902, 3.384412],
  [-0.718809, -2.492514],
  [4.513623, 3.841029],
  [-4.822011, 4.607049],
  [-0.656297, -1.449872],
  [1.919901, 4.439368],
  [-3.287749, 3.918836],
  [-1.576936, -2.977622],
  [3.598143, 1.97597],
  [-3.977329, 4.900932],
  [-1.79108, -2.184517],
  [3.914654, 3.559303],
  [-1.910108, 4.166946],
  [-1.226597, -3.317889],
  [1.148946, 3.345138],
  [-2.113864, 3.548172],
  [0.845762, -3.589788],
  [2.629062, 3.535831],
  [-1.640717, 2.990517],
  [-1.881012, -2.485405],
  [4.606999, 3.510312],
  [-4.366462, 4.023316],
  [0.765015, -3.00127],
  [3.121904, 2.173988],
  [-4.025139, 4.65231],
  [-0.559558, -3.840539],
  [4.376754, 4.863579],
  [-1.874308, 4.032237],
  [-0.089337, -3.026809],
  [3.997787, 2.518662],
  [-3.082978, 2.884822],
  [0.845235, -3.454465],
  [1.327224, 3.358778],
  [-2.889949, 3.596178],
  [-0.966018, -2.839827],
  [2.960769, 3.079555],
  [-3.275518, 1.577068],
  [0.639276, -3.41284]
];
var DIM_CLUSTER_INDEX = 2;
var DATA_DIM_IDX = [0, 1];
var CENTER_DIM_IDX = [3, 4];
// See https://github.com/ecomfe/echarts-stat
var step = ecStat.clustering.hierarchicalKMeans(originalData, {
  clusterCount: 6,
  outputType: 'single',
  outputClusterIndexDimension: DIM_CLUSTER_INDEX,
  outputCentroidDimensions: CENTER_DIM_IDX,
  stepByStep: true
});
var colorAll = [
  '#bbb',
  '#37A2DA',
  '#e06343',
  '#37a354',
  '#b55dba',
  '#b5bd48',
  '#8378EA',
  '#96BFFF'
];
var ANIMATION_DURATION_UPDATE = 1500;
function renderItemPoint(params, api) {
  var coord = api.coord([api.value(0), api.value(1)]);
  var clusterIdx = api.value(2);
  if (clusterIdx == null || isNaN(clusterIdx)) {
    clusterIdx = 0;
  }
  var isNewCluster = clusterIdx === api.value(3);
  var extra = {
    transition: []
  };
  var contentColor = colorAll[clusterIdx];
  return {
    type: 'circle',
    x: coord[0],
    y: coord[1],
    shape: {
      cx: 0,
      cy: 0,
      r: 10
    },
    extra: extra,
    style: {
      fill: contentColor,
      stroke: '#333',
      lineWidth: 1,
      shadowColor: contentColor,
      shadowBlur: isNewCluster ? 12 : 0,
      transition: ['shadowBlur', 'fill']
    }
  };
}
function renderBoundary(params, api) {
  var xVal = api.value(0);
  var yVal = api.value(1);
  var maxDist = api.value(2);
  var center = api.coord([xVal, yVal]);
  var size = api.size([maxDist, maxDist]);
  return {
    type: 'ellipse',
    shape: {
      cx: isNaN(center[0]) ? 0 : center[0],
      cy: isNaN(center[1]) ? 0 : center[1],
      rx: isNaN(size[0]) ? 0 : size[0] + 15,
      ry: isNaN(size[1]) ? 0 : size[1] + 15
    },
    extra: {
      renderProgress: ++targetRenderProgress,
      enterFrom: {
        renderProgress: 0
      },
      transition: 'renderProgress'
    },
    style: {
      fill: null,
      stroke: 'rgba(0,0,0,0.2)',
      lineDash: [4, 4],
      lineWidth: 4
    }
  };
}
function makeStepOption(option, data, centroids) {
  var newCluIdx = centroids ? centroids.length - 1 : -1;
  var maxDist = 0;
  for (var i = 0; i < data.length; i++) {
    var line = data[i];
    if (line[DIM_CLUSTER_INDEX] === newCluIdx) {
      var dist0 = Math.pow(line[DATA_DIM_IDX[0]] - line[CENTER_DIM_IDX[0]], 2);
      var dist1 = Math.pow(line[DATA_DIM_IDX[1]] - line[CENTER_DIM_IDX[1]], 2);
      maxDist = Math.max(maxDist, dist0 + dist1);
    }
  }
  var boundaryData = centroids
    ? [[centroids[newCluIdx][0], centroids[newCluIdx][1], Math.sqrt(maxDist)]]
    : [];
  option.options.push({
    series: [
      {
        type: 'custom',
        encode: {
          tooltip: [0, 1]
        },
        renderItem: renderItemPoint,
        data: data
      },
      {
        type: 'custom',
        renderItem: renderBoundary,
        animationDuration: 3000,
        silent: true,
        data: boundaryData
      }
    ]
  });
}
var targetRenderProgress = 0;
option = {
  timeline: {
    top: 'center',
    right: 50,
    height: 300,
    width: 10,
    inverse: true,
    autoPlay: false,
    playInterval: 2500,
    symbol: 'none',
    orient: 'vertical',
    axisType: 'category',
    label: {
      formatter: 'step {value}',
      position: 10
    },
    checkpointStyle: {
      animationDuration: ANIMATION_DURATION_UPDATE
    },
    data: []
  },
  baseOption: {
    animationDurationUpdate: ANIMATION_DURATION_UPDATE,
    transition: ['shape'],
    tooltip: {},
    xAxis: {
      type: 'value'
    },
    yAxis: {
      type: 'value'
    },
    series: [
      {
        type: 'scatter'
      }
    ]
  },
  options: []
};
makeStepOption(option, originalData);
option.timeline.data.push('0');
for (var i = 1, stepResult; !(stepResult = step.next()).isEnd; i++) {
  makeStepOption(
    option,
    echarts.util.clone(stepResult.data),
    echarts.util.clone(stepResult.centroids)
  );
  option.timeline.data.push(i + '');
}
```
