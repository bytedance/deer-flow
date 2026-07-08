# matrix-grid-layout

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=matrix-grid-layout
**Chart Type:** `time`

## User Data Requirements

Columns needed: check data arrays in reference code for required format

## Data Arrays — Complete Replacement Guide

**2 array(s)** to replace with real data:

### [0] `data` (context: root)
```
data: []
```

### [1] `data` (context: root)
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
title: Responsive grid layout based on matrix
category: matrix
titleCN: 矩阵中响应式网格布局
difficulty: 3
since: 6.0.0
*/
/**
 * Use a matrix coordinate system to layout multiple charts and components,
 * following the similar idea of CSS grid layout, and provide responsiveness
 * by media queries.
 */
let _idBase = 1;
const _mediaDefinitionList = [
  {
    // When the canvas width is less than 500px,
    query: { maxWidth: 500 },
    matrix: {
      // Define column and rows
      x: { data: Array(1).fill(null) },
      y: { data: Array(10).fill(null) }
    },
    // Place sections into the matrix cell determined by the coords.
    // key: sectionId, value: coord.
    sectionCoordMap: {
      section_title_1: [0, 0],
      section_header_1: [0, [1, 2]],
      section_sidebar_1: [0, [3, 4]],
      section_main_content_area_1: [0, [5, 7]],
      section_footer_1: [0, [8, 9]]
    }
  },
  {
    // The default (with no `query`)
    matrix: {
      // Define column and rows
      x: { data: Array(4).fill(null) },
      y: { data: Array(10).fill(null) }
    },
    sectionCoordMap: {
      section_title_1: [[0, 3], 0],
      section_header_1: [
        [0, 3],
        [1, 2]
      ],
      section_sidebar_1: [0, [3, 9]],
      section_main_content_area_1: [
        [1, 3],
        [3, 7]
      ],
      section_footer_1: [
        [1, 3],
        [8, 9]
      ]
    }
  }
];
/**
 * Each section contains some charts and components.
 */
const _sectionDefinitionMap = {
  section_title_1: {
    option: {
      title: [
        {
          coordinateSystem: 'matrix',
          text: 'Resize the Canvas to Check the Responsiveness',
          left: 'center',
          top: 10
        }
      ]
    }
  },
  section_header_1: {
    option: {
      title: [
        {
          coordinateSystem: 'matrix',
          text: 'Header Section',
          textStyle: { fontSize: 14 },
          left: 'center',
          top: 5
        }
      ],
      xAxis: {
        type: 'time',
        id: 'header_1',
        gridId: 'header_1'
      },
      yAxis: {
        id: 'header_1',
        gridId: 'header_1',
        splitNumber: 2,
        splitLine: { show: false }
      },
      grid: {
        id: 'header_1',
        coordinateSystem: 'matrix',
        tooltip: {
          trigger: 'axis'
        },
        top: 30,
        bottom: 10,
        left: 10,
        right: 10,
        outerBounds: {
          top: 30,
          left: 20,
          bottom: 20,
          right: 20
        }
      },
      series: {
        type: 'line',
        id: 'header_1',
        xAxisId: 'header_1',
        yAxisId: 'header_1',
        symbol: 'none',
        data: generateSingleSeriesData(100, false)
      }
    }
  },
  section_sidebar_1: {
    option: {
      title: {
        coordinateSystem: 'matrix',
        text: 'Sidebar Section',
        textStyle: { fontSize: 14 },
        left: 'center',
        top: 15
      },
      xAxis: {
        id: 'sidebar_1',
        gridId: 'sidebar_1',
        splitLine: { show: false },
        axisLabel: {
          hideOverlap: true
        }
      },
      yAxis: {
        type: 'time',
        id: 'sidebar_1',
        gridId: 'sidebar_1',
        axisLabel: {
          hideOverlap: true
        }
      },
      grid: {
        id: 'sidebar_1',
        coordinateSystem: 'matrix',
        tooltip: {
          trigger: 'axis'
        },
        top: 50,
        bottom: 30,
        left: 40,
        right: 30,
        outerBounds: {
          top: 30,
          left: 20,
          bottom: 20,
          right: 20
        }
      },
      series: {
        type: 'bar',
        id: 'sidebar_1',
        xAxisId: 'sidebar_1',
        yAxisId: 'sidebar_1',
        data: generateSingleSeriesData(10, true)
      }
    }
  },
  section_main_content_area_1: {
    option: {
      title: {
        text: 'Main Content Area',
        coordinateSystem: 'matrix',
        textStyle: { fontSize: 14 },
        left: 'center',
        top: 15
      },
      xAxis: {
        type: 'time',
        id: 'main_content_area_1',
        gridId: 'main_content_area_1'
      },
      yAxis: {
        id: 'main_content_area_1',
        gridId: 'main_content_area_1'
      },
      grid: {
        id: 'main_content_area_1',
        coordinateSystem: 'matrix',
        tooltip: {
          trigger: 'axis'
        },
        top: 50,
        bottom: 10,
        left: 10,
        right: 10,
        outerBounds: {
          top: 30,
          left: 20,
          bottom: 20,
          right: 20
        }
      },
      series: {
        type: 'line',
        id: 'main_content_area_1',
        xAxisId: 'main_content_area_1',
        yAxisId: 'main_content_area_1',
        symbol: 'none',
        data: generateSingleSeriesData(100, false)
      }
    }
  },
  section_footer_1: {
    option: {
      title: {
        coordinateSystem: 'matrix',
        text: 'Footer Section',
        textStyle: { fontSize: 14 },
        left: 'center',
        top: 15
      },
      xAxis: {
        type: 'time',
        id: 'footer_1',
        gridId: 'footer_1'
      },
      yAxis: {
        id: 'footer_1',
        gridId: 'footer_1',
        splitNumber: 2,
        splitLine: { show: false }
      },
      grid: {
        id: 'footer_1',
        coordinateSystem: 'matrix',
        tooltip: {
          trigger: 'axis'
        },
        top: 50,
        bottom: 10,
        left: 20,
        right: 20,
        outerBounds: {
          top: 30,
          left: 20,
          bottom: 20,
          right: 20
        }
      },
      series: {
        type: 'bar',
        id: 'footer_1',
        xAxisId: 'footer_1',
        yAxisId: 'footer_1',
        data: generateSingleSeriesData(10, false)
      }
    }
  }
};
option = {
  // Use the matrix coordinate system to layout the charts and components.
  matrix: {
    x: { show: false, data: [] },
    y: { show: false, data: [] },
    body: {
      itemStyle: { borderColor: 'none' }
    },
    backgroundStyle: { borderColor: 'none' },
    top: 0,
    bottom: 0,
    left: 0,
    right: 0
  },
  tooltip: {}
}; // End of option
initFloatingControlPanel();
assembleIntoEChartsOption(option, _sectionDefinitionMap, _mediaDefinitionList);
console.log(option);
/**
 * Merge those definitions into the single echarts option.
 * @param option The target echarts option to be written to.
 */
