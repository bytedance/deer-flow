# pictorialBar-forest

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=pictorialBar-forest
**Chart Type:** `pictorialBar`

## User Data Requirements

Columns needed: check data arrays in reference code for required format

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
title: Expansion of forest
category: pictorialBar
titleCN: 森林的增长
videoStart: 4000
videoEnd: 10000
*/
const treeDataURI =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABwAAAA2CAYAAADUOvnEAAAACXBIWXMAAAsTAAALEwEAmpwYAAAAGXRFWHRTb2Z0d2FyZQBBZG9iZSBJbWFnZVJlYWR5ccllPAAAA5tJREFUeNrcWE1oE0EUnp0kbWyUpCiNYEpCFSpIMdpLRTD15s2ePHixnj00N4/GoyfTg2fbiwdvvagHC1UQ66GQUIQKKgn1UAqSSFua38b3prPJZDs7s5ufKn0w7CaZ2W/fe9/73kyMRqNB3Nrj1zdn4RJ6du9T2u1a2iHYSxjP4d41oOHGQwAIwSUHIyh8/RA8XeiXh0kLGFoaXiTecw/hoTG4ZCSAaFkY0+BpsZceLtiAoV2FkepZSDk5EpppczBvpuuQCqx0YnkYcVVoqQYMyeCG+lFdaGkXeVOFNu4aEBalOBk6sbQrQF7gSdK5JXjuHXuYVIVyr0TZ0FjKDeCs6km7JYMUdrWAUVmZUBtmRnVPK+x6nIR2xomH06R35ggwJPeofWphr/W5UjPIxq8B2bKgE8C4HVHWvg+2gZjXj19PkdFztY7bk9TDCH/g6oafDPpaoMvZIRI5WyMB/0Hv++HkpTKE0kM+A+h20cPAfN4GuRyp9G+LMTW+z8rCLI8b46XO9zRcYZTde/j0AZm8WGb3Y2F9KLlE2nqYkjFLJAsDOl/lea0q55mqxXcL7YBc++bsCPMe8mUyU2ZIpnCoblca6TZA/ga2Co8PGg7UGUlEDd0ueptglbrRZLLE7poti6pCaWUo2pu1oaYI1CF9b9cCZPO3F8ikJQ/rPpQT5YETht26ss+uCIL2Y8vHwJGpA96GI5mjOlaKhowUy6BcNcgIhDviTGWCGFaqEuufWz4pgcbCh+w0gEOyOjTlTtYYlIWPYWKEsLDzOs+nhzaO1KEpd+MXpOoTUgKiNyhdy5aSMPNVqxtSsJFgza5EWA4zKtCJ2OGbLn0JSLu8+SL4G86p1Fpr7ABXdGFF/UTD4rfmFYFw4G9VAJ9SM3aF8l3yok4/J6IV9sDVb36ynmtJ2M5+CwxTYBdKNMBaocKGV2nYgkz6r+cHBP30MzAfi4Sy+BebSoPIOi8PW1PpCCvr/KOD4k9Zu0WSH0Y0+SxJ2awp/nlwKtcGyHOJ8vNHtRJzhPlsHr8MogtlVtwUU0tSM1x58upSKbfJnSKUR07GVMKkDNfXpzpv0RTHy3nZMVx5IOWdZIaPabGFvfpwpjnvfmJHXLaEvZUTseu/TeLc+xgAPhEAb/PbjO6PBaOTf6LQRh/dERde23zxLtOXbaKNhfq2L/1fAOPHDUhOpIf5485h7l+GNHHiSYPKE3Myz9sFxoJuAyazvwIMAItferha5LTqAAAAAElFTkSuQmCC';
const beginYear = 2016;
const endYear = 2050;
const lineCount = 10;
// Basic option:
option = {
  color: ['#e54035'],
  xAxis: {
    axisLine: { show: false },
    axisLabel: { show: false },
    axisTick: { show: false },
    splitLine: { show: false },
    name: beginYear + '',
    nameLocation: 'middle',
    nameGap: 40,
    nameTextStyle: {
      color: 'green',
      fontSize: 30,
      fontFamily: 'Arial'
    },
    min: -2800,
    max: 2800
  },
  yAxis: {
    data: makeCategoryData(),
    show: false
  },
  grid: {
    top: 'center',
    height: 280
  },
  series: [
    {
      name: 'all',
      type: 'pictorialBar',
      symbol: 'image://' + treeDataURI,
      symbolSize: [30, 55],
      symbolRepeat: true,
      data: makeSeriesData(beginYear),
      animationEasing: 'elasticOut'
    },
    {
      name: 'all',
      type: 'pictorialBar',
      symbol: 'image://' + treeDataURI,
      symbolSize: [30, 55],
      symbolRepeat: true,
      data: makeSeriesData(beginYear, true),
      animationEasing: 'elasticOut'
    }
  ]
};
// Make fake data.
function makeCategoryData() {
  var categoryData = [];
  for (var i = 0; i < lineCount; i++) {
    categoryData.push(i + 'a');
  }
  return categoryData;
}
function makeSeriesData(year, negative) {
  // make a fake value just for demo.
  const r = (year - beginYear + 1) * 10;
  const seriesData = [];
  for (let i = 0; i < lineCount; i++) {
    let sign = negative ? -1 * (i % 3 ? 0.9 : 1) : 1 * ((i + 1) % 3 ? 0.9 : 1);
    seriesData.push({
      value:
        sign *
        (year <= beginYear + 1
          ? Math.abs(i - lineCount / 2 + 0.5) < lineCount / 5
            ? 5
            : 0
          : (lineCount - Math.abs(i - lineCount / 2 + 0.5)) * r),
      symbolOffset: i % 2 ? ['50%', 0] : undefined
    });
  }
  return seriesData;
}
// Set dynamic data.
var currentYear = beginYear;
setInterval(function () {
  currentYear++;
  if (currentYear > endYear) {
    currentYear = beginYear;
  }
  myChart.setOption({
    xAxis: {
      name: currentYear
    },
    series: [
      {
        data: makeSeriesData(currentYear)
      },
      {
        data: makeSeriesData(currentYear, true)
      }
    ]
  });
}, 800);
```
