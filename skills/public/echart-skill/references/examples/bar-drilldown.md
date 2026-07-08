# bar-drilldown

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=bar-drilldown
**Chart Type:** `bar`

## User Data Requirements

Columns needed: need **category** + **value** columns

## Data Arrays — Complete Replacement Guide

**5 array(s)** to replace with real data:

### [0] `data` (context: xAxis)
```
data: ['Animals', 'Fruits', 'Cars']
```

### [1] `data` (context: series)
```
data: [
      {
        value: 5,
        groupId: 'animals'
      },
      {
        value: 2,
        groupId: 'fruits'
      },
      {
        val...
```

### [2] `data` (context: root)
```
data: [
      ['Cats', 4],
      ['Dogs', 2],
      ['Cows', 1],
      ['Sheep', 2],
      ['Pigs', 1]
    ]
```

### [3] `data` (context: root)
```
data: [
      ['Apples', 4],
      ['Oranges', 2]
    ]
```

### [4] `data` (context: root)
```
data: [
      ['Toyota', 4],
      ['Opel', 2],
      ['Volkswagen', 2]
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
title: Bar Chart Drilldown Animation
category: bar
titleCN: 柱状图下钻动画
difficulty: 5
*/
option = {
  xAxis: {
    data: ['Animals', 'Fruits', 'Cars']
  },
  yAxis: {},
  dataGroupId: '',
  animationDurationUpdate: 500,
  series: {
    type: 'bar',
    id: 'sales',
    data: [
      {
        value: 5,
        groupId: 'animals'
      },
      {
        value: 2,
        groupId: 'fruits'
      },
      {
        value: 4,
        groupId: 'cars'
      }
    ],
    universalTransition: {
      enabled: true,
      divideShape: 'clone'
    }
  }
};
const drilldownData = [
  {
    dataGroupId: 'animals',
    data: [
      ['Cats', 4],
      ['Dogs', 2],
      ['Cows', 1],
      ['Sheep', 2],
      ['Pigs', 1]
    ]
  },
  {
    dataGroupId: 'fruits',
    data: [
      ['Apples', 4],
      ['Oranges', 2]
    ]
  },
  {
    dataGroupId: 'cars',
    data: [
      ['Toyota', 4],
      ['Opel', 2],
      ['Volkswagen', 2]
    ]
  }
];
myChart.on('click', function (event) {
  if (event.data) {
    var subData = drilldownData.find(function (data) {
      return data.dataGroupId === event.data.groupId;
    });
    if (!subData) {
      return;
    }
    myChart.setOption({
      xAxis: {
        data: subData.data.map(function (item) {
          return item[0];
        })
      },
      series: {
        type: 'bar',
        id: 'sales',
        dataGroupId: subData.dataGroupId,
        data: subData.data.map(function (item) {
          return item[1];
        }),
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
            fontSize: 18
          },
          onclick: function () {
            myChart.setOption(option);
          }
        }
      ]
    });
  }
});
```
