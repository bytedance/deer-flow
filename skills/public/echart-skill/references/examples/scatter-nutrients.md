# scatter-nutrients

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=scatter-nutrients
**Chart Type:** `piecewise`

## User Data Requirements

Columns needed: check data arrays in reference code for required format

## Data Arrays — Replacement Guide

The code contains **0 data array(s)** to replace:


## External Data Format

This example uses external data. Format from `nutrients.json`:

```json
[
  [
    "Beverage, instant breakfast powder, chocolate, not reconstituted",
    "Dairy and Egg Products",
    19.9,
    0.285,
    0.385,
    0.4,
    0.07690000000000001,
    0.947,
    66.2,
    65.8,
    1.4,
    7.4,
    357,
    0.56,
    0.314,
    0.278,
    27481
  ],
  [
    "Beverage, instant breakfast powder, chocolate, sugar-free, not reconstituted",
    "Dairy and Egg Products",
    35.8,
    0.5,
    0.717,
    2,
    0.138,
    1.705,
    41,
    39,
    5.1,
    7.4,
    358,
 
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
title: Scatter Nutrients
category: scatter
titleCN: 营养分布散点图
difficulty: 7
*/
const indices = {
  name: 0,
  group: 1,
  id: 16
};
const schema = [
  { name: 'name', index: 0 },
  { name: 'group', index: 1 },
  { name: 'protein', index: 2 },
  { name: 'calcium', index: 3 },
  { name: 'sodium', index: 4 },
  { name: 'fiber', index: 5 },
  { name: 'vitaminc', index: 6 },
  { name: 'potassium', index: 7 },
  { name: 'carbohydrate', index: 8 },
  { name: 'sugars', index: 9 },
// ... (16 total entries — truncated, Agent: query DuckDB)
];
const fieldIndices = schema.reduce(function (obj, item) {
  obj[item.name] = item.index;
  return obj;
}, {});
const groupCategories = [];
const groupColors = [];
let data;
// zlevel 为 1 的层开启尾迹特效
myChart.getZr().configLayer(1, {
  motionBlur: true
});
var originData = [
  [
    "Beverage, instant breakfast powder, chocolate, not reconstituted",
    "Dairy and Egg Products",
    19.9,
    0.285,
    0.385,
    0.4,
    0.07690000000000001,
    0.947,
    66.2,
    65.8,
  // ... (16 total entries — truncated, Agent: query DuckDB)
  ],
  [
    "Beverage, instant breakfast powder, chocolate, sugar-free, not reconstituted",
    "Dairy and Egg Products",
    35.8,
    0.5,
    0.717,
    2,
    0.138,
    1.705,
    41,
    39,
    5.1,
    7.4,
    358,
    2.162,
    1.189,
    1.027,
    27482
  ],
  [
    "Beverage, milkshake mix, dry, not chocolate",
    "Dairy and Egg Products",
    23.5,
    0.88,
    0.78,
    1.6,
    0.0012,
    2.2,
    52.9,
    51.3,
    2.6,
    12.8,
    329,
    2.059,
    0.332,
    0.06,
    27483
  ],
  [
    "Butter oil, anhydrous",
    "Dairy and Egg Products",
    0.28,
    0.004,
    0.002,
    null,
    0,
    0.005,
    null,
    null,
    99.48,
    0.24,
    876,
    61.924,
    28.732,
    3.694,
    27484
  ],
  [
    "Butter, salted",
    "Dairy and Egg Products",
    0.85,
    0.024,
    0.714,
    null,
    0,
    0.024,
    0.06,
    0.06,
    81.11,
    15.87,
    717,
    51.368,
    21.021,
    3.043,
    27485
  ],
  [
    "Butter, whipped, with salt",
    "Dairy and Egg Products",
    0.85,
    0.024,
    0.827,
    null,
    0,
    0.026,
    0.06,
    0.06,
    81.11,
    15.87,
    717,
    50.489,
    23.426,
    3.012,
    27486
  ],
  [
    "Butter, without salt",
    "Dairy and Egg Products",
    0.85,
    0.024,
    0.011,
    null,
    0,
    0.024,
    0.06,
    0.06,
    81.11,
    17.94,
    717,
    51.368,
    21.021,
    3.043,
    27487
  ],
  [
    "Cheese fondue",
    "Dairy and Egg Products",
    14.23,
    0.476,
    0.132,
    null,
    0,
    0.105,
    3.77,
    null,
    13.47,
    61.61,
    229,
    8.721,
    3.563,
    0.484,
    27488
  ],
  [
    "Cheese food, cold pack, american",
    "Dairy and Egg Products",
    19.66,
    0.497,
    0.966,
    null,
    0,
    0.363,
    8.32,
    null,
    24.46,
    43.12,
    331,
    15.355,
    7.165,
    0.719,
    27489
  ],
  [
    "Cheese food, imitation",
    "Dairy and Egg Products",
    22.4,
    0.552,
    1.239,
    null,
    0,
    0.336,
    8.8,
    8.21,
    1.3,
    63.8,
    137,
    0.81,
    0.38,
    0.048,
    27490
  ],
  [
    "Cheese food, pasteurized process, american, with di sodium phosphate",
    "Dairy and Egg Products",
    19.61,
    0.574,
    1.596,
    null,
    0,
    0.279,
    7.29,
    7.43,
    24.6,
    43.15,
    328,
    15.443,
    7.206,
    0.723,
  // ... (7636 total entries — truncated, Agent: query DuckDB)
  ]
];
data = normalizeData(originData).slice(0, 1000);
  myChart.setOption((option = getOption(data)));

function normalizeData(originData) {
  let groupMap = {};
  originData.forEach(function (row) {
    let groupName = row[indices.group];
    if (!groupMap.hasOwnProperty(groupName)) {
      groupMap[groupName] = 1;
    }
  });
  originData.forEach(function (row) {
    row.forEach(function (item, index) {
      if (
        index !== indices.name &&
        index !== indices.group &&
        index !== indices.id
      ) {
        // Convert null to zero, as all of them under unit "g".
        row[index] = parseFloat(item) || 0;
      }
    });
  });
  for (let groupName in groupMap) {
    if (groupMap.hasOwnProperty(groupName)) {
      groupCategories.push(groupName);
    }
  }
  let hStep = Math.round(300 / (groupCategories.length - 1));
  for (let i = 0; i < groupCategories.length; i++) {
    groupColors.push(echarts.color.modifyHSL('#5A94DF', hStep * i));
  }
  return originData;
}
function getOption(data) {
  return {
    xAxis: {
      name: 'protein',
      splitLine: { show: false }
    },
    yAxis: {
      name: 'calcium',
      splitLine: { show: false }
    },
    visualMap: [
      {
        show: false,
        type: 'piecewise',
        categories: groupCategories,
        dimension: 2,
        inRange: {
          color: groupColors
        },
        outOfRange: {
          color: ['#ccc']
        },
        top: 20,
        textStyle: {
          color: '#fff'
        },
        realtime: false
      },
      {
        show: false,
        dimension: 3,
        max: 100,
        inRange: {
          colorLightness: [0.15, 0.6]
        }
      }
    ],
    series: [
      {
        zlevel: 1,
        name: 'nutrients',
        type: 'scatter',
        data: data.map(function (item, idx) {
          return [item[2], item[3], item[1], idx];
        }),
        animationThreshold: 5000,
        progressiveThreshold: 5000
      }
    ],
    animationEasingUpdate: 'cubicInOut',
    animationDurationUpdate: 2000
  };
}
let fieldNames = schema
  .map(function (item) {
    return item.name;
  })
  .slice(2);
app.config = {
  xAxis: 'protein',
  yAxis: 'calcium',
  onChange: function () {
    if (data) {
      myChart.setOption({
        xAxis: {
          name: app.config.xAxis
        },
        yAxis: {
          name: app.config.yAxis
        },
        series: {
          data: data.map(function (item, idx) {
            return [
              item[fieldIndices[app.config.xAxis]],
              item[fieldIndices[app.config.yAxis]],
              item[1],
              idx
            ];
          })
        }
      });
    }
  }
};
app.configParameters = {
  xAxis: {
    options: fieldNames
  },
  yAxis: {
    options: fieldNames
  }
};
```
