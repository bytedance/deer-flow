# matrix-periodic-table

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=matrix-periodic-table
**Chart Type:** `custom`

## User Data Requirements

Columns needed: check data arrays in reference code for required format

## Data Arrays — Complete Replacement Guide

**1 array(s)** to replace with real data:

### [0] `data` (context: series)
```
data: 
```

## Agent Workflow

1. **Analyze** user table → identify columns matching the required format above
2. **Query DuckDB** → transform to match each data array's format
3. **Replace**: use **bracket-counting** to find each `data: [...]` → replace with real data
4. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: Periodic Table
category: matrix
titleCN: 元素周期表
difficulty: 10
since: 6.0.0
*/
const colors = {
  red: '#f88',
  green: '#8f8',
  blue: '#8bf',
  yellow: '#ff8'
};
option = {
  matrix: {
    x: {
      data: Array.from({ length: 19 }, (_, i) => i + 1 + ''),
      label: {
        show: false
      },
      itemStyle: {
        borderWidth: 0
      },
      dividerLineStyle: {
        width: 0
      }
    },
    y: {
      data: Array.from({ length: 10 }, (_, i) => i + 1 + ''),
      label: {
        show: false
      },
      itemStyle: {
        borderWidth: 0
      },
      dividerLineStyle: {
        width: 0
      }
    },
    left: 'center',
    width: 900,
    backgroundStyle: {
      borderWidth: 0
    },
    body: {
      itemStyle: {
        borderWidth: 0
      }
    }
  },
  series: {
    type: 'custom',
    coordinateSystem: 'matrix',
    data: [
      ['1', '1', '1', 'H', colors.red],
      ['19', '1', '2', 'He', colors.red],
      ['1', '2', '3', 'Li', colors.red],
      ['2', '2', '4', 'Be', colors.red],
      ['14', '2', '5', 'B', colors.yellow],
      ['15', '2', '6', 'C', colors.yellow],
      ['16', '2', '7', 'N', colors.yellow],
      ['17', '2', '8', 'O', colors.yellow],
      ['18', '2', '9', 'F', colors.yellow],
      ['19', '2', '10', 'Ne', colors.yellow],
      ['1', '3', '11', 'Na', colors.red],
      ['2', '3', '12', 'Mg', colors.red],
      ['14', '3', '13', 'Al', colors.yellow],
      ['15', '3', '14', 'Si', colors.yellow],
      ['16', '3', '15', 'P', colors.yellow],
      ['17', '3', '16', 'S', colors.yellow],
      ['18', '3', '17', 'Cl', colors.yellow],
      ['19', '3', '18', 'Ar', colors.yellow],
      ['1', '4', '19', 'K', colors.red],
      ['2', '4', '20', 'Ca', colors.red],
      ['4', '4', '21', 'Sc', colors.blue],
      ['5', '4', '22', 'Ti', colors.blue],
      ['6', '4', '23', 'V', colors.blue],
      ['7', '4', '24', 'Cr', colors.blue],
      ['8', '4', '25', 'Mn', colors.blue],
      ['9', '4', '26', 'Fe', colors.blue],
      ['10', '4', '27', 'Co', colors.blue],
      ['11', '4', '28', 'Ni', colors.blue],
      ['12', '4', '29', 'Cu', colors.blue],
      ['13', '4', '30', 'Zn', colors.blue],
      ['14', '4', '31', 'Ga', colors.yellow],
      ['15', '4', '32', 'Ge', colors.yellow],
      ['16', '4', '33', 'As', colors.yellow],
      ['17', '4', '34', 'Se', colors.yellow],
      ['18', '4', '35', 'Br', colors.yellow],
      ['19', '4', '36', 'Kr', colors.yellow],
      ['1', '5', '37', 'Rb', colors.red],
      ['2', '5', '38', 'Sr', colors.red],
      ['4', '5', '39', 'Y', colors.blue],
      ['5', '5', '40', 'Zr', colors.blue],
      ['6', '5', '41', 'Nb', colors.blue],
      ['7', '5', '42', 'Mo', colors.blue],
      ['8', '5', '43', 'Tc', colors.blue],
      ['9', '5', '44', 'Ru', colors.blue],
      ['10', '5', '45', 'Rh', colors.blue],
      ['11', '5', '46', 'Pd', colors.blue],
      ['12', '5', '47', 'Ag', colors.blue],
      ['13', '5', '48', 'Cd', colors.blue],
      ['14', '5', '49', 'In', colors.yellow],
      ['15', '5', '50', 'Sn', colors.yellow],
      ['16', '5', '51', 'Sb', colors.yellow],
      ['17', '5', '52', 'Te', colors.yellow],
      ['18', '5', '53', 'I', colors.yellow],
      ['19', '5', '54', 'Xe', colors.yellow],
      ['1', '6', '55', 'Cs', colors.red],
      ['2', '6', '56', 'Ba', colors.red],
      ['4', '9', '57', 'La', colors.green],
      ['5', '9', '58', 'Ce', colors.green],
      ['6', '9', '59', 'Pr', colors.green],
      ['7', '9', '60', 'Nd', colors.green],
      ['8', '9', '61', 'Pm', colors.green],
      ['9', '9', '62', 'Sm', colors.green],
      ['10', '9', '63', 'Eu', colors.green],
      ['11', '9', '64', 'Gd', colors.green],
      ['12', '9', '65', 'Tb', colors.green],
      ['13', '9', '66', 'Dy', colors.green],
      ['14', '9', '67', 'Ho', colors.green],
      ['15', '9', '68', 'Er', colors.green],
      ['16', '9', '69', 'Tm', colors.green],
      ['17', '9', '70', 'Yb', colors.green],
      ['4', '6', '71', 'Lu', colors.blue],
      ['5', '6', '72', 'Hf', colors.blue],
      ['6', '6', '73', 'Ta', colors.blue],
      ['7', '6', '74', 'W', colors.blue],
      ['8', '6', '75', 'Re', colors.blue],
      ['9', '6', '76', 'Os', colors.blue],
      ['10', '6', '77', 'Ir', colors.blue],
      ['11', '6', '78', 'Pt', colors.blue],
      ['12', '6', '79', 'Au', colors.blue],
      ['13', '6', '80', 'Hg', colors.blue],
      ['14', '6', '81', 'Tl', colors.yellow],
      ['15', '6', '82', 'Pb', colors.yellow],
      ['16', '6', '83', 'Bi', colors.yellow],
      ['17', '6', '84', 'Po', colors.yellow],
      ['18', '6', '85', 'At', colors.yellow],
      ['19', '6', '86', 'Rn', colors.yellow],
      ['1', '7', '87', 'Fr', colors.red],
      ['2', '7', '88', 'Ra', colors.red],
      ['4', '10', '89', 'Ac', colors.green],
      ['5', '10', '90', 'Th', colors.green],
      ['6', '10', '91', 'Pa', colors.green],
      ['7', '10', '92', 'U', colors.green],
      ['8', '10', '93', 'Np', colors.green],
      ['9', '10', '94', 'Pu', colors.green],
      ['10', '10', '95', 'Am', colors.green],
      ['11', '10', '96', 'Cm', colors.green],
      ['12', '10', '97', 'Bk', colors.green],
      ['13', '10', '98', 'Cf', colors.green],
      ['14', '10', '99', 'Es', colors.green],
      ['15', '10', '100', 'Fm', colors.green],
      ['16', '10', '101', 'Md', colors.green],
      ['17', '10', '102', 'No', colors.green],
      ['4', '7', '103', 'Lr', colors.blue],
      ['5', '7', '104', 'Rf', colors.blue],
      ['6', '7', '105', 'Db', colors.blue],
      ['7', '7', '106', 'Sg', colors.blue],
      ['8', '7', '107', 'Bh', colors.blue],
      ['9', '7', '108', 'Hs', colors.blue],
      ['10', '7', '109', 'Mt', colors.blue],
      ['11', '7', '110', 'Ds', colors.blue],
      ['12', '7', '111', 'Rg', colors.blue],
      ['13', '7', '112', 'Cn', colors.blue],
      ['14', '7', '113', 'Nh', colors.yellow],
      ['15', '7', '114', 'Fl', colors.yellow],
      ['16', '7', '115', 'Mc', colors.yellow],
      ['17', '7', '116', 'Lv', colors.yellow],
      ['18', '7', '117', 'Ts', colors.yellow],
      ['19', '7', '118', 'Og', colors.yellow],
      ['3', '6', null, 'La~Yb', colors.green],
      ['3', '7', null, 'Ac~No', colors.green]
    ],
    label: {
      show: true,
      formatter: (params) => {
        if (params.value[2] == null) {
          return '{small|' + params.value[3] + '}';
        }
        return params.value[2] + '\n' + params.value[3];
      },
      rich: {
        small: {
          fontSize: 12,
          color: '#777'
        }
      },
      textStyle: {
        fontSize: 14,
        color: '#555',
        align: 'center'
      }
    },
    renderItem: function (params, api) {
      const x = api.value(0);
      const y = api.value(1);
      const rect = api.layout([x, y]).rect;
      const isElement = !isNaN(api.value(2));
      const margin = 2;
      return {
        type: 'rect',
        shape: {
          x: rect.x + margin,
          y: rect.y + margin,
          width: rect.width - margin * 2,
          height: rect.height - margin * 2
        },
        style: api.style({
          fill: api.value(4),
          stroke: '#aaa',
          lineWidth: isElement ? 1 : 0,
          opacity: isElement ? 1 : 0.5
        })
      };
    }
  }
};
setTimeout(function () {
  const elements = [
    ['2', '9', 'Lanthanides', 20],
    ['2', '10', 'Actinides', 20],
    ['1', '1', 'Nonmetals', -70],
    ['1', '2', 'Metals', -70],
    ['19', '1', 'Noble gases', 0, -40],
    ['9', '3', 'Transition metals\n(somtimes excl. group 12)', -25],
    ['1', '8', 's-block\n(incl. He)', 20, -3],
    ['3', '8', 'f-block', 0, -10],
    ['9', '8', 'd-block', -25, -10],
    ['17', '8', 'p-block (excl. He)', -25, -10],
    [
      '16',
      '1',
      'Some elements near\nthe dashed staircase are\nsometimes called metalloids'
    ]
  ].map((row) => {
    const center = myChart.convertToPixel(
      {
        matrixIndex: 0
      },
      row.slice(0, 2)
    );
    return {
      type: 'text',
      style: {
        text: row[2],
        fill: '#333',
        font: 'italic bold 14px sans-serif',
        textAlign: 'center',
        textVerticalAlign: 'middle'
      },
      x: center[0] + (row[3] || 0),
      y: center[1] + (row[4] || 0)
    };
  });
  myChart.setOption({
    graphic: {
      elements
    }
  });
});
```
