# wind-barb

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=wind-barb
**Chart Type:** `path`

## User Data Requirements

Columns needed: check data arrays in reference code for required format

## Data Arrays — Complete Replacement Guide

**2 array(s)** to replace with real data:

### [0] `pieces` (context: visualMap)
```
pieces: [
          {
            gte: 17,
            color: '#18BF12',
            label: '大风（>=17节）'
          },
          {
            gte: 11,
...
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
title: Wind Barb
category: 'custom, dataZoom'
titleCN: 风向图
difficulty: 5
*/
var rawData = {
  "data": [
    {
      "time": "2017-06-27T11:00:00.000Z",
      "windSpeed": 9,
      "R": "NNW",
      "waveHeight": 2.64
    },
    {
      "time": "2017-06-27T12:30:00.000Z",
      "windSpeed": 10,
      "R": "NNW",
      "waveHeight": 2.57
    },
    {
      "time": "2017-06-27T14:00:00.000Z",
      "windSpeed": 12,
      "R": "NNW",
      "waveHeight": 2.49
    },
    {
      "time": "2017-06-27T15:30:00.000Z",
      "windSpeed": 12,
      "R": "NNW",
      "waveHeight": 2.44
    },
    {
      "time": "2017-06-27T17:00:00.000Z",
      "windSpeed": 11,
      "R": "NNW",
      "waveHeight": 2.38
    },
    {
      "time": "2017-06-27T18:30:00.000Z",
      "windSpeed": 10,
      "R": "NNW",
      "waveHeight": 2.34
    },
    {
      "time": "2017-06-27T20:00:00.000Z",
      "windSpeed": 10,
      "R": "N",
      "waveHeight": 2.3
    },
    {
      "time": "2017-06-27T21:30:00.000Z",
      "windSpeed": 11,
      "R": "NNW",
      "waveHeight": 2.26
    },
    {
      "time": "2017-06-27T23:00:00.000Z",
      "windSpeed": 12,
      "R": "NNW",
      "waveHeight": 2.22
    },
    {
      "time": "2017-06-28T00:30:00.000Z",
      "windSpeed": 12,
      "R": "N",
      "waveHeight": 2.18
    },
    {
      "time": "2017-06-28T02:00:00.000Z",
      "windSpeed": 12,
      "R": "N",
      "waveHeight": 2.13
    },
    {
      "time": "2017-06-28T03:30:00.000Z",
      "windSpeed": 12,
      "R": "N",
      "waveHeight": 2.09
    },
    {
      "time": "2017-06-28T05:00:00.000Z",
      "windSpeed": 12,
      "R": "NNE",
      "waveHeight": 2.04
    },
    {
      "time": "2017-06-28T06:30:00.000Z",
      "windSpeed": 10,
      "R": "N",
      "waveHeight": 2.01
    },
    {
      "time": "2017-06-28T08:00:00.000Z",
      "windSpeed": 9,
      "R": "N",
      "waveHeight": 1.99
    },
    {
      "time": "2017-06-28T09:30:00.000Z",
      "windSpeed": 8,
      "R": "NNW",
      "waveHeight": 2
    },
    {
      "time": "2017-06-28T11:00:00.000Z",
      "windSpeed": 8,
      "R": "NW",
      "waveHeight": 2.01
    },
    {
      "time": "2017-06-28T12:30:00.000Z",
      "windSpeed": 8,
      "R": "NW",
      "waveHeight": 2.06
    },
    {
      "time": "2017-06-28T14:00:00.000Z",
      "windSpeed": 9,
      "R": "WNW",
      "waveHeight": 2.12
    },
    {
      "time": "2017-06-28T15:30:00.000Z",
      "windSpeed": 10,
      "R": "WNW",
      "waveHeight": 2.19
    },
    {
      "time": "2017-06-28T17:00:00.000Z",
      "windSpeed": 11,
      "R": "WNW",
      "waveHeight": 2.27
    },
    {
      "time": "2017-06-28T18:30:00.000Z",
      "windSpeed": 12,
      "R": "WNW",
      "waveHeight": 2.33
    },
    {
      "time": "2017-06-28T20:00:00.000Z",
      "windSpeed": 13,
      "R": "NW",
      "waveHeight": 2.39
    },
    {
      "time": "2017-06-28T21:30:00.000Z",
      "windSpeed": 13,
      "R": "NW",
      "waveHeight": 2.43
    },
    {
      "time": "2017-06-28T23:00:00.000Z",
      "windSpeed": 14,
      "R": "NW",
      "waveHeight": 2.46
    },
    {
      "time": "2017-06-29T00:30:00.000Z",
      "windSpeed": 16,
      "R": "NW",
      "waveHeight": 2.48
    },
    {
      "time": "2017-06-29T02:00:00.000Z",
      "windSpeed": 18,
      "R": "NNW",
      "waveHeight": 2.49
    },
    {
      "time": "2017-06-29T03:30:00.000Z",
      "windSpeed": 20,
      "R": "WNW",
      "waveHeight": 2.53
    },
    {
      "time": "2017-06-29T05:00:00.000Z",
      "windSpeed": 22,
      "R": "W",
      "waveHeight": 2.58
    },
    {
      "time": "2017-06-29T06:30:00.000Z",
      "windSpeed": 26,
      "R": "WSW",
      "waveHeight": 2.89
    },
    {
      "time": "2017-06-29T08:00:00.000Z",
      "windSpeed": 30,
      "R": "WSW",
      "waveHeight": 3.21
    },
    {
      "time": "2017-06-29T09:30:00.000Z",
      "windSpeed": 30,
      "R": "SW",
      "waveHeight": 3.58
    },
    {
      "time": "2017-06-29T11:00:00.000Z",
      "windSpeed": 29,
      "R": "SW",
      "waveHeight": 3.94
    },
    {
      "time": "2017-06-29T12:30:00.000Z",
      "windSpeed": 29,
      "R": "SW",
      "waveHeight": 4.08
    },
    {
      "time": "2017-06-29T14:00:00.000Z",
      "windSpeed": 29,
      "R": "SW",
      "waveHeight": 4.22
    },
    {
      "time": "2017-06-29T15:30:00.000Z",
      "windSpeed": 28,
      "R": "SW",
      "waveHeight": 4.25
    },
    {
      "time": "2017-06-29T17:00:00.000Z",
      "windSpeed": 28,
      "R": "SW",
      "waveHeight": 4.28
    },
    {
      "time": "2017-06-29T18:30:00.000Z",
      "windSpeed": 29,
      "R": "SSW",
      "waveHeight": 4.37
    },
    {
      "time": "2017-06-29T20:00:00.000Z",
      "windSpeed": 30,
      "R": "SSW",
      "waveHeight": 4.45
    },
    {
      "time": "2017-06-29T21:30:00.000Z",
      "windSpeed": 29,
      "R": "SSW",
      "waveHeight": 4.45
    },
    {
      "time": "2017-06-29T23:00:00.000Z",
      "windSpeed": 27,
      "R": "SSW",
      "waveHeight": 4.45
    },
    {
      "time": "2017-06-30T00:30:00.000Z",
      "windSpeed": 26,
      "R": "SSW",
      "waveHeight": 4.32
    },
    {
      "time": "2017-06-30T02:00:00.000Z",
      "windSpeed": 25,
      "R": "SSW",
      "waveHeight": 4.2
    },
    {
      "time": "2017-06-30T03:30:00.000Z",
      "windSpeed": 22,
      "R": "SSW",
      "waveHeight": 4.01
    },
    {
      "time": "2017-06-30T05:00:00.000Z",
      "windSpeed": 20,
      "R": "SSW",
      "waveHeight": 3.82
    },
    {
      "time": "2017-06-30T06:30:00.000Z",
      "windSpeed": 19,
      "R": "SSW",
      "waveHeight": 3.66
    },
    {
      "time": "2017-06-30T08:00:00.000Z",
      "windSpeed": 19,
      "R": "SSW",
      "waveHeight": 3.51
    },
    {
      "time": "2017-06-30T09:30:00.000Z",
      "windSpeed": 17,
      "R": "SSW",
      "waveHeight": 3.37
    },
    {
      "time": "2017-06-30T11:00:00.000Z",
      "windSpeed": 14,
      "R": "SSW",
      "waveHeight": 3.22
    },
    {
      "time": "2017-06-30T12:30:00.000Z",
      "windSpeed": 12,
      "R": "SSW",
      "waveHeight": 3.09
    },
    {
      "time": "2017-06-30T14:00:00.000Z",
      "windSpeed": 10,
      "R": "SW",
      "waveHeight": 2.96
    },
    {
      "time": "2017-06-30T15:30:00.000Z",
      "windSpeed": 9,
      "R": "WSW",
      "waveHeight": 2.83
    },
    {
      "time": "2017-06-30T17:00:00.000Z",
      "windSpeed": 9,
      "R": "W",
      "waveHeight": 2.7
    },
    {
      "time": "2017-06-30T18:30:00.000Z",
      "windSpeed": 10,
      "R": "W",
      "waveHeight": 2.58
    },
    {
      "time": "2017-06-30T20:00:00.000Z",
      "windSpeed": 10,
      "R": "WNW",
      "waveHeight": 2.45
    },
    {
      "time": "2017-06-30T21:30:00.000Z",
      "windSpeed": 10,
      "R": "WNW",
      "waveHeight": 2.33
    },
    {
      "time": "2017-06-30T23:00:00.000Z",
      "windSpeed": 10,
      "R": "WNW",
      "waveHeight": 2.21
    },
    {
      "time": "2017-07-01T00:30:00.000Z",
      "windSpeed": 10,
      "R": "NW",
      "waveHeight": 2.13
    },
    {
      "time": "2017-07-01T02:00:00.000Z",
      "windSpeed": 10,
      "R": "NW",
      "waveHeight": 2.05
    },
    {
      "time": "2017-07-01T03:30:00.000Z",
      "windSpeed": 10,
      "R": "NNW",
      "waveHeight": 2.02
    },
    {
      "time": "2017-07-01T05:00:00.000Z",
      "windSpeed": 10,
      "R": "N",
      "waveHeight": 2
    },
    {
      "time": "2017-07-01T06:30:00.000Z",
      "windSpeed": 10,
      "R": "N",
      "waveHeight": 2
    },
    {
      "time": "2017-07-01T08:00:00.000Z",
      "windSpeed": 10,
      "R": "N",
      "waveHeight": 1.99
    },
    {
      "time": "2017-07-01T09:30:00.000Z",
      "windSpeed": 10,
      "R": "N",
      "waveHeight": 1.98
    },
    {
      "time": "2017-07-01T11:00:00.000Z",
      "windSpeed": 10,
      "R": "N",
      "waveHeight": 1.96
    },
    {
      "time": "2017-07-01T12:30:00.000Z",
      "windSpeed": 10,
      "R": "N",
      "waveHeight": 1.94
    },
    {
      "time": "2017-07-01T14:00:00.000Z",
      "windSpeed": 11,
      "R": "N",
      "waveHeight": 1.93
    },
    {
      "time": "2017-07-01T15:30:00.000Z",
      "windSpeed": 11,
      "R": "N",
      "waveHeight": 1.93
    },
    {
      "time": "2017-07-01T17:00:00.000Z",
      "windSpeed": 11,
      "R": "NNW",
      "waveHeight": 1.93
    },
    {
      "time": "2017-07-01T18:30:00.000Z",
      "windSpeed": 10,
      "R": "NNW",
      "waveHeight": 1.94
    },
    {
      "time": "2017-07-01T20:00:00.000Z",
      "windSpeed": 10,
      "R": "NNW",
      "waveHeight": 1.96
    },
    {
      "time": "2017-07-01T21:30:00.000Z",
      "windSpeed": 10,
      "R": "NNW",
      "waveHeight": 1.97
    },
    {
      "time": "2017-07-01T23:00:00.000Z",
      "windSpeed": 10,
      "R": "NNW",
      "waveHeight": 1.97
    },
    {
      "time": "2017-07-02T00:30:00.000Z",
      "windSpeed": 10,
      "R": "N",
      "waveHeight": 1.96
    },
    {
      "time": "2017-07-02T02:00:00.000Z",
      "windSpeed": 11,
      "R": "N",
      "waveHeight": 1.94
    },
    {
      "time": "2017-07-02T03:30:00.000Z",
      "windSpeed": 11,
      "R": "N",
      "waveHeight": 1.91
    },
    {
      "time": "2017-07-02T05:00:00.000Z",
      "windSpeed": 10,
      "R": "N",
      "waveHeight": 1.88
    },
    {
      "time": "2017-07-02T06:30:00.000Z",
      "windSpeed": 10,
      "R": "N",
      "waveHeight": 1.84
    },
    {
      "time": "2017-07-02T08:00:00.000Z",
      "windSpeed": 10,
      "R": "N",
      "waveHeight": 1.8
    },
    {
      "time": "2017-07-02T09:30:00.000Z",
      "windSpeed": 11,
      "R": "N",
      "waveHeight": 1.78
    },
    {
      "time": "2017-07-02T11:00:00.000Z",
      "windSpeed": 11,
      "R": "N",
      "waveHeight": 1.76
    },
    {
      "time": "2017-07-02T12:30:00.000Z",
      "windSpeed": 12,
      "R": "N",
      "waveHeight": 1.76
    },
    {
      "time": "2017-07-02T14:00:00.000Z",
      "windSpeed": 13,
      "R": "N",
      "waveHeight": 1.77
    },
    {
      "time": "2017-07-02T15:30:00.000Z",
      "windSpeed": 14,
      "R": "N",
      "waveHeight": 1.81
    },
    {
      "time": "2017-07-02T17:00:00.000Z",
      "windSpeed": 15,
      "R": "N",
      "waveHeight": 1.85
    },
    {
      "time": "2017-07-02T18:30:00.000Z",
      "windSpeed": 14,
      "R": "N",
      "waveHeight": 1.86
    },
    {
      "time": "2017-07-02T20:00:00.000Z",
      "windSpeed": 13,
      "R": "N",
      "waveHeight": 1.87
    },
    {
      "time": "2017-07-02T21:30:00.000Z",
      "windSpeed": 13,
      "R": "N",
      "waveHeight": 1.88
    },
    {
      "time": "2017-07-02T23:00:00.000Z",
      "windSpeed": 13,
      "R": "N",
      "waveHeight": 1.9
    },
    {
      "time": "2017-07-03T00:30:00.000Z",
      "windSpeed": 13,
      "R": "N",
      "waveHeight": 1.91
    },
    {
      "time": "2017-07-03T02:00:00.000Z",
      "windSpeed": 13,
      "R": "N",
      "waveHeight": 1.93
    },
    {
      "time": "2017-07-03T03:30:00.000Z",
      "windSpeed": 13,
      "R": "N",
      "waveHeight": 1.96
    },
    {
      "time": "2017-07-03T05:00:00.000Z",
      "windSpeed": 13,
      "R": "NNE",
      "waveHeight": 1.99
    },
    {
      "time": "2017-07-03T06:30:00.000Z",
      "windSpeed": 12,
      "R": "NNE",
      "waveHeight": 2.03
    },
    {
      "time": "2017-07-03T08:00:00.000Z",
      "windSpeed": 11,
      "R": "NNE",
      "waveHeight": 2.08
    },
    {
      "time": "2017-07-03T09:30:00.000Z",
      "windSpeed": 11,
      "R": "N",
      "waveHeight": 2.12
    },
    {
      "time": "2017-07-03T11:00:00.000Z",
      "windSpeed": 11,
      "R": "NNW",
      "waveHeight": 2.16
    },
    {
      "time": "2017-07-03T12:30:00.000Z",
      "windSpeed": 15,
      "R": "N",
      "waveHeight": 2.22
    },
    {
      "time": "2017-07-03T14:00:00.000Z",
      "windSpeed": 20,
      "R": "N",
      "waveHeight": 2.27
    },
    {
      "time": "2017-07-03T15:30:00.000Z",
      "windSpeed": 20,
      "R": "N",
      "waveHeight": 2.33
    },
    {
      "time": "2017-07-03T17:00:00.000Z",
      "windSpeed": 19,
      "R": "N",
      "waveHeight": 2.39
    },
    {
      "time": "2017-07-03T18:30:00.000Z",
      "windSpeed": 17,
      "R": "N",
      "waveHeight": 2.44
    },
    {
      "time": "2017-07-03T20:00:00.000Z",
      "windSpeed": 15,
      "R": "N",
      "waveHeight": 2.49
    },
    {
      "time": "2017-07-03T21:30:00.000Z",
      "windSpeed": 16,
      "R": "NNW",
      "waveHeight": 2.49
    },
    {
      "time": "2017-07-03T23:00:00.000Z",
      "windSpeed": 17,
      "R": "WNW",
      "waveHeight": 2.49
    },
    {
      "time": "2017-07-04T00:30:00.000Z",
      "windSpeed": 18,
      "R": "W",
      "waveHeight": 2.47
    },
    {
      "time": "2017-07-04T02:00:00.000Z",
      "windSpeed": 20,
      "R": "SW",
      "waveHeight": 2.44
    },
    {
      "time": "2017-07-04T03:30:00.000Z",
      "windSpeed": 21,
      "R": "SW",
      "waveHeight": 2.5
    },
    {
      "time": "2017-07-04T05:00:00.000Z",
      "windSpeed": 21,
      "R": "WSW",
      "waveHeight": 2.56
    },
    {
      "time": "2017-07-04T06:30:00.000Z",
      "windSpeed": 22,
      "R": "WSW",
      "waveHeight": 2.69
    },
    {
      "time": "2017-07-04T08:00:00.000Z",
      "windSpeed": 22,
      "R": "WSW",
      "waveHeight": 2.83
    },
    {
      "time": "2017-07-04T09:30:00.000Z",
      "windSpeed": 23,
      "R": "WSW",
      "waveHeight": 2.94
    },
    {
      "time": "2017-07-04T11:00:00.000Z",
      "windSpeed": 23,
      "R": "WSW",
      "waveHeight": 3.06
    },
    {
      "time": "2017-07-04T12:30:00.000Z",
      "windSpeed": 24,
      "R": "WSW",
      "waveHeight": 3.06
    },
    {
      "time": "2017-07-04T14:00:00.000Z",
      "windSpeed": 24,
      "R": "SW",
      "waveHeight": 3.06
    },
    {
      "time": "2017-07-04T15:30:00.000Z",
      "windSpeed": 25,
      "R": "SW",
      "waveHeight": 3.04
    },
    {
      "time": "2017-07-04T17:00:00.000Z",
      "windSpeed": 25,
      "R": "SW",
      "waveHeight": 3.03
    },
    {
      "time": "2017-07-04T18:30:00.000Z",
      "windSpeed": 26,
      "R": "SW",
      "waveHeight": 3
    },
    {
      "time": "2017-07-04T20:00:00.000Z",
      "windSpeed": 26,
      "R": "SW",
      "waveHeight": 2.97
    }
  ],
  "title": "HOBART",
  "forecast": [
    {
      "localDate": "2017-06-28",
      "day": "Wednesday",
      "minTemp": 4,
      "maxTemp": 13,
      "shortDesc": "Partly cloudy.",
      "skyIcon": "Cloudy",
      "weatherIcon": "MostlySunnyPartlyCloudy",
      "probabilityPrecip": 0,
      "rangePrecipText": "0 to 1 mm",
      "sunrise": "768",
      "sunset": "1673",
      "moonPhase": 0.682,
      "tides": "4,6,18,0.3,L,13,5,1.26,H,18,24,0.94,L,23,57,1.41,H"
    },
    {
      "localDate": "2017-06-29",
      "day": "Thursday",
      "minTemp": 5,
      "maxTemp": 11,
      "shortDesc": "Showers.",
      "skyIcon": "Showers",
      "weatherIcon": "Shower",
      "probabilityPrecip": 70,
      "rangePrecipText": "0 to 1 mm",
      "sunrise": "768",
      "sunset": "1673",
      "moonPhase": 0.901,
      "tides": "4,7,11,0.38,L,13,52,1.29,H,19,32,0.89,L"
    },
    {
      "localDate": "2017-06-30",
      "day": "Friday",
      "minTemp": 3,
      "maxTemp": 11,
      "shortDesc": "Shower or two.",
      "skyIcon": "Showers",
      "weatherIcon": "Shower",
      "probabilityPrecip": 70,
      "rangePrecipText": "0 to 1 mm",
      "sunrise": "768",
      "sunset": "1675",
      "moonPhase": 1.112,
      "tides": "4,1,0,1.3,H,8,0,0.48,L,14,34,1.31,H,20,41,0.84,L"
    },
    {
      "localDate": "2017-07-01",
      "day": "Saturday",
      "minTemp": 1,
      "maxTemp": 11,
      "shortDesc": "Mostly sunny.",
      "skyIcon": "Sunny",
      "weatherIcon": "MostlySunnyPartlyCloudy",
      "probabilityPrecip": 0,
      "rangePrecipText": "",
      "sunrise": "768",
      "sunset": "1675",
      "moonPhase": 1.315,
      "tides": "4,2,3,1.19,H,8,42,0.58,L,15,13,1.33,H,21,47,0.79,L"
    },
    {
      "localDate": "2017-07-02",
      "day": "Sunday",
      "minTemp": 2,
      "maxTemp": 13,
      "shortDesc": "Mostly sunny.",
      "skyIcon": "Sunny",
      "weatherIcon": "MostlySunnyPartlyCloudy",
      "probabilityPrecip": 0,
      "rangePrecipText": "",
      "sunrise": "768",
      "sunset": "1676",
      "moonPhase": 1.513,
      "tides": "4,3,8,1.1,H,9,16,0.67,L,15,48,1.35,H,22,49,0.74,L"
    },
    {
      "localDate": "2017-07-03",
      "day": "Monday",
      "minTemp": 3,
      "maxTemp": 12,
      "shortDesc": "Mostly sunny.",
      "skyIcon": "Sunny",
      "weatherIcon": "MostlySunnyPartlyCloudy",
      "probabilityPrecip": 20,
      "rangePrecipText": "0 to 1 mm",
      "sunrise": "768",
      "sunset": "1676",
      "moonPhase": 1.898,
      "tides": "4,4,15,1.03,H,9,43,0.75,L,16,20,1.37,H,23,41,0.69,L"
    },
    {
      "localDate": "2017-07-04",
      "day": "Tuesday",
      "minTemp": 5,
      "maxTemp": 12,
      "shortDesc": "Shower or two.",
      "skyIcon": "Showers",
      "weatherIcon": "Shower",
      "probabilityPrecip": 50,
      "rangePrecipText": "0 to 2 mm",
      "sunrise": "768",
      "sunset": "1678",
      "moonPhase": 2.088,
      "tides": "4,5,19,1,H,10,0,0.81,L,16,51,1.39,H"
    }
  ]
};
const weatherIcons = {
      Showers: /* Base64 data replaced — insert real URL here */
'PLACEHOLDER_URL',
      Sunny: /* Base64 data replaced — insert real URL here */
'PLACEHOLDER_URL',
      Cloudy: /* Base64 data replaced — insert real URL here */
'PLACEHOLDER_URL'
    };
    const directionMap = {};
    // prettier-ignore
    ['W', 'WSW', 'SW', 'SSW', 'S', 'SSE', 'SE', 'ESE', 'E', 'ENE', 'NE', 'NNE', 'N', 'NNW', 'NW', 'WNW'].forEach(function (name, index) {
        directionMap[name] = Math.PI / 8 * index;
    });
    const data = rawData.data.map(function (entry) {
      return [entry.time, entry.windSpeed, entry.R, entry.waveHeight];
    });
    const weatherData = rawData.forecast.map(function (entry) {
      return [
        entry.localDate,
        0,
        weatherIcons[entry.skyIcon],
        entry.minTemp,
        entry.maxTemp
      ];
    });
    const dims = {
      time: 0,
      windSpeed: 1,
      R: 2,
      waveHeight: 3,
      weatherIcon: 2,
      minTemp: 3,
      maxTemp: 4
    };
    const arrowSize = 18;
    const weatherIconSize = 45;
    const renderArrow = function (param, api) {
      const point = api.coord([
        api.value(dims.time),
        api.value(dims.windSpeed)
      ]);
      return {
        type: 'path',
        shape: {
          pathData: 'M31 16l-15-15v9h-26v12h26v9z',
          x: -arrowSize / 2,
          y: -arrowSize / 2,
          width: arrowSize,
          height: arrowSize
        },
        rotation: directionMap[api.value(dims.R)],
        position: point,
        style: api.style({
          stroke: '#555',
          lineWidth: 1
        })
      };
    };
    const renderWeather = function (param, api) {
      const point = api.coord([
        api.value(dims.time) + (3600 * 24 * 1000) / 2,
        0
      ]);
      return {
        type: 'group',
            type: 'image',
              image: api.value(dims.weatherIcon),
              x: -weatherIconSize / 2,
              y: -weatherIconSize / 2,
              width: weatherIconSize,
            },
            position: [point[0], 110]
          },
            type: 'text',
                api.value(dims.minTemp) + ' - ' + api.value(dims.maxTemp) + '°',
              textFont: api.font({ fontSize: 14 }),
            position: [point[0], 80]
      // ... (12 total entries — truncated, keep first 10 as sample)
        ]
      };
    };
    option = {
      title: {
        text: '天气 风向 风速 海浪 预报',
        subtext: '示例数据源于 www.seabreeze.com.au',
        left: 'center'
      },
      tooltip: {
        trigger: 'axis',
        formatter: function (params) {
          return [
            echarts.format.formatTime(
              'yyyy-MM-dd',
              params[0].value[dims.time]
            ) +
              ' ' +
              echarts.format.formatTime('hh:mm', params[0].value[dims.time]),
            '风速：' + params[0].value[dims.windSpeed],
            '风向：' + params[0].value[dims.R],
            '浪高：' + params[0].value[dims.waveHeight]
          ].join('<br>');
        }
      },
      grid: {
        top: 160,
        bottom: 125
      },
      xAxis: {
        type: 'time',
        maxInterval: 3600 * 1000 * 24,
        splitLine: {
          lineStyle: {
            color: '#ddd'
          }
        }
      },
      yAxis: [
        {
          name: '风速（节）',
          nameLocation: 'middle',
          nameGap: 35,
          axisLine: {
            lineStyle: {
              color: '#666'
            }
          },
          splitLine: {
            lineStyle: {
              color: '#ddd'
            }
          }
        },
        {
          name: '浪高（米）',
          nameLocation: 'middle',
          nameGap: 35,
          max: 6,
          axisLine: {
            lineStyle: {
              color: '#015DD5'
            }
          },
          splitLine: { show: false }
        },
        {
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: { show: false },
          splitLine: { show: false }
        }
      ],
      visualMap: {
        type: 'piecewise',
        // show: false,
        orient: 'horizontal',
        left: 'center',
        bottom: 10,
        pieces: [
          {
            gte: 17,
            color: '#18BF12',
            label: '大风（>=17节）'
          },
          {
            gte: 11,
            lt: 17,
            color: '#f4e9a3',
            label: '中风（11  ~ 17 节）'
          },
          {
            lt: 11,
            color: '#D33C3E',
            label: '微风（小于 11 节）'
          }
        ],
        seriesIndex: 1,
        dimension: 1
      },
      dataZoom: [
        {
          type: 'inside',
          xAxisIndex: 0,
          minSpan: 5
        },
        {
          type: 'slider',
          xAxisIndex: 0,
          minSpan: 5,
          bottom: 50
        }
      ],
      series: [
        {
          type: 'line',
          yAxisIndex: 1,
          showSymbol: false,
          emphasis: {
            scale: false
          },
          symbolSize: 10,
          areaStyle: {
            color: {
              type: 'linear',
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              global: false,
              colorStops: [
                {
                  offset: 0,
                  color: 'rgba(88,160,253,1)'
                },
                {
                  offset: 0.5,
                  color: 'rgba(88,160,253,0.7)'
                },
                {
                  offset: 1,
                  color: 'rgba(88,160,253,0)'
                }
              ]
            }
          },
          lineStyle: {
            color: 'rgba(88,160,253,1)'
          },
          itemStyle: {
            color: 'rgba(88,160,253,1)'
          },
          encode: {
            x: dims.time,
            y: dims.waveHeight
          },
          data: data,
          z: 2
        },
        {
          type: 'custom',
          renderItem: renderArrow,
          encode: {
            x: dims.time,
            y: dims.windSpeed
          },
          data: data,
          z: 10
        },
        {
          type: 'line',
          symbol: 'none',
          encode: {
            x: dims.time,
            y: dims.windSpeed
          },
          lineStyle: {
            color: '#aaa',
            type: 'dotted'
          },
          data: data,
          z: 1
        },
        {
          type: 'custom',
          renderItem: renderWeather,
          data: weatherData,
          tooltip: {
            trigger: 'item',
            formatter: function (param) {
              return (
                param.value[dims.time] +
                ': ' +
                param.value[dims.minTemp] +
                ' - ' +
                param.value[dims.maxTemp] +
                '°'
              );
            }
          },
          yAxisIndex: 2,
          z: 11
        }
      ]
    };
    myChart.setOption(option);

```
