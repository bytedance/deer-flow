# bar3d-noise-modified-from-marpi-demo

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=bar3d-noise-modified-from-marpi-demo
**Chart Type:** `value`

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
title: Noise modified from marpi's demo
category: bar3D
titleCN: åºäº marpi ç¤ºä¾ä¿®æ¹çåªå£°ææ
*/
$.getScript(CDN_PATH + 'simplex-noise@2.4.0/simplex-noise.js').done(
  function () {
    var simplex = new SimplexNoise();
    var UPDATE_DURATION = 1000;
    function initVisualizer() {
      var config = {
        numWaves: 2,
        randomize: randomize,
        color1: '#000',
        color2: '#300',
        color3: '#fff',
        size: 150,
        roughness: 0.5,
        metalness: 0
      };
      //gui.add(config, "numWaves", 1, 3).name("Waves number").onChange(update).listen();
      for (var i = 0; i < 2; i++) {
        config['wave' + i + 'axis' + 'x'] = Math.random();
        config['wave' + i + 'axis' + 'y'] = Math.random();
        config['wave' + i + 'rounding'] = Math.random();
        config['wave' + i + 'square'] = Math.random();
      }
      function randomize() {
        //config.numWaves = Math.floor(Math.random() * 3) + 1;
        for (var i = 0; i < 2; i++) {
          config['wave' + i + 'axis' + 'x'] = Math.random();
          config['wave' + i + 'axis' + 'y'] = Math.random();
          config['wave' + i + 'rounding'] = Math.random();
          config['wave' + i + 'square'] = Math.random();
        }
        // Iterate over all controllers
        for (var i in gui.__controllers) {
          gui.__controllers[i].updateDisplay();
        }
        update();
      }
      function update() {
        var item = [];
        var dataProvider = [];
        var mod = 0.1;
        //config.numWaves = Math.round(config.numWaves)
        //var occurenceR = Math.random() * .02
        //var r = 0//Math.random()
        for (var s = 0; s < config.size * config.size; s++) {
          var x = s % config.size;
          var y = Math.floor(s / config.size);
          //if (Math.random() < occurenceR)
          //    r = Math.random()
          var output = 0;
          for (var i = 0; i < config.numWaves; i++) {
            var n = simplex.noise2D(
              i * 213 +
                (-50 + x) * mod * (1 - config['wave' + i + 'axis' + 'x']) * 0.5,
              i * 3124 +
                (-50 + y) * mod * (1 - config['wave' + i + 'axis' + 'y']) * 0.5
            );
            n = Math.pow(n, 1.95 - 1.9 * config['wave' + i + 'rounding']);
            var square = Math.floor(
              (1.1 - config['wave' + i + 'square']) * 100
            );
            n = Math.round(n * square) / square;
            //output*=n
            if (output < n) output = n;
          }
          dataProvider.push([x, y, (output + 0.1) * 2]);
        }
        myChart.setOption({
          visualMap: {
            inRange: {
              barSize: 100 / config.size,
              color: [config.color1, config.color2, config.color3]
            }
          },
          series: [
            {
              data: dataProvider,
              realisticMaterial: {
                roughness: config.roughness,
                metalness: config.metalness
              }
            }
          ]
        });
        //setTimeout(update, UPDATE_DURATION);
      }
      update();
    }
    var focalRange = 40;
    var blurRadius = 4;
    myChart.setOption(
      (option = {
        toolbox: {
          left: 20,
          iconStyle: {
            normal: {
              borderColor: '#fff'
            }
          }
        },
        tooltip: {},
        visualMap: {
          show: false,
          min: 0.1,
          max: 2.5,
          inRange: {
            color: ['#000', '#300', '#fff']
          }
        },
        xAxis3D: {
          type: 'value'
        },
        yAxis3D: {
          type: 'value'
        },
        zAxis3D: {
          type: 'value',
          min: -6,
          max: 6
        },
        grid3D: {
          show: false,
          environment: '#000',
          viewControl: {
            distance: 100,
            maxDistance: 150,
            minDistance: 50,
            alpha: 38,
            beta: 220,
            minAlpha: 10
            //maxBeta: 360,
          },
          postEffect: {
            enable: true,
            SSAO: {
              enable: true,
              intensity: 1.3,
              radius: 5
            },
            screenSpaceReflection: {
              enable: false
            },
            depthOfField: {
              enable: true,
              blurRadius: blurRadius,
              focalRange: focalRange,
              focalDistance: 70
            }
          },
          light: {
            main: {
              intensity: 1,
              shadow: true,
              shadowQuality: 'high',
              alpha: 30
            },
            ambient: {
              intensity: 0
            },
            ambientCubemap: {
              texture: /* Base64 data replaced — insert real URL here */
'PLACEHOLDER_URL',
              exposure: 2,
              diffuseIntensity: 1,
              specularIntensity: 1
            }
          }
        },
        series: [
          {
            type: 'bar3D',
            silent: true,
            shading: 'realistic',
            realisticMaterial: {
              roughness: 0.5,
              metalness: 0
            },
            instancing: true,
            barSize: 0.6,
            data: [],
            lineStyle: {
              width: 4
            },
            itemStyle: {
              color: '#fff'
            },
            animation: false,
            animationDurationUpdate: UPDATE_DURATION
          }
        ]
      })
    );
    setTimeout(function () {
      initVisualizer();
    });
  }
);
```
