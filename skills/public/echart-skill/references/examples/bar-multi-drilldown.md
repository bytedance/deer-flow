# bar-multi-drilldown

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=bar-multi-drilldown
**Chart Type:** `category`

## User Data Requirements

Columns needed: check data arrays in reference code for required format

## Data Arrays — Complete Replacement Guide

**1 array(s)** to replace with real data:

### [0] `dimensions` (context: series)
```
dimensions: ['x', 'y', 'groupId', 'childGroupId']
```

## Agent Workflow

1. **Analyze** user table → identify columns matching the required format above
2. **Query DuckDB** → transform to match each data array's format
3. **Replace**: use **bracket-counting** to find each `data: [...]` → replace with real data
4. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: Bar Chart Multi-level Drilldown Animation
category: bar
titleCN: 柱状图多层下钻动画
difficulty: 6
*/
// This example requires ECharts v5.5.0 or later
// level 1 (root)
const data_things = [
  ['Animals', 3, 'things', 'animals'],
  ['Fruits', 3, 'things', 'fruits'],
  ['Cars', 2, 'things', 'cars']
];
// level 2
const data_animals = [
  ['Dogs', 3, 'animals', 'dogs'],
  ['Cats', 4, 'animals', 'cats'],
  ['Birds', 3, 'animals', 'birds']
];
const data_fruits = [
  ['Pomes', 3, 'fruits', 'pomes'],
  ['Berries', 4, 'fruits', 'berries'],
  ['Citrus', 9, 'fruits', 'citrus']
];
const data_cars = [
  ['SUV', 5, 'cars', 'suv'],
  ['Sports', 3, 'cars', 'sports']
];
// level 3
const data_dogs = [
  ['Corgi', 5, 'dogs'],
  ['Bulldog', 6, 'dogs'],
  ['Shiba Inu', 7, 'dogs']
];
const data_cats = [
  ['American Shorthair', 2, 'cats'],
  ['British Shorthair', 9, 'cats'],
  ['Bengal', 2, 'cats'],
  ['Birman', 2, 'cats']
];
const data_birds = [
  ['Goose', 1, 'birds'],
  ['Owl', 2, 'birds'],
  ['Eagle', 8, 'birds']
];
const data_pomes = [
  ['Apple', 9, 'pomes'],
  ['Pear', 2, 'pomes'],
  ['Kiwi', 1, 'pomes']
];
const data_berries = [
  ['Blackberries', 7, 'berries'],
  ['Cranberries', 2, 'berries'],
  ['Strawberries', 9, 'berries'],
  ['Grapes', 4, 'berries']
];
const data_citrus = [
  ['Oranges', 3, 'citrus'],
  ['Grapefruits', 7, 'citrus'],
  ['Tangerines', 8, 'citrus'],
  ['Lemons', 7, 'citrus'],
  ['Limes', 3, 'citrus'],
  ['Kumquats', 2, 'citrus'],
  ['Citrons', 3, 'citrus'],
  ['Tengelows', 3, 'citrus'],
  ['Uglifruit', 1, 'citrus']
];
const data_suv = [
  ['Mazda CX-30', 7, 'suv'],
  ['BMW X2', 7, 'suv'],
  ['Ford Bronco Sport', 2, 'suv'],
  ['Toyota RAV4', 9, 'suv'],
  ['Porsche Macan', 4, 'suv']
];
const data_sports = [
  ['Porsche 718 Cayman', 2, 'sports'],
  ['Porsche 911 Turbo', 2, 'sports'],
  ['Ferrari F8', 4, 'sports']
];
const allLevelData = [
  data_things,
  data_animals,
  data_fruits,
  data_cars,
  data_dogs,
  data_cats,
  data_birds,
  data_pomes,
  data_berries,
  data_citrus,
  data_suv,
  data_sports
];
const allOptions = {};
allLevelData.forEach((data, index) => {
  // since dataItems of each data have same groupId in this
  // example, we can use groupId as optionId for optionStack.
  const optionId = data[0][2];
  const option = {
    id: optionId,
    xAxis: {
      type: 'category'
    },
    yAxis: {
      minInterval: 1
    },
    animationDurationUpdate: 500,
    series: {
      type: 'bar',
      dimensions: ['x', 'y', 'groupId', 'childGroupId'],
      encode: {
        x: 'x',
        y: 'y',
        itemGroupId: 'groupId',
        itemChildGroupId: 'childGroupId'
      },
      data,
      universalTransition: {
        enabled: true,
        divideShape: 'clone'
      }
    },
    graphic: [
      {
        type: 'text',
        left: 50,
        top: 20,
        style: {
          text: 'Back',
          fontSize: 18,
          fill: 'grey'
        },
        onclick: function () {
          goBack();
        }
      }
    ]
  };
  allOptions[optionId] = option;
});
// A stack to remember previous option id
const optionStack = [];
const goForward = (optionId) => {
  optionStack.push(myChart.getOption().id); // push current option id into stack.
  myChart.setOption(allOptions[optionId]);
};
const goBack = () => {
  if (optionStack.length === 0) {
    console.log('Already in root level!');
  } else {
    console.log('Go back to previous level.');
    myChart.setOption(allOptions[optionStack.pop()]);
  }
};
option = allOptions['things']; // The initial option is the root data option
myChart.on('click', 'series', (params) => {
  const dataItem = params.data;
  if (dataItem[3]) {
    // If current params is not belong to the "childest" data, it has data[3]
    const childGroupId = dataItem[3];
    // since we use groupId as optionId in this example,
    // we use childGroupId as the next level optionId.
    const nextOptionId = childGroupId;
    goForward(nextOptionId);
  }
});
```
