# globe-country-carousel

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=globe-country-carousel
**Chart Type:** `map`

## User Data Requirements

Columns needed: need **region name** + **value** columns

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
title: Country Carousel
category: globe
titleCN: Country Carousel
*/
var canvas = document.createElement('canvas');
var mapChart = echarts.init(canvas, null, {
  width: 2048,
  height: 1024
});
mapChart.setOption({
  backgroundColor: '#999',
  geo: {
    type: 'map',
    map: 'world',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    boundingCoords: [
      [-180, 90],
      [180, -90]
    ],
    silent: true,
    itemStyle: {
      borderColor: '#000'
    },
    label: {
      color: '#fff',
      fontSize: 40
    }
  }
});
option = {
  globe: {
    baseTexture: mapChart,
    heightTexture: /* Base64 data replaced — load from server */
'ROOT_PATH + '/data-gl/asset/world.topo.bathy.200401.jpg'',
    displacementScale: 0.1,
    shading: 'realistic',
    realisticMaterial: {
      roughness: 0.8,
      metalness: 0
    },
    postEffect: {
      enable: true
    },
    temporalSuperSampling: {
      enable: true
    },
    light: {
      ambient: {
        intensity: 0
      },
      main: {
        intensity: 2,
        shadow: true
      },
      ambientCubemap: {
        texture: /* Base64 data replaced — insert real URL here */
'PLACEHOLDER_URL',
        exposure: 1,
        diffuseIntensity: 0.2
      }
    },
    viewControl: {
      animationDurationUpdate: 1000,
      animationEasingUpdate: 'cubicInOut',
      targetCoord: [116.46, 39.92],
      autoRotate: false
    }
  },
  series: []
};
var regions = mapChart.getModel().getComponent('geo').coordinateSystem.regions;
setInterval(function () {
  var region = regions[Math.round(Math.random() * (regions.length - 1))];
  myChart.setOption({
    title: {
      left: 'center',
      top: 'center',
      text: region.name,
      textStyle: {
        fontSize: 40
      }
    },
    globe: {
      viewControl: {
        targetCoord: region.center
      }
    }
  });
  mapChart.setOption({
    geo: {
      regions: [
        {
          name: region.name,
          itemStyle: {
            normal: {
              areaColor: '#444'
            }
          }
        }
      ]
    }
  });
}, 2000);
```
