# sankey-itemstyle

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=sankey-itemstyle
**Chart Type:** `sankey`

## User Data Requirements

Columns needed: need **source**, **target**, **value** columns

## Data Arrays — Complete Replacement Guide

**2 array(s)** to replace with real data:

### [0] `data` (context: series)
```
data: 
```

### [1] `links` (context: root)
```
links: 
```

## Agent Workflow

1. **Analyze** user table → identify columns matching the required format above
2. **Query DuckDB** → transform to match each data array's format
3. **Replace**: use **bracket-counting** to find each `data: [...]` → replace with real data
4. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: Specify ItemStyle for Each Node in Sankey
category: sankey
titleCN: 桑基图节点自定义样式
difficulty: 2
*/
option = {
  backgroundColor: '#fff',
  title: {
    subtext: 'Data From lisachristina1234 on GitHub',
    left: 'center'
  },
  series: [
    {
      type: 'sankey',
      left: 50.0,
      top: 20.0,
      right: 150.0,
      bottom: 25.0,
      data: [
        {
          name: 'Werne',
          itemStyle: {
            color: '#f18bbf',
            borderColor: '#f18bbf'
          }
        },
        {
          name: 'Duesseldorf',
          itemStyle: {
            color: '#0078D7',
            borderColor: '#0078D7'
          }
        },
        {
          name: 'Cambridge',
          itemStyle: {
            color: '#3891A7',
            borderColor: '#3891A7'
          }
        },
        {
          name: 'Colma',
          itemStyle: {
            color: '#0037DA',
            borderColor: '#0037DA'
          }
        },
        {
          name: 'W. York',
          itemStyle: {
            color: '#C0BEAF',
            borderColor: '#C0BEAF'
          }
        },
        {
          name: 'Frankfurt am Main',
          itemStyle: {
            color: '#EA005E',
            borderColor: '#EA005E'
          }
        },
        {
          name: 'Metz',
          itemStyle: {
            color: '#D13438',
            borderColor: '#D13438'
          }
        },
        {
          name: 'Orleans',
          itemStyle: {
            color: '#567C73',
            borderColor: '#567C73'
          }
        },
        {
          name: 'Saint-Denis',
          itemStyle: {
            color: '#9ed566',
            borderColor: '#9ed566'
          }
        },
        {
          name: 'Hof',
          itemStyle: {
            color: '#2BCC7F',
            borderColor: '#2BCC7F'
          }
        },
        {
          name: 'Cliffside',
          itemStyle: {
            color: '#809B48',
            borderColor: '#809B48'
          }
        },
        {
          name: 'Leeds',
          itemStyle: {
            color: '#9B2D1F',
            borderColor: '#9B2D1F'
          }
        },
        {
          name: 'Victoria',
          itemStyle: {
            color: '#604878',
            borderColor: '#604878'
          }
        },
        {
          name: 'Erlangen',
          itemStyle: {
            color: '#A5644E',
            borderColor: '#A5644E'
          }
        },
        {
          name: 'Saint Germain en Laye',
          itemStyle: {
            color: '#2D3F3A',
            borderColor: '#2D3F3A'
          }
        },
        {
          name: 'Roissy en Brie',
          itemStyle: {
            color: '#761721',
            borderColor: '#761721'
          }
        },
        {
          name: 'Wokingham',
          itemStyle: {
            color: '#B1BADD',
            borderColor: '#B1BADD'
          }
        },
        {
          name: 'Runcorn',
          itemStyle: {
            color: '#B0CCB0',
            borderColor: '#B0CCB0'
          }
        },
        {
          name: 'Newton',
          itemStyle: {
            color: '#8164A3',
            borderColor: '#8164A3'
          }
        },
        {
          name: 'Morangis',
          itemStyle: {
            color: '#8E562E',
            borderColor: '#8E562E'
          }
        },
        {
          name: 'Metchosin',
          itemStyle: {
            color: '#C1504D',
            borderColor: '#C1504D'
          }
        },
        {
          name: 'Kirkby',
          itemStyle: {
            color: '#CCAF0A',
            borderColor: '#CCAF0A'
          }
        },
        {
          name: 'London',
          itemStyle: {
            color: '#956251',
            borderColor: '#956251'
          }
        },
        {
          name: 'Offenbach',
          itemStyle: {
            color: '#C17529',
            borderColor: '#C17529'
          }
        },
        {
          name: 'Warrington',
          itemStyle: {
            color: '#CEC597',
            borderColor: '#CEC597'
          }
        },
        {
          name: 'Vancouver',
          itemStyle: {
            color: '#9F2936',
            borderColor: '#9F2936'
          }
        },
        {
          name: 'SuperiorCard',
          itemStyle: {
            color: 'rgba(128,155,72,255)',
            borderColor: 'rgba(128,155,72,255)'
          }
        },
        {
          name: 'Lille',
          itemStyle: {
            color: '#ac7430',
            borderColor: '#ac7430'
          }
        },
        {
          name: 'Hamburg',
          itemStyle: {
            color: '#00BCF2',
            borderColor: '#00BCF2'
          }
        },
        {
          name: 'Langley',
          itemStyle: {
            color: '#CD7B38',
            borderColor: '#CD7B38'
          }
        },
        {
          name: 'Les Ulis',
          itemStyle: {
            color: '#424242',
            borderColor: '#424242'
          }
        },
        {
          name: 'Saarbrücken',
          itemStyle: {
            color: '#f63185',
            borderColor: '#f63185'
          }
        },
        {
          name: 'N. Vancouver',
          itemStyle: {
            color: '#9CBC59',
            borderColor: '#9CBC59'
          }
        },
        {
          name: 'Chalk Riber',
          itemStyle: {
            color: '#4F4BD9',
            borderColor: '#4F4BD9'
          }
        },
        {
          name: 'Esher-Molesey',
          itemStyle: {
            color: '#3EC562',
            borderColor: '#3EC562'
          }
        },
        {
          name: 'Chatou',
          itemStyle: {
            color: '#F06F2E',
            borderColor: '#F06F2E'
          }
        },
        {
          name: 'Hannover',
          itemStyle: {
            color: '#C3986D',
            borderColor: '#C3986D'
          }
        },
        {
          name: 'Roncq',
          itemStyle: {
            color: '#4D291C',
            borderColor: '#4D291C'
          }
        },
        {
          name: 'Ingolstadt',
          itemStyle: {
            color: '#009c7a',
            borderColor: '#009c7a'
          }
        },
        {
          name: 'Drancy',
          itemStyle: {
            color: '#986F0B',
            borderColor: '#986F0B'
          }
        },
        {
          name: 'Langford',
          itemStyle: {
            color: '#3C8EA4',
            borderColor: '#3C8EA4'
          }
        },
        {
          name: 'Lebanon',
          itemStyle: {
            color: '#4F82BE',
            borderColor: '#4F82BE'
          }
        },
        {
          name: 'Maidenhead',
          itemStyle: {
            color: '#D38017',
            borderColor: '#D38017'
          }
        },
        {
          name: 'Stoke-on-Trent',
          itemStyle: {
            color: '#A8CDD7',
            borderColor: '#A8CDD7'
          }
        },
        {
          name: 'Peterborough',
          itemStyle: {
            color: '#7A072D',
            borderColor: '#7A072D'
          }
        },
        {
          name: 'Suresnes',
          itemStyle: {
            color: '#859599',
            borderColor: '#859599'
          }
        },
        {
          name: 'Versailles',
          itemStyle: {
            color: '#84AA33',
            borderColor: '#84AA33'
          }
        },
        {
          name: 'Neunkirchen',
          itemStyle: {
            color: '#ff8b67',
            borderColor: '#ff8b67'
          }
        },
        {
          name: 'Vista',
          itemStyle: {
            color: 'rgba(106,82,134,255)',
            borderColor: 'rgba(106,82,134,255)'
          }
        },
        {
          name: 'Westminster',
          itemStyle: {
            color: '#1B587C',
            borderColor: '#1B587C'
          }
        },
        {
          name: 'Kiel',
          itemStyle: {
            color: '#A19574',
            borderColor: '#A19574'
          }
        },
        {
          name: 'Newcastle upon Tyne',
          itemStyle: {
            color: '#918485',
            borderColor: '#918485'
          }
        },
        {
          name: 'Oxon',
          itemStyle: {
            color: '#FFA98C',
            borderColor: '#FFA98C'
          }
        },
        {
          name: 'West Sussex',
          itemStyle: {
            color: '#B0E3C0',
            borderColor: '#B0E3C0'
          }
        },
        {
          name: 'Oak Bay',
          itemStyle: {
            color: '#4BADC7',
            borderColor: '#4BADC7'
          }
        },
        {
          name: 'Milton Keynes',
          itemStyle: {
            color: '#BA144C',
            borderColor: '#BA144C'
          }
        },
        {
          name: 'Eilenburg',
          itemStyle: {
            color: '#F0A22E',
            borderColor: '#F0A22E'
          }
        },
        {
          name: 'ColonialVoice',
          itemStyle: {
            color: 'rgba(64,105,157,255)',
            borderColor: 'rgba(64,105,157,255)'
          }
        },
        {
          name: 'Liverpool',
          itemStyle: {
            color: '#A28E6A',
            borderColor: '#A28E6A'
          }
        },
        {
          name: 'Calgary',
          itemStyle: {
            color: '#9F413E',
            borderColor: '#9F413E'
          }
        },
        {
          name: 'CAD',
          itemStyle: {
            color: '#40699D',
            borderColor: '#40699D'
          }
        },
        {
          name: 'Paris La Defense',
          itemStyle: {
            color: '#989391',
            borderColor: '#989391'
          }
        },
        {
          name: "Villeneuve-d'Ascq",
          itemStyle: {
            color: '#886CE4',
            borderColor: '#886CE4'
          }
        },
        {
          name: 'Gloucestershire',
          itemStyle: {
            color: '#964305',
            borderColor: '#964305'
          }
        },
        {
          name: 'Gateshead',
          itemStyle: {
            color: '#485FB5',
            borderColor: '#485FB5'
          }
        },
        {
          name: 'Salzgitter',
          itemStyle: {
            color: '#87a0c7',
            borderColor: '#87a0c7'
          }
        },
        {
          name: 'Woolston',
          itemStyle: {
            color: '#FFE2C5',
            borderColor: '#FFE2C5'
          }
        },
        {
          name: 'Frankfurt',
          itemStyle: {
            color: '#40699D',
            borderColor: '#40699D'
          }
        },
        {
          name: 'Münster',
          itemStyle: {
            color: '#7e7eb2',
            borderColor: '#7e7eb2'
          }
        },
        {
          name: 'York',
          itemStyle: {
            color: '#587C7D',
            borderColor: '#587C7D'
          }
        },
        {
          name: 'High Wycombe',
          itemStyle: {
            color: '#F07F09',
            borderColor: '#F07F09'
          }
        },
        {
          name: 'Stuttgart',
          itemStyle: {
            color: '#E3008C',
            borderColor: '#E3008C'
          }
        },
        {
          name: 'Sooke',
          itemStyle: {
            color: '#4E8542',
            borderColor: '#4E8542'
          }
        },
        {
          name: 'Essen',
          itemStyle: {
            color: '#B58B80',
            borderColor: '#B58B80'
          }
        },
        {
          name: 'München',
          itemStyle: {
            color: '#4dc0a6',
            borderColor: '#4dc0a6'
          }
        },
        {
          name: 'Haney',
          itemStyle: {
            color: '#6A5286',
            borderColor: '#6A5286'
          }
        },
        {
          name: 'Port Hammond',
          itemStyle: {
            color: '#F89746',
            borderColor: '#F89746'
          }
        },
        {
          name: 'Saint Ouen',
          itemStyle: {
            color: '#744DA9',
            borderColor: '#744DA9'
          }
        },
        {
          name: 'Watford',
          itemStyle: {
            color: '#E8B7B7',
            borderColor: '#E8B7B7'
          }
        },
        {
          name: 'GBP',
          itemStyle: {
            color: '#C32D2E',
            borderColor: '#C32D2E'
          }
        },
        {
          name: 'Paderborn',
          itemStyle: {
            color: '#F0C42E',
            borderColor: '#F0C42E'
          }
        },
        {
          name: 'Dunkerque',
          itemStyle: {
            color: '#881798',
            borderColor: '#881798'
          }
        },
        {
          name: 'Colomiers',
          itemStyle: {
            color: '#efa835',
            borderColor: '#efa835'
          }
        },
        {
          name: 'Oxford',
          itemStyle: {
            color: '#D8B25C',
            borderColor: '#D8B25C'
          }
        },
        {
          name: 'Bury',
          itemStyle: {
            color: '#FEB80A',
            borderColor: '#FEB80A'
          }
        },
        {
          name: 'Royal Oak',
          itemStyle: {
            color: '#009DD9',
            borderColor: '#009DD9'
          }
        },
        {
          name: 'Shawnee',
          itemStyle: {
            color: '#F07F09',
            borderColor: '#F07F09'
          }
        },
        {
          name: 'Lancaster',
          itemStyle: {
            color: '#D34817',
            borderColor: '#D34817'
          }
        },
        {
          name: 'DEM',
          itemStyle: {
            color: '#4E342E',
            borderColor: '#4E342E'
          }
        },
        {
          name: 'Grevenbroich',
          itemStyle: {
            color: '#FFA836',
            borderColor: '#FFA836'
          }
        },
        {
          name: 'Distinguish',
          itemStyle: {
            color: 'rgba(159,65,62,255)',
            borderColor: 'rgba(159,65,62,255)'
          }
        },
        {
          name: 'Cheltenham',
          itemStyle: {
            color: '#FF6551',
            borderColor: '#FF6551'
          }
        },
        {
          name: 'Reading',
          itemStyle: {
            color: '#72A376',
            borderColor: '#72A376'
          }
        },
        {
          name: 'Pantin',
          itemStyle: {
            color: '#69797E',
            borderColor: '#69797E'
          }
        },
        {
          name: 'Kassel',
          itemStyle: {
            color: '#e65e20',
            borderColor: '#e65e20'
          }
        },
        {
          name: 'Orly',
          itemStyle: {
            color: '#6E6A68',
            borderColor: '#6E6A68'
          }
        },
        {
          name: 'FRF',
          itemStyle: {
            color: '#5ba33b',
            borderColor: '#5ba33b'
          }
        },
        {
          name: 'Cergy',
          itemStyle: {
            color: '#B4009E',
            borderColor: '#B4009E'
          }
        },
        {
          name: 'Paris',
          itemStyle: {
            color: '#666666',
            borderColor: '#666666'
          }
        }
      ],
      links: [
        {
          source: 'FRF',
          target: 'Colomiers',
          value: 357.8399963378906
        },
        {
          source: 'SuperiorCard',
          target: 'FRF',
          value: 894.5999908447266
        },
        {
          source: 'DEM',
          target: 'München',
          value: 178.9199981689453
        },
        {
          source: 'GBP',
          target: 'Reading',
          value: 188.52999836206436
        },
        {
          source: 'CAD',
          target: 'Shawnee',
          value: 2346.919983509928
        },
        {
          source: 'GBP',
          target: 'Kirkby',
          value: 753.4000000059605
        },
        {
          source: 'FRF',
          target: 'Roncq',
          value: 178.9199981689453
        },
        {
          source: 'GBP',
          target: 'Peterborough',
          value: 999.159998036921
        },
        {
          source: 'DEM',
          target: 'Frankfurt am Main',
          value: 536.7599945068359
        },
        {
          source: 'GBP',
          target: 'Oxford',
          value: 1831.3799968883395
        },
        {
          source: 'Vista',
          target: 'FRF',
          value: 1789.1999816894531
        },
        {
          source: 'CAD',
          target: 'Langley',
          value: 1274.8199949413538
        },
        {
          source: 'DEM',
          target: 'Offenbach',
          value: 357.8399963378906
        },
        {
          source: 'FRF',
          target: "Villeneuve-d'Ascq",
          value: 178.9199981689453
        },
        {
          source: 'FRF',
          target: 'Dunkerque',
          value: 357.8399963378906
        },
        {
          source: 'DEM',
          target: 'Eilenburg',
          value: 178.9199981689453
        },
        {
          source: 'FRF',
          target: 'Paris',
          value: 1073.5199890136719
        },
        {
          source: 'GBP',
          target: 'Maidenhead',
          value: 549.8400026857853
        },
        {
          source: 'CAD',
          target: 'Sooke',
          value: 1764.499989286065
        },
        {
          source: 'CAD',
          target: 'Vancouver',
          value: 1528.580000281334
        },
        {
          source: 'DEM',
          target: 'Hamburg',
          value: 357.8399963378906
        },
        {
          source: 'GBP',
          target: 'London',
          value: 8619.309983983636
        },
        {
          source: 'CAD',
          target: 'Oak Bay',
          value: 1565.109990529716
        },
        {
          source: 'Distinguish',
          target: 'FRF',
          value: 2683.7999725341797
        },
        {
          source: 'DEM',
          target: 'Neunkirchen',
          value: 178.9199981689453
        },
        {
          source: 'FRF',
          target: 'Cergy',
          value: 178.9199981689453
        },
        {
          source: 'DEM',
          target: 'Hof',
          value: 357.8399963378906
        },
        {
          source: 'FRF',
          target: 'Paris La Defense',
          value: 178.9199981689453
        },
        {
          source: 'CAD',
          target: 'Westminster',
          value: 1149.7999994903803
        },
        {
          source: 'DEM',
          target: 'Ingolstadt',
          value: 536.7599945068359
        },
        {
          source: 'GBP',
          target: 'Saint Ouen',
          value: 0.5899999737739563
        },
        {
          source: 'FRF',
          target: 'Lille',
          value: 357.8399963378906
        },
        {
          source: 'GBP',
          target: 'Leeds',
          value: 1356.6899970173836
        },
        {
          source: 'FRF',
          target: 'Morangis',
          value: 357.8399963378906
        },
        {
          source: 'GBP',
          target: 'Orly',
          value: 0.5899999737739563
        },
        {
          source: 'SuperiorCard',
          target: 'DEM',
          value: 1431.3599853515625
        },
        {
          source: 'Vista',
          target: 'CAD',
          value: 5369.929964579642
        },
        {
          source: 'GBP',
          target: 'Paris',
          value: 0.6399999856948853
        },
        {
          source: 'GBP',
          target: 'Liverpool',
          value: 857.1999968588352
        },
        {
          source: 'GBP',
          target: 'Stoke-on-Trent',
          value: 1131.7099939212203
        },
        {
          source: 'Distinguish',
          target: 'DEM',
          value: 2504.8799743652344
        },
        {
          source: 'CAD',
          target: 'Langford',
          value: 2343.4599857851863
        },
        {
          source: 'DEM',
          target: 'Kassel',
          value: 536.7599945068359
        },
        {
          source: 'GBP',
          target: 'High Wycombe',
          value: 216.83999809622765
        },
        {
          source: 'CAD',
          target: 'Port Hammond',
          value: 1711.1399984136224
        },
        {
          source: 'DEM',
          target: 'Duesseldorf',
          value: 178.9199981689453
        },
        {
          source: 'GBP',
          target: 'Gloucestershire',
          value: 422.28999888151884
        },
        {
          source: 'Distinguish',
          target: 'GBP',
          value: 10384.949975416064
        },
        {
          source: 'FRF',
          target: 'Roissy en Brie',
          value: 178.9199981689453
        },
        {
          source: 'GBP',
          target: 'West Sussex',
          value: 592.1700052022934
        },
        {
          source: 'CAD',
          target: 'Cliffside',
          value: 2906.2699892893434
        },
        {
          source: 'GBP',
          target: 'Newcastle upon Tyne',
          value: 1448.2899911925197
        },
        {
          source: 'GBP',
          target: 'Runcorn',
          value: 1120.4800013303757
        },
        {
          source: 'GBP',
          target: 'W. York',
          value: 612.1199932694435
        },
        {
          source: 'DEM',
          target: 'Kiel',
          value: 178.9199981689453
        },
        {
          source: 'GBP',
          target: 'Woolston',
          value: 833.3199937939644
        },
        {
          source: 'Distinguish',
          target: 'CAD',
          value: 6950.059956334531
        },
        {
          source: 'DEM',
          target: 'Frankfurt',
          value: 715.6799926757812
        },
        {
          source: 'CAD',
          target: 'Colma',
          value: 0.2199999988079071
        },
        {
          source: 'DEM',
          target: 'Essen',
          value: 178.9199981689453
        },
        {
          source: 'FRF',
          target: 'Chatou',
          value: 178.9199981689453
        },
        {
          source: 'GBP',
          target: 'Cheltenham',
          value: 573.0499979257584
        },
        {
          source: 'SuperiorCard',
          target: 'GBP',
          value: 8228.39999615401
        },
        {
          source: 'CAD',
          target: 'Haney',
          value: 2310.4499812424183
        },
        {
          source: 'FRF',
          target: 'Saint Ouen',
          value: 178.9199981689453
        },
        {
          source: 'CAD',
          target: 'Chalk Riber',
          value: 0.9200000166893005
        },
        {
          source: 'DEM',
          target: 'Salzgitter',
          value: 178.9199981689453
        },
        {
          source: 'ColonialVoice',
          target: 'FRF',
          value: 1610.2799835205078
        },
        {
          source: 'DEM',
          target: 'Stuttgart',
          value: 357.8399963378906
        },
        {
          source: 'FRF',
          target: 'Saint-Denis',
          value: 178.9199981689453
        },
        {
          source: 'CAD',
          target: 'Royal Oak',
          value: 2128.459992274642
        },
        {
          source: 'FRF',
          target: 'Les Ulis',
          value: 715.6799926757812
        },
        {
          source: 'FRF',
          target: 'Drancy',
          value: 178.9199981689453
        },
        {
          source: 'GBP',
          target: 'Esher-Molesey',
          value: 911.4700058028102
        },
        {
          source: 'SuperiorCard',
          target: 'CAD',
          value: 7388.099954992533
        },
        {
          source: 'GBP',
          target: 'Bury',
          value: 903.9400005489588
        },
        {
          source: 'GBP',
          target: 'Watford',
          value: 1326.5300009772182
        },
        {
          source: 'CAD',
          target: 'Victoria',
          value: 827.3899968340993
        },
        {
          source: 'DEM',
          target: 'Saarbrücken',
          value: 178.9199981689453
        },
        {
          source: 'GBP',
          target: 'Lancaster',
          value: 685.6899967193604
        },
        {
          source: 'FRF',
          target: 'Pantin',
          value: 178.9199981689453
        },
        {
          source: 'CAD',
          target: 'Newton',
          value: 1781.909985654056
        },
        {
          source: 'GBP',
          target: 'Oxon',
          value: 493.6499986946583
        },
        {
          source: 'CAD',
          target: 'Calgary',
          value: 361.3899962902069
        },
        {
          source: 'DEM',
          target: 'Münster',
          value: 715.6799926757812
        },
        {
          source: 'DEM',
          target: 'Grevenbroich',
          value: 536.7599945068359
        },
        {
          source: 'DEM',
          target: 'Paderborn',
          value: 357.8399963378906
        },
        {
          source: 'GBP',
          target: 'York',
          value: 3172.9999914616346
        },
        {
          source: 'CAD',
          target: 'Metchosin',
          value: 1750.7899813987315
        },
        {
          source: 'FRF',
          target: 'Suresnes',
          value: 357.8399963378906
        },
        {
          source: 'FRF',
          target: 'Versailles',
          value: 894.5999908447266
        },
        {
          source: 'DEM',
          target: 'Erlangen',
          value: 536.7599945068359
        },
        {
          source: 'CAD',
          target: 'Lebanon',
          value: 0.8700000047683716
        },
        {
          source: 'GBP',
          target: 'Wokingham',
          value: 812.6600027084351
        },
        {
          source: 'GBP',
          target: 'Cambridge',
          value: 500.36999743431807
        },
        {
          source: 'ColonialVoice',
          target: 'GBP',
          value: 8040.7799860313535
        },
        {
          source: 'FRF',
          target: 'Saint Germain en Laye',
          value: 178.9199981689453
        },
        {
          source: 'FRF',
          target: 'Metz',
          value: 178.9199981689453
        },
        {
          source: 'FRF',
          target: 'Orleans',
          value: 357.8399963378906
        },
        {
          source: 'GBP',
          target: 'Milton Keynes',
          value: 1648.2200061008334
        },
        {
          source: 'GBP',
          target: 'Warrington',
          value: 2162.8300000429153
        },
        {
          source: 'CAD',
          target: 'N. Vancouver',
          value: 1862.4599857926369
        },
        {
          source: 'DEM',
          target: 'Hannover',
          value: 178.9199981689453
        },
        {
          source: 'Vista',
          target: 'GBP',
          value: 9497.539981640875
        },
        {
          source: 'DEM',
          target: 'Werne',
          value: 178.9199981689453
        },
        {
          source: 'ColonialVoice',
          target: 'DEM',
          value: 1789.1999816894531
        },
        {
          source: 'ColonialVoice',
          target: 'CAD',
          value: 7907.36997512728
        },
        {
          source: 'GBP',
          target: 'Gateshead',
          value: 1425.7099913656712
        },
        {
          source: 'Vista',
          target: 'DEM',
          value: 1968.1199798583984
        }
      ],
      lineStyle: {
        color: 'source',
        curveness: 0.5
      },
      itemStyle: {
        color: '#1f77b4',
        borderColor: '#1f77b4'
      },
      label: {
        color: 'rgba(0,0,0,0.7)',
        fontFamily: 'Arial',
        fontSize: 10
      }
    }
  ],
  tooltip: {
    trigger: 'item'
  }
};
```
