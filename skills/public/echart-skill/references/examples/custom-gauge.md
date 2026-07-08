# custom-gauge

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=custom-gauge
**Chart Type:** `group`

## User Data Requirements

Columns needed: check data arrays in reference code for required format

## Data Arrays — Complete Replacement Guide

**2 array(s)** to replace with real data:

### [0] `source` (context: dataset)
```
source: [[1, 156]]
```

### [1] `children` (context: root)
```
children: 
```

## Agent Workflow

1. **Analyze** user table → identify columns matching the required format above
2. **Query DuckDB** → transform to match each data array's format
3. **Replace**: use **bracket-counting** to find each `data: [...]` → replace with real data
4. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: Custom Gauge
category: custom
titleCN: 自定义仪表
difficulty: 9
*/
var _panelImageURL = 'data:image/png;base64,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';
var _animationDuration = 1000;
var _animationDurationUpdate = 1000;
var _animationEasingUpdate = 'quarticInOut';
var _valOnRadianMax = 200;
var _outerRadius = 200;
var _innerRadius = 170;
var _pointerInnerRadius = 40;
var _insidePanelRadius = 140;
var _currentDataIndex = 0;
function renderItem(params, api) {
  var valOnRadian = api.value(1);
  var coords = api.coord([api.value(0), valOnRadian]);
  var polarEndRadian = coords[3];
  var imageStyle = {
    image: _panelImageURL,
    x: params.coordSys.cx - _outerRadius,
    y: params.coordSys.cy - _outerRadius,
    width: _outerRadius * 2,
    height: _outerRadius * 2
  };
  return {
    type: 'group',
    children: [
      {
        type: 'image',
        style: imageStyle,
        clipPath: {
          type: 'sector',
          shape: {
            cx: params.coordSys.cx,
            cy: params.coordSys.cy,
            r: _outerRadius,
            r0: _innerRadius,
            startAngle: 0,
            endAngle: -polarEndRadian,
            transition: 'endAngle',
            enterFrom: { endAngle: 0 }
          }
        }
      },
      {
        type: 'image',
        style: imageStyle,
        clipPath: {
          type: 'polygon',
          shape: {
            points: makePionterPoints(params, polarEndRadian)
          },
          extra: {
            polarEndRadian: polarEndRadian,
            transition: 'polarEndRadian',
            enterFrom: { polarEndRadian: 0 }
          },
          during: function (apiDuring) {
            apiDuring.setShape(
              'points',
              makePionterPoints(params, apiDuring.getExtra('polarEndRadian'))
            );
          }
        }
      },
      {
        type: 'circle',
        shape: {
          cx: params.coordSys.cx,
          cy: params.coordSys.cy,
          r: _insidePanelRadius
        },
        style: {
          fill: '#fff',
          shadowBlur: 25,
          shadowOffsetX: 0,
          shadowOffsetY: 0,
          shadowColor: 'rgba(76,107,167,0.4)'
        }
      },
      {
        type: 'text',
        extra: {
          valOnRadian: valOnRadian,
          transition: 'valOnRadian',
          enterFrom: { valOnRadian: 0 }
        },
        style: {
          text: makeText(valOnRadian),
          fontSize: 50,
          fontWeight: 700,
          x: params.coordSys.cx,
          y: params.coordSys.cy,
          fill: 'rgb(0,50,190)',
          align: 'center',
          verticalAlign: 'middle',
          enterFrom: { opacity: 0 }
        },
        during: function (apiDuring) {
          apiDuring.setStyle(
            'text',
            makeText(apiDuring.getExtra('valOnRadian'))
          );
        }
      }
    ]
  };
}
function convertToPolarPoint(renderItemParams, radius, radian) {
  return [
    Math.cos(radian) * radius + renderItemParams.coordSys.cx,
    -Math.sin(radian) * radius + renderItemParams.coordSys.cy
  ];
}
function makePionterPoints(renderItemParams, polarEndRadian) {
  return [
    convertToPolarPoint(renderItemParams, _outerRadius, polarEndRadian),
    convertToPolarPoint(
      renderItemParams,
      _outerRadius,
      polarEndRadian + Math.PI * 0.03
    ),
    convertToPolarPoint(renderItemParams, _pointerInnerRadius, polarEndRadian)
  ];
}
function makeText(valOnRadian) {
  // Validate additive animation calc.
  if (valOnRadian < -10) {
    alert('illegal during val: ' + valOnRadian);
  }
  return ((valOnRadian / _valOnRadianMax) * 100).toFixed(0) + '%';
}
option = {
  animationEasing: _animationEasingUpdate,
  animationDuration: _animationDuration,
  animationDurationUpdate: _animationDurationUpdate,
  animationEasingUpdate: _animationEasingUpdate,
  dataset: {
    source: [[1, 156]]
  },
  tooltip: {},
  angleAxis: {
    type: 'value',
    startAngle: 0,
    show: false,
    min: 0,
    max: _valOnRadianMax
  },
  radiusAxis: {
    type: 'value',
    show: false
  },
  polar: {},
  series: [
    {
      type: 'custom',
      coordinateSystem: 'polar',
      renderItem: renderItem
    }
  ]
};
setInterval(function () {
  var nextSource = [[1, Math.round(Math.random() * _valOnRadianMax)]];
  myChart.setOption({
    dataset: {
      source: nextSource
    }
  });
}, 3000);
```