function assembleIntoEChartsOption(
  option,
  sectionDefinitionMap,
  mediaDefinitionList
) {
  option.media = mediaDefinitionList.map(({ query, matrix }) => {
    return { query, option: { matrix } };
  });
  Object.keys(sectionDefinitionMap).forEach((sectionId) => {
    const section = sectionDefinitionMap[sectionId];
    const optionIdMapWillSetCoord = {};
    Object.keys(section.option).forEach((componentMainType) => {
      option[componentMainType] = normalizeToArray(option[componentMainType]);
      normalizeToArray(section.option[componentMainType]).forEach(
        (component) => {
          component = ensureComponentId(
            component,
            sectionId,
            componentMainType
          );
          option[componentMainType].push(component);
          if (component.coordinateSystem === 'matrix') {
            optionIdMapWillSetCoord[componentMainType] = normalizeToArray(
              optionIdMapWillSetCoord[componentMainType]
            );
            optionIdMapWillSetCoord[componentMainType].push(component.id);
          }
        }
      );
    });
    mediaDefinitionList.forEach(
      ({ query, matrix, sectionCoordMap }, mediaIdx) => {
        const optionInMedia = option.media[mediaIdx].option;
        const coord = sectionCoordMap[sectionId];
        if (!coord) {
          throw new Error(
            `Section with id "${sectionId}" not found in media definition index ${mediaIdx}.`
          );
        }
        Object.keys(optionIdMapWillSetCoord).forEach((componentMainType) => {
          optionIdMapWillSetCoord[componentMainType].forEach((id) => {
            optionInMedia[componentMainType] = normalizeToArray(
              optionInMedia[componentMainType]
            );
            optionInMedia[componentMainType].push({
              id: id,
              coord: coord
            });
          });
        });
      }
    );
  });
}
/**
 * If no component id, generate one, and immutablely return a new component object.
 */
function ensureComponentId(component, sectionId, componentMainType) {
  if (component.id != null) {
    return component;
  }
  component = Object.assign({}, component);
  component.id = sectionId + '_' + componentMainType + '_' + _idBase++;
  return component;
}
/**
 * `{}` is converted to `[{}]`; null/undefined is converted to `[]`.
 */
function normalizeToArray(value) {
  return Array.isArray(value) ? value : value != null ? [value] : [];
}
/**
 * Generate some random data for a single series.
 */
function generateSingleSeriesData(dayCount, inverseXY) {
  const dayStart = new Date('2025-05-05T00:00:00.000Z'); // Monday
  const timeStart = dayStart.getTime();
  const sevenDay = 7 * 1000 * 3600 * 24;
  const seriesData = [];
  let lastVal = +(Math.random() * 300).toFixed(0);
  let turnCount = null;
  let sign = -1;
  for (let idx = 0; idx < dayCount; idx++) {
    if (turnCount == null || idx >= turnCount) {
      turnCount =
        idx + Math.round((dayCount / 4) * ((Math.random() - 0.5) * 0.1));
      sign = -sign;
    }
    const deltaMag = 50;
    const delta = +(
      Math.random() * deltaMag -
      deltaMag / 2 +
      (sign * deltaMag) / 3
    ).toFixed(0);
    const val = Math.max(0, (lastVal += delta));
    const xTime = timeStart + idx * sevenDay;
    const dataXVal = echarts.time.format(xTime, '{yyyy}-{MM}-{dd}');
    const item = [dataXVal, val];
    if (inverseXY) {
      item.reverse();
    }
    seriesData.push(item);
  }
  return seriesData;
}
/**
 * Note: The floating control panel are not relevant to echarts API,
 *  just for illustration purposes.
 */
function initFloatingControlPanel() {
  app.config = {};
  app.configParameters = {};
  app.config.showMatrixGrid = false;
  app.configParameters.showMatrixGrid = { options: [false, true] };
  app.config.onChange = function () {
    myChart.setOption({
      matrix: {
        body: {
          itemStyle: { borderColor: app.config.showMatrixGrid ? 'red' : 'none' }
        }
      }
    });
  };
}
```
