# matrix-mbti

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=matrix-mbti
**Chart Type:** `heatmap`

## User Data Requirements

Columns needed: need **x**, **y**, **value** columns

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
title: MBTI Partner Compatibility
category: matrix
titleCN: MBTI 伴侣相容性
difficulty: 11
since: 6.0.0
*/
// Click on the data to toggle grouping
const mbti = [
  'ENFJ',
  'ENFP',
  'ENTJ',
  'ENTP',
  'ESFJ',
  'ESFP',
  'ESTJ',
  'ESTP',
  'INFJ',
  'INFP',
  'INTJ',
  'INTP',
  'ISFJ',
  'ISFP',
  'ISTJ',
  'ISTP'
];
const color = {
  green: '#2D9A69',
  purple: '#7D568F',
  blue: '#3A8DAB',
  yellow: '#E0A433',
  greenLighter: '#10CA77',
  purpleLighter: '#9253AF',
  blueLighter: '#26A9D9',
  yellowLighter: '#F4AC24',
  greenDarker: '#0FB369',
  purpleDarker: '#854AA0',
  blueDarker: '#2298C3',
  yellowDarker: '#F2A30D'
};
const fontSize = {
  group: window.innerHeight > 700 ? 24 : 16,
  item: window.innerHeight > 700 ? 13 : 11,
  value: window.innerHeight > 700 ? 15 : 12
};
const getColor = (mbti, lightness = 0) => {
  if (mbti.indexOf('NF') >= 0) {
    return lightness < 0
      ? color.greenLighter
      : lightness > 0
      ? color.greenDarker
      : color.green;
  }
  if (mbti.indexOf('NT') >= 0) {
    return lightness < 0
      ? color.purpleLighter
      : lightness > 0
      ? color.purpleDarker
      : color.purple;
  }
  if (mbti.indexOf('S') >= 0 && mbti.indexOf('J') >= 0) {
    return lightness < 0
      ? color.blueLighter
      : lightness > 0
      ? color.blueDarker
      : color.blue;
  }
  if (mbti.indexOf('S') >= 0 && mbti.indexOf('P') >= 0) {
    return lightness < 0
      ? color.yellowLighter
      : lightness > 0
      ? color.yellowDarker
      : color.yellow;
  }
};
const generateGroup = (groupName) => {
  const colorMap = {
    NF: color.green,
    NT: color.purple,
    SJ: color.blue,
    SP: color.yellow
  };
  const groupMembers = {
    NF: ['INFJ', 'INFP', 'ENFJ', 'ENFP'],
    NT: ['INTJ', 'INTP', 'ENTJ', 'ENTP'],
    SJ: ['ISFJ', 'ISTJ', 'ESFJ', 'ESTJ'],
    SP: ['ISFP', 'ISTP', 'ESFP', 'ESTP']
  };
  return {
    value: groupName,
    label: {
      color: colorMap[groupName],
      fontSize: fontSize.group,
      fontWeight: 'bolder',
      padding: 0
    },
    children: groupMembers[groupName].map((mbti) => ({
      value: mbti,
      label: {
        color: colorMap[groupName],
        fontSize: fontSize.item,
        fontWeight: 'bold'
      }
    }))
  };
};
const xData = [
  generateGroup('NF'),
  generateGroup('NT'),
  generateGroup('SJ'),
  generateGroup('SP')
];
const yData = [
  generateGroup('NF'),
  generateGroup('NT'),
  generateGroup('SJ'),
  generateGroup('SP')
];
const originalData = [
  ['ENFJ', 'ENFJ', 0.86],
  ['ENFJ', 'ENFP', 0.91],
  ['ENFJ', 'ENTJ', 0.42],
  ['ENFJ', 'ENTP', 0.73],
  ['ENFJ', 'ESFJ', 0.64],
  ['ENFJ', 'ESFP', 0.8],
  ['ENFJ', 'ESTJ', 0.22],
  ['ENFJ', 'ESTP', 0.41],
  ['ENFJ', 'INFJ', 0.74],
  ['ENFJ', 'INFP', 0.73],
  ['ENFJ', 'INTJ', 0.16],
  ['ENFJ', 'INTP', 0.35],
  ['ENFJ', 'ISFJ', 0.3],
  ['ENFJ', 'ISFP', 0.4],
  ['ENFJ', 'ISTJ', 0.18],
  ['ENFJ', 'ISTP', 0.09],
  ['ENFP', 'ENFJ', 0.91],
  ['ENFP', 'ENFP', 0.97],
  ['ENFP', 'ENTJ', 0.37],
  ['ENFP', 'ENTP', 0.85],
  ['ENFP', 'ESFJ', 0.42],
  ['ENFP', 'ESFP', 0.93],
  ['ENFP', 'ESTJ', 0.27],
  ['ENFP', 'ESTP', 0.76],
  ['ENFP', 'INFJ', 0.51],
  ['ENFP', 'INFP', 0.73],
  ['ENFP', 'INTJ', 0.13],
  ['ENFP', 'INTP', 0.36],
  ['ENFP', 'ISFJ', 0.11],
  ['ENFP', 'ISFP', 0.49],
  ['ENFP', 'ISTJ', 0.04],
  ['ENFP', 'ISTP', 0.14],
  ['ENTJ', 'ENFJ', 0.42],
  ['ENTJ', 'ENFP', 0.37],
  ['ENTJ', 'ENTJ', 0.91],
  ['ENTJ', 'ENTP', 0.81],
  ['ENTJ', 'ESFJ', 0.53],
  ['ENTJ', 'ESFP', 0.51],
  ['ENTJ', 'ESTJ', 0.87],
  ['ENTJ', 'ESTP', 0.74],
  ['ENTJ', 'INFJ', 0.25],
  ['ENTJ', 'INFP', 0.13],
  ['ENTJ', 'INTJ', 0.46],
  ['ENTJ', 'INTP', 0.47],
  ['ENTJ', 'ISFJ', 0.29],
  ['ENTJ', 'ISFP', 0.06],
  ['ENTJ', 'ISTJ', 0.66],
  ['ENTJ', 'ISTP', 0.41],
  ['ENTP', 'ENFJ', 0.73],
  ['ENTP', 'ENFP', 0.64],
  ['ENTP', 'ENTJ', 0.81],
  ['ENTP', 'ENTP', 0.94],
  ['ENTP', 'ESFJ', 0.32],
  ['ENTP', 'ESFP', 0.87],
  ['ENTP', 'ESTJ', 0.7],
  ['ENTP', 'ESTP', 0.92],
  ['ENTP', 'INFJ', 0.11],
  ['ENTP', 'INFP', 0.35],
  ['ENTP', 'INTJ', 0.22],
  ['ENTP', 'INTP', 0.51],
  ['ENTP', 'ISFJ', 0.05],
  ['ENTP', 'ISFP', 0.14],
  ['ENTP', 'ISTJ', 0.11],
  ['ENTP', 'ISTP', 0.35],
  ['ESFJ', 'ESFJ', 0.94],
  ['ESFJ', 'ESFP', 0.4],
  ['ESFJ', 'ESTJ', 0.77],
  ['ESFJ', 'ESTP', 0.37],
  ['ESFJ', 'INFJ', 0.74],
  ['ESFJ', 'INFP', 0.17],
  ['ESFJ', 'INTJ', 0.32],
  ['ESFJ', 'INTP', 0.05],
  ['ESFJ', 'ISFJ', 0.79],
  ['ESFJ', 'ISFP', 0.57],
  ['ESFJ', 'ISTJ', 0.71],
  ['ESFJ', 'ISTP', 0.19],
  ['ESFP', 'ESFP', 0.7],
  ['ESFP', 'ESTJ', 0.39],
  ['ESFP', 'ESTP', 0.75],
  ['ESFP', 'INFJ', 0.43],
  ['ESFP', 'INFP', 0.58],
  ['ESFP', 'INTJ', 0.22],
  ['ESFP', 'INTP', 0.39],
  ['ESFP', 'ISFJ', 0.12],
  ['ESFP', 'ISFP', 0.58],
  ['ESFP', 'ISTJ', 0.08],
  ['ESFP', 'ISTP', 0.26],
  ['ESTJ', 'ESTJ', 0.96],
  ['ESTJ', 'ESTP', 0.78],
  ['ESTJ', 'INFJ', 0.14],
  ['ESTJ', 'INFP', 0.03],
  ['ESTJ', 'INTJ', 0.33],
  ['ESTJ', 'INTP', 0.22],
  ['ESTJ', 'ISFJ', 0.48],
  ['ESTJ', 'ISFP', 0.22],
  ['ESTJ', 'ISTJ', 0.79],
  ['ESTJ', 'ISTP', 0.55],
  ['ESTP', 'ESTP', 0.95],
  ['ESTP', 'INFJ', 0.05],
  ['ESTP', 'INFP', 0.24],
  ['ESTP', 'INTJ', 0.17],
  ['ESTP', 'INTP', 0.39],
  ['ESTP', 'ISFJ', 0.12],
  ['ESTP', 'ISFP', 0.43],
  ['ESTP', 'ISTJ', 0.2],
  ['ESTP', 'ISTP', 0.62],
  ['INFJ', 'INFJ', 0.95],
  ['INFJ', 'INFP', 0.85],
  ['INFJ', 'INTJ', 0.65],
  ['INFJ', 'INTP', 0.5],
  ['INFJ', 'ISFJ', 0.85],
  ['INFJ', 'ISFP', 0.58],
  ['INFJ', 'ISTJ', 0.53],
  ['INFJ', 'ISTP', 0.23],
  ['INFP', 'INFP', 0.97],
  ['INFP', 'INTJ', 0.7],
  ['INFP', 'INTP', 0.84],
  ['INFP', 'ISFJ', 0.46],
  ['INFP', 'ISFP', 0.78],
  ['INFP', 'ISTJ', 0.21],
  ['INFP', 'ISTP', 0.49],
  ['INTJ', 'INTJ', 0.86],
  ['INTJ', 'INTP', 0.89],
  ['INTJ', 'ISFJ', 0.79],
  ['INTJ', 'ISFP', 0.45],
  ['INTJ', 'ISTJ', 0.85],
  ['INTJ', 'ISTP', 0.78],
  ['INTP', 'INTP', 0.96],
  ['INTP', 'ISFJ', 0.38],
  ['INTP', 'ISFP', 0.43],
  ['INTP', 'ISTJ', 0.51],
  ['INTP', 'ISTP', 0.81],
  ['ISFJ', 'ISFJ', 0.95],
  ['ISFJ', 'ISFP', 0.76],
  ['ISFJ', 'ISTJ', 0.93],
  ['ISFJ', 'ISTP', 0.62],
  ['ISFP', 'ISFP', 0.97],
  ['ISFP', 'ISTJ', 0.47],
  ['ISFP', 'ISTP', 0.76],
  ['ISTJ', 'ISTJ', 0.96],
  ['ISTJ', 'ISTP', 0.78],
  ['ISTP', 'ISTP', 0.96]
];
const dataMap = new Map();
const avgData = {};
for (const [a, b, v] of originalData) {
  dataMap.set(`${a}-${b}`, v);
}
const heatmapData = [];
const scatterData = [];
const decalSize = 1;
for (const a of mbti) {
  for (const b of mbti) {
    const key = `${a}-${b}`;
    const altKey = `${b}-${a}`;
    let value;
    if (dataMap.has(key)) {
      value = [a, b, dataMap.get(key)];
    } else if (dataMap.has(altKey)) {
      value = [a, b, dataMap.get(altKey)];
    } else {
      value = [a, b, 0];
    }
    heatmapData.push({
      value,
      itemStyle: {
        decal: {
          shape: 'circle',
          symbolSize: 1,
          color: getColor(a, 1),
          backgroundColor: getColor(b, 1),
          dashArrayX: [
            [decalSize, decalSize],
            [0, decalSize, decalSize, 0]
          ],
          dashArrayY: [decalSize, 0]
        },
        borderColor: getColor(b),
        borderWidth: 0
      }
    });
    scatterData.push({
      value,
      label: {
        color: value[2] < 0.2 ? getColor(b) : '#fff',
        opacity: value[2] < 0.15 ? 0.6 : 1
      }
    });
  }
}
const size = Math.round(Math.min(window.innerWidth, window.innerHeight) * 0.9);
const fontFamily = 'Ubuntu Condensed, sans-serif';
const detailSeries = [
  {
    id: 'detail-heatmap',
    type: 'heatmap',
    coordinateSystem: 'matrix',
    data: heatmapData,
    label: {
      show: false
    },
    emphasis: {
      itemStyle: {
        borderWidth: 5
      }
    }
  },
  {
    id: 'detail-scatter',
    type: 'scatter',
    coordinateSystem: 'matrix',
    symbolSize: 0,
    data: scatterData,
    color: '#fff',
    label: {
      show: true,
      formatter: (params) => Math.round(params.value[2] * 100) + '%',
      fontWeight: 'bold',
      color: 'inherit'
    },
    silent: true
  }
];
const getGroup = (mbti) => {
  if (mbti.indexOf('NF') >= 0) {
    return 'NF';
  }
  if (mbti.indexOf('NT') >= 0) {
    return 'NT';
  }
  if (mbti[1] === 'S' && mbti[3] === 'J') {
    return 'SJ';
  }
  if (mbti[1] === 'S' && mbti[3] === 'P') {
    return 'SP';
  }
  return '';
};
const groupRawData = {};
for (let i = 0; i < originalData.length; ++i) {
  const [a, b, v] = originalData[i];
  const groupA = getGroup(a);
  const groupB = getGroup(b);
  const key = groupA > groupB ? `${groupA}-${groupB}` : `${groupB}-${groupA}`;
  if (groupRawData[key]) {
    groupRawData[key].push(v);
  } else {
    groupRawData[key] = [v];
  }
}
const groupData = [];
function median(arr) {
  const sorted = arr.slice().sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  if (sorted.length % 2 === 0) {
    return (sorted[mid - 1] + sorted[mid]) / 2;
  } else {
    return sorted[mid];
  }
}
for (const key in groupRawData) {
  if (groupRawData.hasOwnProperty(key)) {
    const [a, b] = key.split('-');
    const v = median(groupRawData[key]);
    const colorA = getColor(a, 1);
    const colorB = getColor(b, 1);
    const label = {
      color: v < 0.2 ? getColor(b) : '#fff',
      fontSize: fontSize.value,
      fontWeight: 'bold',
      opacity: v < 0.15 ? 0.6 : 1,
      formatter: (params) => {
        return `${Math.round(params.value[2] * 100)}%`;
      }
    };
    const decalSize = 3;
    const itemStyle = {
      decal: {
        shape: 'circle',
        symbolSize: 1,
        color: colorA,
        backgroundColor: colorB,
        dashArrayX: [
          [decalSize, decalSize],
          [0, decalSize, decalSize, 0]
        ],
        dashArrayY: [decalSize, 0]
      },
      borderColor: getColor(b),
      borderWidth: 0
    };
    groupData.push({
      value: [a, b, v],
      label,
      itemStyle
    });
    if (a !== b) {
      groupData.push({
        value: [b, a, v],
        label,
        itemStyle
      }); // Symmetric
    }
  }
}
const groupSeries = [
  {
    id: 'summary-heatmap',
    type: 'heatmap',
    coordinateSystem: 'matrix',
    data: groupData,
    label: {
      show: true
    }
  }
];
option = {
  backgroundColor: '#F0F7F9',
  textStyle: {
    fontFamily
  },
  title: {
    text: 'MBTI Partner Compatibility',
    subtext:
      'Data from: https://www.personalitydata.org/16-types/enfj-relationships#partner-matrix',
    sublink:
      'https://www.personalitydata.org/16-types/enfj-relationships#partner-matrix',
    left: 'center',
    top: 5,
    textStyle: {
      fontSize: 20,
      color: '#57576A'
    },
    itemGap: 5
  },
  tooltip: {
    formatter: (params) => {
      return `<span style="color:${getColor(
        params.value[1]
      )};font-weight:bold">${params.value[1]}</span> /
                            <span style="color:${getColor(
                              params.value[0]
                            )};font-weight:bold">${params.value[0]}</span> :
                            ${Math.round(params.value[2] * 100)}%`;
    },
    borderColor: '#eee',
    padding: [2, 8]
  },
  matrix: {
    x: {
      data: xData,
      itemStyle: {
        borderColor: 'transparent',
        borderWidth: 0
      },
      dividerLineStyle: {
        width: 0
      },
      label: {
        fontFamily
      },
      levels: [
        {
          levelSize: 25
        },
        {
          levelSize: 30
        }
      ]
    },
    y: {
      data: yData,
      itemStyle: {
        borderColor: 'transparent',
        borderWidth: 0
      },
      dividerLineStyle: {
        width: 0
      },
      label: {
        fontFamily
      }
    },
    body: {
      itemStyle: {
        borderWidth: 0
      },
      label: {
        fontFamily
      }
    },
    width: size,
    height: size,
    left: (window.innerWidth - size) / 2,
    top: 50,
    backgroundStyle: {
      color: 'transparent',
      borderColor: 'transparent',
      borderWidth: 0
    }
  },
  visualMap: [
    {
      type: 'continuous',
      min: 0,
      max: 1,
      dimension: 2,
      calculable: true,
      orient: 'horizontal',
      top: 5,
      left: 'center',
      inRange: {
        opacity: [0, 1]
      },
      seriesIndex: [0, 2],
      show: false
    }
  ],
  series: detailSeries,
  aria: {
    enabled: true,
    decal: {
      show: true
    }
  },
  animation: 0
};
let isGroup = false;
myChart.on('click', () => {
  isGroup = !isGroup;
  option.series = isGroup ? groupSeries : detailSeries;
  myChart.setOption(option, true);
});
```
