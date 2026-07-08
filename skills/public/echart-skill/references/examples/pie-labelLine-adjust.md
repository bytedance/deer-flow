# pie-labelLine-adjust

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=pie-labelLine-adjust
**Chart Type:** `pie`

## User Data Requirements

Columns needed: need **name** + **value** columns

## Data Arrays — Replacement Guide

The code contains **0 data array(s)** to replace:

## Agent Workflow

1. **Analyze** user table → identify columns matching the required format above
2. **Query DuckDB** → transform to match each data array's format
3. **Replace**: use **bracket-counting** to find each `data: [...]` → replace with real data
4. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: Label Line Adjust
category: pie
titleCN: 饼图引导线调整
difficulty: 3
*/
var datas = [
  ////////////////////////////////////////
  [
    { name: '圣彼得堡来客', value: 5.6 },
    { name: '陀思妥耶夫斯基全集', value: 1 },
    { name: '史记精注全译（全6册）', value: 0.8 },
    { name: '加德纳艺术通史', value: 0.5 },
    { name: '表象与本质', value: 0.5 },
    { name: '其它', value: 3.8 }
  ],
  // ////////////////////////////////////////
  [
    { name: '银河帝国5：迈向基地', value: 3.8 },
    { name: '俞军产品方法论', value: 2.3 },
    { name: '艺术的逃难', value: 2.2 },
    { name: '第一次世界大战回忆录（全五卷）', value: 1.3 },
    { name: 'Scrum 精髓', value: 1.2 },
    { name: '其它', value: 5.7 }
  ],
  ////////////////////////////////////////
  [
    { name: '克莱因壶', value: 3.5 },
    { name: '投资最重要的事', value: 2.8 },
    { name: '简读中国史', value: 1.7 },
    { name: '你当像鸟飞往你的山', value: 1.4 },
    { name: '表象与本质', value: 0.5 },
    { name: '其它', value: 3.8 }
  ]
];
option = {
  title: {
    text: '阅读书籍分布',
    left: 'center',
    textStyle: {
      color: '#999',
      fontWeight: 'normal',
      fontSize: 14
    }
  },
  series: datas.map(function (data, idx) {
    var top = idx * 33.3;
    return {
      type: 'pie',
      radius: [20, 60],
      top: top + '%',
      height: '33.33%',
      left: 'center',
      width: 400,
      itemStyle: {
        borderColor: '#fff',
        borderWidth: 1
      },
      label: {
        alignTo: 'edge',
        formatter: '{name|{b}}\n{time|{c} 小时}',
        minMargin: 5,
        edgeDistance: 10,
        lineHeight: 15,
        rich: {
          time: {
            fontSize: 10,
            color: '#999'
          }
        }
      },
      labelLine: {
        length: 15,
        length2: 0,
        maxSurfaceAngle: 80
      },
      labelLayout: function (params) {
        const isLeft = params.labelRect.x < myChart.getWidth() / 2;
        const points = params.labelLinePoints;
        // Update the end point.
        points[2][0] = isLeft
          ? params.labelRect.x
          : params.labelRect.x + params.labelRect.width;
        return {
          labelLinePoints: points
        };
      },
      data: data
    };
  })
};
```
