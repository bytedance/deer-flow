# map3d-alcohol-consumption

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=map3d-alcohol-consumption
**Chart Type:** `map3D`

## User Data Requirements

Columns needed: check data arrays in reference code for required format

## Data Arrays — Replacement Guide

The code contains **0 data array(s)** to replace:


## External Data Format

This example uses external data. Format from `alcohol.json`:

```json
[
  [
    "Afghanistan",
    "0.01"
  ],
  [
    "Albania",
    "2.01"
  ],
  [
    "Algeria",
    "0.15"
  ]
]
```

Agent: build DuckDB query to produce matching data structure.
## Agent Workflow

1. **Analyze** user table → identify columns matching the required format above
2. **Query DuckDB** → transform to match each data array's format
3. **Replace**: use **bracket-counting** to find each `data: [...]` → replace with real data
4. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: Map3D - Alcohol Consumption
category: map3D
titleCN: Map3D - Alcohol Consumption
*/
var data = [
  ["Afghanistan", "0.01"],
  ["Albania", "2.01"],
  ["Algeria", "0.15"],
  ["Andorra", ""],
  ["Angola", "3.86"],
  ["Antigua and Barbuda", "5.73"],
  ["Argentina", "8.40"],
  ["Armenia", "1.48"],
  ["Australia", "9.02"],
  ["Austria", "11.08"],
  ["Azerbaijan", "4.54"],
  ["Bahamas", ""],
  ["Bahrain", "6.98"],
  ["Bangladesh", "0.00"],
  ["Barbados", ""],
  ["Belarus", "5.53"],
  ["Belgium", "10.63"],
  ["Belize", "6.25"],
  ["Benin", "1.29"],
  ["Bhutan", "0.23"],
  ["Bolivia", "3.23"],
  ["Bosnia and Herzegovina", "9.05"],
  ["Botswana", "4.29"],
  ["Brazil", "5.76"],
  ["Brunei Darussalam", "0.12"],
  ["Bulgaria", "5.86"],
  ["Burkina Faso", "5.01"],
  ["Burundi", "9.10"],
  ["Cambodia", "1.48"],
  ["Cameroon", "3.77"],
  ["Canada", "7.80"],
  ["Cape Verde", "4.78"],
  ["Central African Republic", "1.53"],
  ["Chad", "0.31"],
  ["Chile", "6.60"],
  ["China", "5.20"],
  ["Colombia", "5.68"],
  ["Comoros", "0.31"],
  ["Congo", "2.60"],
  ["Cook Islands", "3.73"],
  ["Costa Rica", "5.65"],
  ["Cote d'Ivoire", "1.77"],
  ["Croatia", "12.25"],
  ["Cuba", "2.26"],
  ["Cyprus", "11.52"],
  ["Czech Republic", "12.99"],
  ["Democratic People's Republic of Korea", "3.26"],
  ["Democratic Republic of the Congo", "1.86"],
  ["Denmark", "11.71"],
  ["Djibouti", "1.79"],
  ["Dominica", "7.50"],
  ["Dominican Republic", "6.66"],
  ["Ecuador", "2.36"],
  ["Egypt", "0.21"],
  ["El Salvador", "3.72"],
  ["Equatorial Guinea", "3.38"],
  ["Eritrea", "0.59"],
  ["Estonia", "9.00"],
  ["Ethiopia", "0.86"],
  ["Fiji", "1.72"],
  ["Finland", "9.31"],
  ["France", "11.43"],
  ["Gabon", "8.01"],
  ["Gambia", "2.59"],
  ["Georgia", "1.47"],
  ["Germany", "11.99"],
  ["Ghana", "1.57"],
  ["Greece", "9.01"],
  ["Grenada", "6.67"],
  ["Guatemala", "1.46"],
  ["Guinea", "0.20"],
  ["Guinea-Bissau", "2.19"],
  ["Guyana", "3.84"],
  ["Haiti", "8.30"],
  ["Honduras", "2.92"],
  ["Hungary", "13.60"],
  ["Iceland", "6.99"],
  ["India", "0.29"],
  ["Indonesia", "0.09"],
  ["Iran (Islamic Republic of)", "0.00"],
  ["Iraq", "0.21"],
  ["Ireland", "13.69"],
  ["Israel", "2.47"],
  ["Italy", "8.02"],
  ["Jamaica", "1.74"],
  ["Japan", "7.59"],
  ["Jordan", "0.31"],
  ["Kazakhstan", "2.96"],
  ["Kenya", "1.51"],
  ["Kiribati", "0.45"],
  ["Kuwait", "0.03"],
  ["Kyrgyzstan", "3.63"],
  ["Lao People's Democratic Republic", "6.91"],
  ["Latvia", "9.61"],
  ["Lebanon", "3.24"],
  ["Lesotho", "1.82"],
  ["Liberia", "3.82"],
  ["Libyan Arab Jamahiriya", "0.01"],
  ["Lithuania", "9.89"],
  ["Luxembourg", "15.56"],
  ["Madagascar", "1.59"],
  ["Malawi", "1.41"],
  ["Malaysia", "1.06"],
  ["Maldives", ""],
  ["Mali", "0.50"],
  ["Malta", "6.02"],
  ["Marshall Islands", ""],
  ["Mauritania", "0.01"],
  ["Mauritius", "3.03"],
  ["Mexico", "4.57"],
  ["Micronesia (Federated States of)", "1.23"],
  ["Monaco", ""],
  ["Mongolia", "2.83"],
  ["Montenegro", ""],
  ["Morocco", "0.45"],
  ["Mozambique", "0.52"],
  ["Myanmar", "0.33"],
  ["Namibia", "5.97"],
  ["Nauru", "0.87"],
  ["Nepal", "0.19"],
  ["Netherlands", "9.68"],
  ["New Zealand", "9.68"],
  ["Nicaragua", "2.48"],
  ["Niger", "0.05"],
  ["Nigeria", "10.57"],
  ["Niue", "9.47"],
  ["Norway", "5.50"],
  ["Oman", "0.26"],
  ["Pakistan", "0.01"],
  ["Palau", ""],
  ["Panama", "5.98"],
  ["Papua New Guinea", "1.62"],
  ["Paraguay", "3.73"],
  ["Peru", "3.83"],
  ["Philippines", "3.51"],
  ["Poland", "8.09"],
  ["Portugal", "11.54"],
  ["Qatar", "4.40"],
  ["Republic of Korea", "7.87"],
  ["Republic of Moldova", "13.18"],
  ["Romania", "9.74"],
  ["Rwanda", "6.93"],
  ["Saint Kitts and Nevis", "6.73"],
  ["Saint Lucia", "11.48"],
  ["Saint Vincent and the Grenadines", "7.00"],
  ["Samoa", "1.73"],
  ["San Marino", ""],
  ["Sao Tome and Principe", "6.95"],
  ["Saudi Arabia", "0.00"],
  ["Senegal", "0.46"],
  ["Serbia", ""],
  ["Seychelles", "3.36"],
  ["Sierra Leone", "6.39"],
  ["Singapore", "2.17"],
  ["Slovakia", "10.35"],
  ["Slovenia", "6.74"],
  ["Solomon Islands", "0.97"],
  ["Somalia", "0.00"],
  ["South Africa", "6.72"],
  ["Spain", "11.68"],
  ["Sri Lanka", "0.28"],
  ["Sudan", "0.30"],
  ["Suriname", ""],
  ["Swaziland", "4.60"],
  ["Sweden", "5.96"],
  ["Switzerland", "10.83"],
  ["Tajikistan", "0.39"],
  ["Thailand", "5.59"],
  ["Timor-Leste", ""],
  ["Togo", "1.24"],
  ["Tonga", "0.75"],
  ["Trinidad and Tobago", "4.17"],
  ["Tunisia", "1.23"],
  ["Turkey", "1.37"],
  ["Turkmenistan", "1.18"],
  ["Tuvalu", "1.37"],
  ["Uganda", ""],
  ["Ukraine", "6.09"],
  ["United Arab Emirates", "0.02"],
  ["United Kingdom", "11.75"],
  ["Uruguay", "7.74"],
  ["Uzbekistan", "1.51"],
  ["Vanuatu", "0.75"],
  ["Venezuela", "6.67"],
  ["Viet Nam", "0.85"],
  ["Yemen", "0.04"],
  ["Zambia", "2.40"],
  ["Zimbabwe", "4.41"],
  ["", ""],
  ["", ""],
  ["United States", "8.61"],
  ["Tanzania", "5.45"],
  ["Macedonia", "5.69"],
  ["Syria", "0.49"],
  ["Russia", "10.32"],
  [""]
];
var regionData = data.map(function (item) {
    return {
      name: item[0],
      value: item[1]
    };
  });
  console.log(regionData);
  myChart.setOption({
    backgroundColor: '#cdcfd5',
    visualMap: {
      min: 0,
      max: 15,
      realtime: true,
      calculable: true,
      inRange: {
        color: [
          '#313695',
          '#4575b4',
          '#74add1',
          '#abd9e9',
          '#e0f3f8',
          '#ffffbf',
          '#fee090',
          '#fdae61',
          '#f46d43',
          '#d73027',
          '#a50026'
        ]
      }
    },
    series: [
      {
        type: 'map3D',
        map: 'world',
        shading: 'lambert',
        realisticMaterial: {
          roughness: 0.2,
          metalness: 0
        },
        postEffect: {
          enable: true,
          SSAO: {
            enable: true,
            radius: 2,
            intensity: 1
          }
        },
        groundPlane: {
          show: true
        },
        light: {
          main: {
            intensity: 2,
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
            exposure: 1,
            diffuseIntensity: 1
          }
        },
        viewControl: {
          distance: 50
        },
        regionHeight: 1,
        data: regionData
      }
    ]
  });

```
