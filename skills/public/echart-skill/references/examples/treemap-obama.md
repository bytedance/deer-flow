# treemap-obama

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=treemap-obama
**Chart Type:** `treemap`

## User Data Requirements

Columns needed: need nested **name+value** or **name+children**

## Data Arrays — Replacement Guide

The code contains **0 data array(s)** to replace:


## External Data Format

This example uses external data. Format from `obama_budget_proposal_2012.json`:

```json
[
  {
    "value": [
      1226629000,
      null,
      null
    ],
    "name": "Health and Human Services",
    "id": "branch-8",
    "discretion": null,
    "children": [
      {
        "value": [
          1105220000,
          1071808000,
          3.11734937600765
        ],
        "name": "Centers for Medicare and Medicaid Services",
        "id": "leaf-135",
        "discretion": "mandatory"
      },
      {
        "value": [
          34502000,
          34325000,
          0.5156591
...
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
title: How $3.7 Trillion is Spent
category: treemap
titleCN: 3.7 万亿美元支出构成
*/
myChart.showLoading();
const household_america_2012 = 113616229;
var obama_budget_2012 = [
  {
    "value": [
      1226629000,
      null,
      null
    ],
    "name": "Health and Human Services",
    "id": "branch-8",
    "discretion": null,
    "children": [
      {
        "value": [1105220000, 1071808000, 3.11734937600765],
        "name": "Centers for Medicare and Medicaid Services",
        "id": "leaf-135",
        "discretion": "mandatory"
      },
      {
        "value": [34502000, 34325000, 0.515659140568103],
        "name": "Administration for Children and Families",
        "id": "leaf-131",
        "discretion": "mandatory"
      },
      {
        "value": [31829000, 30784000, 3.39462058212059],
        "name": "National Institutes of Health",
        "id": "leaf-127",
        "discretion": "discretionary"
      },
      {
        "value": [16180000, 17334000, -6.65743625245183],
        "name": "Administration for Children and Families",
        "id": "leaf-118",
        "discretion": "discretionary"
      },
      {
        "value": [7324000, 6246000, 17.2590457893051],
        "name": "Centers for Medicare and Medicaid Services",
        "id": "leaf-121",
        "discretion": "discretionary"
      },
      {
        "value": [6821000, 7506000, -9.12603250732747],
        "name": "Health Resources and Services Administration",
        "id": "leaf-125",
        "discretion": "discretionary"
      },
      {
        "value": [5893000, 6467000, -8.8758311427246],
        "name": "Centers for Disease Control and Prevention",
        "id": "leaf-120",
        "discretion": "discretionary"
      },
      {
        "value": [4624000, 4053000, 14.0883296323711],
        "name": "Indian Health Services",
        "id": "leaf-126",
        "discretion": "discretionary"
      },
      {
        "value": [3387000, 3431000, -1.28242494899447],
        "name": "Substance Abuse and Mental Health Services Administration",
        "id": "leaf-130",
        "discretion": "discretionary"
      },
      {
        "value": [2744000, 2599000, 5.57906887264332],
        "name": "Food and Drug Administration",
        "id": "leaf-124",
        "discretion": "discretionary"
      },
      {
        "value": [2237000, 1513000, 47.8519497686715],
        "name": "Administration on Aging",
        "id": "leaf-119",
        "discretion": "discretionary"
      },
      {
        "value": [2155000, 707000, 204.809052333805],
        "name": "Health Resources and Services Administration",
        "id": "leaf-139",
        "discretion": "mandatory"
      },
      {
        "value": [1063000, 4554000, -76.6578831796223],
        "name": "Departmental Management",
        "id": "leaf-123",
        "discretion": "discretionary"
      },
      {
        "value": [809000, 297000, 172.390572390572],
        "name": "Centers for Disease Control and Prevention",
        "id": "leaf-134",
        "discretion": "mandatory"
      },
      {
        "value": [647000, 610000, 6.06557377049179],
        "name": "Program Support Center",
        "id": "leaf-143",
        "discretion": "mandatory"
      },
      {
        "value": [473000, 1047000, -54.8233046800382],
        "name": "Departmental Management",
        "id": "leaf-137",
        "discretion": "mandatory"
      },
      {
        "value": [210000, 10000, 2000],
        "name": "Administration on Aging",
        "id": "leaf-132",
        "discretion": "mandatory"
      },
      {
        "value": [166000, 166000, 0],
        "name": "National Institutes of Health",
        "id": "leaf-141",
        "discretion": "mandatory"
      },
      {
        "value": [158000, 158000, 0],
        "name": "Indian Health Services",
        "id": "leaf-140",
        "discretion": "mandatory"
      },
      {
        "value": [93000, 20000, 365],
        "name": "Substance Abuse and Mental Health Services Administration",
        "id": "leaf-144",
        "discretion": "mandatory"
      },
      {
        "value": [53000, 50000, 6.00000000000001],
        "name": "Office of the Inspector General",
        "id": "leaf-128",
        "discretion": "discretionary"
      },
      {
        "value": [39000, 36000, 8.33333333333333],
        "name": "Program Support Center",
        "id": "leaf-129",
        "discretion": "discretionary"
      },
      {
        "value": [2000, 2000, 0],
        "name": "Food and Drug Administration",
        "id": "leaf-138",
        "discretion": "mandatory"
      }
    ]
  },
  {
    "value": [
      818284000,
      null,
      null
    ],
    "name": "Social Security Administration",
    "id": "branch-34",
    "discretion": null,
    "children": [
      {
        "value": [808041000, 744812000, 8.48925634925324],
        "name": "Social Security Administration",
        "id": "leaf-531",
        "discretion": "mandatory"
      },
      {
        "value": [10243000, 9294000, 10.2108887454271],
        "name": "Social Security Administration",
        "id": "leaf-530",
        "discretion": "discretionary"
      }
    ]
  },
  {
    "value": [
      677483000,
      null,
      null
    ],
    "name": "Defense--Military Programs",
    "id": "branch-5",
    "discretion": null,
    "children": [
      {
        "value": [294891000, 292828000, 0.704509131640418],
        "name": "Operation and Maintenance",
        "id": "leaf-77",
        "discretion": "discretionary"
      },
      {
        "value": [154057000, 152586000, 0.964046504921812],
        "name": "Military Personnel",
        "id": "leaf-76",
        "discretion": "discretionary"
      },
      {
        "value": [128051000, 135819000, -5.71937652316686],
        "name": "Procurement",
        "id": "leaf-78",
        "discretion": "discretionary"
      },
      {
        "value": [75722000, 80232000, -5.62119852427959],
        "name": "Research, Development, Test, and Evaluation",
        "id": "leaf-79",
        "discretion": "discretionary"
      },
      {
        "value": [13073000, 22578000, -42.0985029674905],
        "name": "Military Construction",
        "id": "leaf-75",
        "discretion": "discretionary"
      },
      {
        "value": [5475000, 4516000, 21.2356067316209],
        "name": "Military Personnel",
        "id": "leaf-83",
        "discretion": "mandatory"
      },
      {
        "value": [3136000, 4159000, -24.5972589564799],
        "name": "Revolving and Management Funds",
        "id": "leaf-80",
        "discretion": "discretionary"
      },
      {
        "value": [1695000, 2267000, -25.2315835906484],
        "name": "Family Housing",
        "id": "leaf-74",
        "discretion": "discretionary"
      },
      {
        "value": [836000, 804000, 3.98009950248757],
        "name": "Operation and Maintenance",
        "id": "leaf-84",
        "discretion": "mandatory"
      },
      {
        "value": [447000, 756000, -40.8730158730159],
        "name": "Trust Funds",
        "id": "leaf-88",
        "discretion": "mandatory"
      },
      {
        "value": [
          100000,
          756000,
          null
        ],
        "name": "Research, Development, Test, and Evaluation",
        "id": "leaf-86",
        "discretion": "mandatory"
      }
    ]
  },
  {
    "value": [
      612004000,
      null,
      null
    ],
    "name": "Treasury",
    "id": "branch-15",
    "discretion": null,
    "children": [
      {
        "value": [474146000, 413955000, 14.5404693746905],
        "name": "Interest on the Public Debt",
        "id": "leaf-279",
        "discretion": "net interest"
      },
      {
        "value": [82053000, 110583000, -25.7996256205746],
        "name": "Internal Revenue Service",
        "id": "leaf-275",
        "discretion": "mandatory"
      },
      {
        "value": [24495000, 12679000, 93.1934695165234],
        "name": "Financial Management Service",
        "id": "leaf-278",
        "discretion": "net interest"
      },
      {
        "value": [13285000, 12147000, 9.36856837079114],
        "name": "Internal Revenue Service",
        "id": "leaf-269",
        "discretion": "discretionary"
      },
      {
        "value": [9495000, 15156000, -37.3515439429929],
        "name": "Departmental Offices",
        "id": "leaf-273",
        "discretion": "mandatory"
      },
      {
        "value": [3841000, 2192000, 75.228102189781],
        "name": "Financial Management Service",
        "id": "leaf-274",
        "discretion": "mandatory"
      },
      {
        "value": [3289000, 2177000, 51.0794671566376],
        "name": "Internal Revenue Service",
        "id": "leaf-280",
        "discretion": "net interest"
      },
      {
        "value": [510000, 378000, 34.9206349206349],
        "name": "Alcohol and Tobacco Tax and Trade Bureau",
        "id": "leaf-270",
        "discretion": "mandatory"
      },
      {
        "value": [219000, 244000, -10.2459016393443],
        "name": "Financial Management Service",
        "id": "leaf-268",
        "discretion": "discretionary"
      },
      {
        "value": [166000, 861000, -80.7200929152149],
        "name": "Departmental Offices",
        "id": "leaf-266",
        "discretion": "discretionary"
      },
      {
        "value": [166000, 185000, -10.2702702702703],
        "name": "Bureau of the Public Debt",
        "id": "leaf-264",
        "discretion": "discretionary"
      },
      {
        "value": [127000, 103000, 23.3009708737864],
        "name": "Bureau of the Public Debt",
        "id": "leaf-271",
        "discretion": "mandatory"
      },
      {
        "value": [114000, 111000, 2.7027027027027],
        "name": "Financial Crimes Enforcement Network",
        "id": "leaf-267",
        "discretion": "discretionary"
      },
      {
        "value": [98000, 103000, -4.85436893203883],
        "name": "Alcohol and Tobacco Tax and Trade Bureau",
        "id": "leaf-263",
        "discretion": "discretionary"
      }
    ]
  },
  {
    "value": [
      148349000,
      null,
      null
    ],
    "name": "Agriculture",
    "id": "branch-3",
    "discretion": null,
    "children": [
      {
        "value": [104212000, 85935000, 21.2684005352883],
        "name": "Food and Nutrition Service",
        "id": "leaf-39",
        "discretion": "mandatory"
      },
      {
        "value": [9801000, 10069000, -2.66163472042904],
        "name": "Farm Service Agency",
        "id": "leaf-38",
        "discretion": "mandatory"
      },
      {
        "value": [7765000, 8227000, -5.61565576759451],
        "name": "Food and Nutrition Service",
        "id": "leaf-14",
        "discretion": "discretionary"
      },
      {
        "value": [5125000, 5313000, -3.53849049501224],
        "name": "Forest Service",
        "id": "leaf-17",
        "discretion": "discretionary"
      },
      {
        "value": [4592000, 2939000, 56.2436202790065],
        "name": "Natural Resources Conservation Service",
        "id": "leaf-44",
        "discretion": "mandatory"
      },
      {
        "value": [2981000, 4547000, -34.4402903012976],
        "name": "Risk Management Agency",
        "id": "leaf-47",
        "discretion": "mandatory"
      },
      {
        "value": [2124000, 2376000, -10.6060606060606],
        "name": "Foreign Agricultural Service",
        "id": "leaf-16",
        "discretion": "discretionary"
      },
      {
        "value": [1777000, 2139000, -16.9237961664329],
        "name": "Farm Service Agency",
        "id": "leaf-13",
        "discretion": "discretionary"
      },
      {
        "value": [1446000, 1885000, -23.289124668435],
        "name": "Rural Housing Service",
        "id": "leaf-31",
        "discretion": "discretionary"
      },
      {
        "value": [1306000, 1276000, 2.35109717868338],
        "name": "Agricultural Marketing Service",
        "id": "leaf-33",
        "discretion": "mandatory"
      },
      {
        "value": [1209000, 1351000, -10.5107327905255],
        "name": "National Institute of Food and Agriculture",
        "id": "leaf-21",
        "discretion": "discretionary"
      },
      {
        "value": [1011000, 1019000, -0.785083415112853],
        "name": "Food Safety and Inspection Service",
        "id": "leaf-15",
        "discretion": "discretionary"
      },
      {
        "value": [914000, 1251000, -26.9384492406075],
        "name": "Agricultural Research Service",
        "id": "leaf-7",
        "discretion": "discretionary"
      },
      {
        "value": [838000, 949000, -11.6965226554268],
        "name": "Animal and Plant Health Inspection Service",
        "id": "leaf-8",
        "discretion": "discretionary"
      },
      {
        "value": [695000, 779000, -10.783055198973],
        "name": "Forest Service",
        "id": "leaf-42",
        "discretion": "mandatory"
      },
      {
        "value": [577000, 694000, -16.8587896253602],
        "name": "Rural Utilities Service",
        "id": "leaf-32",
        "discretion": "discretionary"
      },
      {
        "value": [412000, 431000, -4.40835266821346],
        "name": "Departmental Management",
        "id": "leaf-10",
        "discretion": "discretionary"
      },
      {
        "value": [264000, 320000, -17.5],
        "name": "Animal and Plant Health Inspection Service",
        "id": "leaf-35",
        "discretion": "mandatory"
      },
      {
        "value": [234000, 202000, 15.8415841584158],
        "name": "Rural Development",
        "id": "leaf-30",
        "discretion": "discretionary"
      },
      {
        "value": [175000, 384000, -54.4270833333333],
        "name": "Rural Business_Cooperative Service",
        "id": "leaf-48",
        "discretion": "mandatory"
      },
      {
        "value": [165000, 162000, 1.85185185185186],
        "name": "National Agricultural Statistics Service",
        "id": "leaf-19",
        "discretion": "discretionary"
      },
      {
        "value": [134000, 123000, 8.9430894308943],
        "name": "National Institute of Food and Agriculture",
        "id": "leaf-43",
        "discretion": "mandatory"
      },
      {
        "value": [99000, 93000, 6.4516129032258],
        "name": "Agricultural Marketing Service",
        "id": "leaf-6",
        "discretion": "discretionary"
      },
      {
        "value": [91000, 89000, 2.24719101123596],
        "name": "Office of the Inspector General",
        "id": "leaf-26",
        "discretion": "discretionary"
      },
      {
        "value": [86000, 82000, 4.87804878048781],
        "name": "Economic Research Service",
        "id": "leaf-11",
        "discretion": "discretionary"
      },
      {
        "value": [82000, 80000, 2.49999999999999],
        "name": "Risk Management Agency",
        "id": "leaf-28",
        "discretion": "discretionary"
      },
      {
        "value": [53000, 18000, 194.444444444444],
        "name": "Office of the Secretary",
        "id": "leaf-27",
        "discretion": "discretionary"
      },
      {
        "value": [46000, 44000, 4.54545454545454],
        "name": "Office of the General Counsel",
        "id": "leaf-25",
        "discretion": "discretionary"
      },
      {
        "value": [44000, 42000, 4.76190476190477],
        "name": "Grain Inspection, Packers and Stockyards Administration",
        "id": "leaf-18",
        "discretion": "discretionary"
      },
      {
        "value": [22000, 22000, 0],
        "name": "Departmental Management",
        "id": "leaf-37",
        "discretion": "mandatory"
      },
      {
        "value": [18000, 14000, 28.5714285714286],
        "name": "Agricultural Research Service",
        "id": "leaf-34",
        "discretion": "mandatory"
      },
      {
        "value": [15000, 15000, 0],
        "name": "National Appeals Division",
        "id": "leaf-20",
        "discretion": "discretionary"
      },
      {
        "value": [15000, 13000, 15.3846153846154],
        "name": "Office of Chief Economist",
        "id": "leaf-23",
        "discretion": "discretionary"
      },
      {
        "value": [10000, 10000, 0],
        "name": "Office of Communications",
        "id": "leaf-24",
        "discretion": "discretionary"
      },
      {
        "value": [9000, 10000, -10],
        "name": "Food Safety and Inspection Service",
        "id": "leaf-40",
        "discretion": "mandatory"
      },
      {
        "value": [1000, 1000, 0],
        "name": "Office of the Secretary",
        "id": "leaf-46",
        "discretion": "mandatory"
      },
      {
        "value": [1000, 1000, 0],
        "name": "Office of Chief Economist",
        "id": "leaf-45",
        "discretion": "mandatory"
      }
    ]
  },
  {
    "value": [
      132612000,
      null,
      null
    ],
    "name": "Labor",
    "id": "branch-12",
    "discretion": null,
    "children": [
      {
        "value": [117659000, 240093000, -50.9944063342122],
        "name": "Employment and Training Administration",
        "id": "leaf-218",
        "discretion": "mandatory"
      },
      {
        "value": [10000000, 10917000, -8.39974351928186],
        "name": "Employment and Training Administration",
        "id": "leaf-209",
        "discretion": "discretionary"
      },
      {
        "value": [2078000, 2217000, -6.26973387460532],
        "name": "Office of Workers' Compensation Programs",
        "id": "leaf-220",
        "discretion": "mandatory"
      },
      {
        "value": [583000, 559000, 4.29338103756709],
        "name": "Occupational Safety and Health Administration",
        "id": "leaf-212",
        "discretion": "discretionary"
      },
      {
        "value": [578000, 530000, 9.0566037735849],
        "name": "Bureau of Labor Statistics",
        "id": "leaf-205",
        "discretion": "discretionary"
      },
      {
        "value": [567000, 530000, 6.98113207547171],
        "name": "Departmental Management",
        "id": "leaf-207",
        "discretion": "discretionary"
      },
      {
        "value": [384000, 364000, 5.4945054945055],
        "name": "Mine Safety and Health Administration",
        "id": "leaf-211",
        "discretion": "discretionary"
      },
      {
        "value": [
          241000,
          364000,
          null
        ],
        "name": "Wage and Hour Division",
        "id": "leaf-216",
        "discretion": "discretionary"
      },
      {
        "value": [198000, 160000, 23.75],
        "name": "Employee Benefits Security Administration",
        "id": "leaf-208",
        "discretion": "discretionary"
      },
      {
        "value": [
          123000,
          160000,
          null
        ],
        "name": "Office of Workers' Compensation Programs",
        "id": "leaf-215",
        "discretion": "discretionary"
      },
      {
        "value": [
          109000,
          160000,
          null
        ],
        "name": "Office of Federal Contract Compliance Programs",
        "id": "leaf-213",
        "discretion": "discretionary"
      },
      {
        "value": [
          51000,
          160000,
          null
        ],
        "name": "Wage and Hour Division",
        "id": "leaf-221",
        "discretion": "mandatory"
      },
      {
        "value": [
          41000,
          160000,
          null
        ],
        "name": "Office of Labor Management Standards",
        "id": "leaf-214",
        "discretion": "discretionary"
      }
    ]
  },
  {
    "value": [
      132359000,
      null,
      null
    ],
    "name": "Veterans Affairs",
    "id": "branch-17",
    "discretion": null,
    "children": [
      {
        "value": [70477000, 71940000, -2.03363914373089],
        "name": "Benefits Programs",
        "id": "leaf-310",
        "discretion": "mandatory"
      },
      {
        "value": [54438000, 47966000, 13.4928907976483],
        "name": "Veterans Health Administration",
        "id": "leaf-309",
        "discretion": "discretionary"
      },
      {
        "value": [7259000, 7718000, -5.94713656387665],
        "name": "Departmental Administration",
        "id": "leaf-308",
        "discretion": "discretionary"
      },
      {
        "value": [156000, 233000, -33.0472103004292],
        "name": "Benefits Programs",
        "id": "leaf-306",
        "discretion": "discretionary"
      },
      {
        "value": [29000, 27000, 7.40740740740742],
        "name": "Veterans Health Administration",
        "id": "leaf-312",
        "discretion": "mandatory"
      }
    ]
  },
  {
    "value": [
      129458000,
      null,
      null
    ],
    "name": "Transportation",
    "id": "branch-16",
    "discretion": null,
    "children": [
      {
        "value": [70546000, 67815000, 4.02713264027132],
        "name": "Federal Highway Administration",
        "id": "leaf-297",
        "discretion": "mandatory"
      },
      {
        "value": [22201000, 9772000, 127.189930413426],
        "name": "Federal Transit Administration",
        "id": "leaf-300",
        "discretion": "mandatory"
      },
      {
        "value": [12883000, 12470000, 3.31194867682438],
        "name": "Federal Aviation Administration",
        "id": "leaf-282",
        "discretion": "discretionary"
      },
      {
        "value": [8046000, 15000, 53540],
        "name": "Federal Railroad Administration",
        "id": "leaf-299",
        "discretion": "mandatory"
      },
      {
        "value": [5774000, 3121000, 85.0048061518744],
        "name": "Federal Aviation Administration",
        "id": "leaf-296",
        "discretion": "mandatory"
      },
      {
        "value": [
          5000000,
          3121000,
          null
        ],
        "name": "National Infrastructure Bank",
        "id": "leaf-303",
        "discretion": "mandatory"
      },
      {
        "value": [2050000, 50000, 4000],
        "name": "Office of the Secretary",
        "id": "leaf-304",
        "discretion": "mandatory"
      },
      {
        "value": [860000, 696000, 23.5632183908046],
        "name": "National Highway Traffic Safety Administration",
        "id": "leaf-302",
        "discretion": "mandatory"
      },
      {
        "value": [606000, 536000, 13.0597014925373],
        "name": "Federal Motor Carrier Safety Administration",
        "id": "leaf-298",
        "discretion": "mandatory"
      },
      {
        "value": [303000, 413000, -26.634382566586],
        "name": "Maritime Administration",
        "id": "leaf-287",
        "discretion": "discretionary"
      },
      {
        "value": [290000, 890000, -67.4157303370787],
        "name": "Office of the Secretary",
        "id": "leaf-290",
        "discretion": "discretionary"
      },
      {
        "value": [192000, 164000, 17.0731707317073],
        "name": "Pipeline and Hazardous Materials Safety Administration",
        "id": "leaf-291",
        "discretion": "discretionary"
      },
      {
        "value": [183000, 4360000, -95.802752293578],
        "name": "Federal Railroad Administration",
        "id": "leaf-285",
        "discretion": "discretionary"
      },
      {
        "value": [175000, 226000, -22.5663716814159],
        "name": "Maritime Administration",
        "id": "leaf-301",
        "discretion": "mandatory"
      },
      {
        "value": [150000, 2389000, -93.7212222687317],
        "name": "Federal Transit Administration",
        "id": "leaf-286",
        "discretion": "discretionary"
      },
      {
        "value": [89000, 77000, 15.5844155844156],
        "name": "Office of Inspector General",
        "id": "leaf-289",
        "discretion": "discretionary"
      },
      {
        "value": [34000, 32000, 6.25],
        "name": "Saint Lawrence Seaway Development Corporation",
        "id": "leaf-293",
        "discretion": "discretionary"
      },
      {
        "value": [30000, 28000, 7.14285714285714],
        "name": "Surface Transportation Board",
        "id": "leaf-294",
        "discretion": "discretionary"
      },
      {
        "value": [28000, 23000, 21.7391304347826],
        "name": "Pipeline and Hazardous Materials Safety Administration",
        "id": "leaf-305",
        "discretion": "mandatory"
      },
      {
        "value": [18000, 13000, 38.4615384615385],
        "name": "Research and Innovative Technology Administration",
        "id": "leaf-292",
        "discretion": "discretionary"
      }
    ]
  },
  {
    "value": [
      93790000,
      null,
      null
    ],
    "name": "Education",
    "id": "branch-6",
    "discretion": null,
    "children": [
      {
        "value": [31433000, 20085000, 56.4998755290018],
        "name": "Office of Federal Student Aid",
        "id": "leaf-95",
        "discretion": "discretionary"
      },
      {
        "value": [20161000, 22495000, -10.3756390308958],
        "name": "Office of Elementary and Secondary Education",
        "id": "leaf-93",
        "discretion": "discretionary"
      },
      {
        "value": [12805000, 14290000, -10.3918824352694],
        "name": "Office of Federal Student Aid",
        "id": "leaf-103",
        "discretion": "mandatory"
      },
      {
        "value": [12647000, 13225000, -4.37051039697542],
        "name": "Office of Special Education and Rehabilitative Services",
        "id": "leaf-99",
        "discretion": "discretionary"
      },
      {
        "value": [4995000, 1378000, 262.481857764877],
        "name": "Office of Innovation and Improvement",
        "id": "leaf-96",
        "discretion": "discretionary"
      },
      {
        "value": [3122000, 3085000, 1.19935170178282],
        "name": "Office of Special Education and Rehabilitative Services",
        "id": "leaf-106",
        "discretion": "mandatory"
      },
      {
        "value": [2533000, 2512000, 0.835987261146487],
        "name": "Office of Postsecondary Education",
        "id": "leaf-97",
        "discretion": "discretionary"
      },
      {
        "value": [1781000, 393000, 353.180661577608],
        "name": "Office of Safe and Drug-Free Schools",
        "id": "leaf-98",
        "discretion": "discretionary"
      },
      {
        "value": [1683000, 2016000, -16.5178571428571],
        "name": "Office of Vocational and Adult Education",
        "id": "leaf-100",
        "discretion": "discretionary"
      },
      {
        "value": [760000, 659000, 15.3262518968134],
        "name": "Institute of Education Sciences",
        "id": "leaf-92",
        "discretion": "discretionary"
      },
      {
        "value": [750000, 750000, 0],
        "name": "Office of English Language Acquisition",
        "id": "leaf-94",
        "discretion": "discretionary"
      },
      {
        "value": [654000, 619000, 5.65428109854604],
        "name": "Departmental Management",
        "id": "leaf-91",
        "discretion": "discretionary"
      },
      {
        "value": [426000, 462000, -7.79220779220779],
        "name": "Office of Postsecondary Education",
        "id": "leaf-105",
        "discretion": "mandatory"
      },
      {
        "value": [
          40000,
          462000,
          null
        ],
        "name": "Office of Innovation and Improvement",
        "id": "leaf-104",
        "discretion": "mandatory"
      }
    ]
  },
  {
    "value": [
      83502000,
      null,
      null
    ],
    "name": "Office of Personnel Management",
    "id": "branch-28",
    "discretion": null,
    "children": [
      {
        "value": [83239000, 73691000, 12.9568061228644],
        "name": "Office of Personnel Management",
        "id": "leaf-403",
        "discretion": "mandatory"
      },
      {
        "value": [263000, 243000, 8.23045267489713],
        "name": "Office of Personnel Management",
        "id": "leaf-402",
        "discretion": "discretionary"
      }
    ]
  },
  {
    "value": [
      66476000,
      null,
      null
    ],
    "name": "Other",
    "id": "branch-29",
    "discretion": null,
    "children": [
      {
        "value": [18724000, 18725000, -0.00534045393858484],
        "name": "National Aeronautics and Space Administration",
        "id": "leaf-443",
        "discretion": "discretionary"
      },
      {
        "value": [
          10000000,
          18725000,
          null
        ],
        "name": "Allowances",
        "id": "leaf-476",
        "discretion": "mandatory"
      },
      {
        "value": [8973000, 10257000, -12.5182801988886],
        "name": "Environmental Protection Agency",
        "id": "leaf-424",
        "discretion": "discretionary"
      },
      {
        "value": [7768000, 6873000, 13.0219700276444],
        "name": "National Science Foundation",
        "id": "leaf-452",
        "discretion": "discretionary"
      },
      {
        "value": [5947000, 4449000, 33.6704877500562],
        "name": "Postal Service",
        "id": "leaf-499",
        "discretion": "mandatory"
      },
      {
        "value": [
          1900000,
          4449000,
          null
        ],
        "name": "National Credit Union Administration",
        "id": "leaf-495",
        "discretion": "mandatory"
      },
      {
        "value": [1259000, 1150000, 9.47826086956523],
        "name": "Corporation for National and Community Service",
        "id": "leaf-417",
        "discretion": "discretionary"
      },
      {
        "value": [1125000, 672000, 67.4107142857143],
        "name": "Tennessee Valley Authority",
        "id": "leaf-505",
        "discretion": "mandatory"
      },
      {
        "value": [1048000, 980000, 6.93877551020408],
        "name": "Smithsonian Institution",
        "id": "leaf-469",
        "discretion": "discretionary"
      },
      {
        "value": [984000, 1786000, -44.9048152295633],
        "name": "Small Business Administration",
        "id": "leaf-468",
        "discretion": "discretionary"
      },
      {
        "value": [767000, 750000, 2.26666666666666],
        "name": "Broadcasting Board of Governors",
        "id": "leaf-409",
        "discretion": "discretionary"
      },
      {
        "value": [592000, 705000, -16.0283687943262],
        "name": "Intelligence Community Management Account",
        "id": "leaf-437",
        "discretion": "discretionary"
      },
      {
        "value": [514000, 291000, 76.6323024054983],
        "name": "Central Intelligence Agency",
        "id": "leaf-480",
        "discretion": "mandatory"
      },
      {
        "value": [451000, 506000, -10.8695652173913],
        "name": "Corporation for Public Broadcasting",
        "id": "leaf-418",
        "discretion": "discretionary"
      },
      {
        "value": [450000, 420000, 7.14285714285714],
        "name": "Legal Services Corporation",
        "id": "leaf-439",
        "discretion": "discretionary"
      },
      {
        "value": [386000, 367000, 5.17711171662125],
        "name": "Equal Employment Opportunity Commission",
        "id": "leaf-425",
        "discretion": "discretionary"
      },
      {
        "value": [347000, 370000, -6.21621621621622],
        "name": "Postal Service",
        "id": "leaf-464",
        "discretion": "discretionary"
      },
      {
        "value": [333000, 375000, -11.2],
        "name": "Federal Drug Control Programs",
        "id": "leaf-427",
        "discretion": "discretionary"
      },
      {
        "value": [329000, 18000, 1727.77777777778],
        "name": "Bureau of Consumer Financial Protection",
        "id": "leaf-479",
        "discretion": "mandatory"
      },
      {
        "value": [288000, 417000, -30.9352517985611],
        "name": "Securities Investor Protection Corporation",
        "id": "leaf-501",
        "discretion": "mandatory"
      },
      {
        "value": [288000, 283000, 1.76678445229681],
        "name": "National Labor Relations Board",
        "id": "leaf-449",
        "discretion": "discretionary"
      },
      {
        "value": [258000, 249000, 3.6144578313253],
        "name": "Court Services and Offender Supervision Agency for the District",
        "id": "leaf-419",
        "discretion": "discretionary"
      },
      {
        "value": [248000, 90000, 175.555555555556],
        "name": "National Science Foundation",
        "id": "leaf-496",
        "discretion": "mandatory"
      },
      {
        "value": [243000, 282000, -13.8297872340426],
        "name": "Institute of Museum and Library Services",
        "id": "leaf-436",
        "discretion": "discretionary"
      },
      {
        "value": [227000, 143000, 58.7412587412587],
        "name": "Federal Housing Finance Agency",
        "id": "leaf-486",
        "discretion": "mandatory"
      },
      {
        "value": [216000, 216000, 0],
        "name": "Affordable Housing Program",
        "id": "leaf-475",
        "discretion": "mandatory"
      },
      {
        "value": [215000, 233000, -7.72532188841202],
        "name": "Neighborhood Reinvestment Corporation",
        "id": "leaf-454",
        "discretion": "discretionary"
      },
      {
        "value": [213000, 164000, 29.8780487804878],
        "name": "Public Company Accounting Oversight Board",
        "id": "leaf-500",
        "discretion": "mandatory"
      },
      {
        "value": [197000, 205000, -3.90243902439025],
        "name": "Federal Trade Commission",
        "id": "leaf-433",
        "discretion": "discretionary"
      },
      {
        "value": [191000, 169000, 13.0177514792899],
        "name": "Commodity Futures Trading Commission",
        "id": "leaf-415",
        "discretion": "discretionary"
      },
      {
        "value": [150000, 10000, 1400],
        "name": "Patient-Centered Outcomes Research Trust Fund",
        "id": "leaf-498",
        "discretion": "mandatory"
      },
      {
        "value": [146000, 168000, -13.0952380952381],
        "name": "National Endowment for the Humanities",
        "id": "leaf-448",
        "discretion": "discretionary"
      },
      {
        "value": [146000, 168000, -13.0952380952381],
        "name": "National Endowment for the Arts",
        "id": "leaf-447",
        "discretion": "discretionary"
      },
      {
        "value": [128000, 139000, -7.9136690647482],
        "name": "Nuclear Regulatory Commission",
        "id": "leaf-456",
        "discretion": "discretionary"
      },
      {
        "value": [122000, 118000, 3.38983050847457],
        "name": "Consumer Product Safety Commission",
        "id": "leaf-416",
        "discretion": "discretionary"
      },
      {
        "value": [102000, 98000, 4.08163265306123],
        "name": "National Transportation Safety Board",
        "id": "leaf-453",
        "discretion": "discretionary"
      },
      {
        "value": [100000, 100000, 0],
        "name": "Electric Reliability Organization",
        "id": "leaf-483",
        "discretion": "mandatory"
      },
      {
        "value": [
          100000,
          100000,
          null
        ],
        "name": "Corporation for Travel Promotion",
        "id": "leaf-482",
        "discretion": "mandatory"
      },
      {
        "value": [
          88000,
          100000,
          null
        ],
        "name": "Civilian Property Realignment Board",
        "id": "leaf-412",
        "discretion": "discretionary"
      },
      {
        "value": [87000, 81000, 7.40740740740742],
        "name": "International Trade Commission",
        "id": "leaf-438",
        "discretion": "discretionary"
      },
      {
        "value": [76000, 76000, 0],
        "name": "Appalachian Regional Commission",
        "id": "leaf-408",
        "discretion": "discretionary"
      },
      {
        "value": [67000, 67000, 0],
        "name": "Federal Election Commission",
        "id": "leaf-428",
        "discretion": "discretionary"
      },
      {
        "value": [56000, 27000, 107.407407407407],
        "name": "United States Court of Appeals for Veterans Claims",
        "id": "leaf-471",
        "discretion": "discretionary"
      },
      {
        "value": [53000, 49000, 8.16326530612246],
        "name": "United States Holocaust Memorial Museum",
        "id": "leaf-472",
        "discretion": "discretionary"
      },
      {
        "value": [48000, 47000, 2.12765957446808],
        "name": "Federal Mediation and Conciliation Service",
        "id": "leaf-431",
        "discretion": "discretionary"
      },
      {
        "value": [43000, 49000, -12.2448979591837],
        "name": "United States Institute of Peace",
        "id": "leaf-473",
        "discretion": "discretionary"
      },
      {
        "value": [42000, 40000, 5],
        "name": "Merit Systems Protection Board",
        "id": "leaf-441",
        "discretion": "discretionary"
      },
      {
        "value": [41000, 34000, 20.5882352941176],
        "name": "Standard Setting Body",
        "id": "leaf-503",
        "discretion": "mandatory"
      },
      {
        "value": [33000, 42000, -21.4285714285714],
        "name": "United Mine Workers of America Benefit Funds",
        "id": "leaf-507",
        "discretion": "mandatory"
      },
      {
        "value": [29000, 26000, 11.5384615384615],
        "name": "Defense Nuclear Facilities Safety Board",
        "id": "leaf-420",
        "discretion": "discretionary"
      },
      {
        "value": [26000, 24000, 8.33333333333333],
        "name": "Federal Maritime Commission",
        "id": "leaf-430",
        "discretion": "discretionary"
      },
      {
        "value": [26000, 25000, 4],
        "name": "Federal Labor Relations Authority",
        "id": "leaf-429",
        "discretion": "discretionary"
      },
      {
        "value": [22000, 19000, 15.7894736842105],
        "name": "National Railroad Passenger Corporation Office of Inspector Gene",
        "id": "leaf-451",
        "discretion": "discretionary"
      },
      {
        "value": [22000, 14000, 57.1428571428571],
        "name": "Federal Mine Safety and Health Review Commission",
        "id": "leaf-432",
        "discretion": "discretionary"
      },
      {
        "value": [20000, 14000, 42.8571428571429],
        "name": "Corporation for National and Community Service",
        "id": "leaf-481",
        "discretion": "mandatory"
      },
      {
        "value": [19000, 18000, 5.55555555555556],
        "name": "Office of Special Counsel",
        "id": "leaf-461",
        "discretion": "discretionary"
      },
      {
        "value": [16000, 19000, -15.7894736842105],
        "name": "Denali Commission",
        "id": "leaf-422",
        "discretion": "discretionary"
      },
      {
        "value": [14000, 13000, 7.69230769230769],
        "name": "National Mediation Board",
        "id": "leaf-450",
        "discretion": "discretionary"
      },
      {
        "value": [14000, 14000, 0],
        "name": "Office of Government Ethics",
        "id": "leaf-459",
        "discretion": "discretionary"
      },
      {
        "value": [13000, 13000, 0],
        "name": "Delta Regional Authority",
        "id": "leaf-421",
        "discretion": "discretionary"
      },
      {
        "value": [13000, 12000, 8.33333333333333],
        "name": "Occupational Safety and Health Review Commission",
        "id": "leaf-458",
        "discretion": "discretionary"
      },
      {
        "value": [12000, 23000, -47.8260869565217],
        "name": "Presidio Trust",
        "id": "leaf-465",
        "discretion": "discretionary"
      },
      {
        "value": [11000, 89000, -87.6404494382023],
        "name": "Election Assistance Commission",
        "id": "leaf-423",
        "discretion": "discretionary"
      },
      {
        "value": [11000, 11000, 0],
        "name": "Chemical Safety and Hazard Investigation Board",
        "id": "leaf-410",
        "discretion": "discretionary"
      },
      {
        "value": [10000, 8000, 25],
        "name": "Office of Navajo and Hopi Indian Relocation",
        "id": "leaf-460",
        "discretion": "discretionary"
      },
      {
        "value": [9000, 8000, 12.5],
        "name": "Institute of American Indian and Alaska Native Culture and Arts",
        "id": "leaf-435",
        "discretion": "discretionary"
      },
      {
        "value": [9000, 9000, 0],
        "name": "Commission on Civil Rights",
        "id": "leaf-414",
        "discretion": "discretionary"
      },
      {
        "value": [8000, 9000, -11.1111111111111],
        "name": "National Capital Planning Commission",
        "id": "leaf-444",
        "discretion": "discretionary"
      },
      {
        "value": [6000, 6000, 0],
        "name": "Advisory Council on Historic Preservation",
        "id": "leaf-406",
        "discretion": "discretionary"
      },
      {
        "value": [6000, 7000, -14.2857142857143],
        "name": "Morris K. Udall and Stewart L. Udall Foundation",
        "id": "leaf-442",
        "discretion": "discretionary"
      },
      {
        "value": [5000, 5000, 0],
        "name": "State Justice Institute",
        "id": "leaf-470",
        "discretion": "discretionary"
      },
      {
        "value": [4000, 2000, 100],
        "name": "United States Interagency Council on Homelessness",
        "id": "leaf-474",
        "discretion": "discretionary"
      },
      {
        "value": [4000, 4000, 0],
        "name": "Barry Goldwater Scholarship and Excellence in Education Foundati",
        "id": "leaf-477",
        "discretion": "mandatory"
      },
      {
        "value": [4000, 4000, 0],
        "name": "Office of the Fed Coordinator for Alaska Natural Gas Transportat",
        "id": "leaf-462",
        "discretion": "discretionary"
      },
      {
        "value": [3000, 2000, 50],
        "name": "Japan-United States Friendship Commission",
        "id": "leaf-491",
        "discretion": "mandatory"
      },
      {
        "value": [3000, 1000, 200],
        "name": "Harry S Truman Scholarship Foundation",
        "id": "leaf-489",
        "discretion": "mandatory"
      },
      {
        "value": [3000, 3000, 0],
        "name": "National Council on Disability",
        "id": "leaf-445",
        "discretion": "discretionary"
      },
      {
        "value": [3000, 3000, 0],
        "name": "Marine Mammal Commission",
        "id": "leaf-440",
        "discretion": "discretionary"
      },
      {
        "value": [3000, 4000, -25],
        "name": "Nuclear Waste Technical Review Board",
        "id": "leaf-457",
        "discretion": "discretionary"
      },
      {
        "value": [3000, 2000, 50],
        "name": "Administrative Conference of the United States",
        "id": "leaf-405",
        "discretion": "discretionary"
      },
      {
        "value": [2000, 2000, 0],
        "name": "Northern Border Regional Commission",
        "id": "leaf-455",
        "discretion": "discretionary"
      },
      {
        "value": [2000, 2000, 0],
        "name": "James Madison Memorial Fellowship Foundation",
        "id": "leaf-490",
        "discretion": "mandatory"
      },
      {
        "value": [2000, 1000, 100],
        "name": "National Credit Union Administration",
        "id": "leaf-446",
        "discretion": "discretionary"
      },
      {
        "value": [
          2000,
          1000,
          null
        ],
        "name": "Privacy and Civil Liberties Oversight Board",
        "id": "leaf-466",
        "discretion": "discretionary"
      },
      {
        "value": [2000, 12000, -83.3333333333333],
        "name": "Commission of Fine Arts",
        "id": "leaf-413",
        "discretion": "discretionary"
      },
      {
        "value": [2000, 1000, 100],
        "name": "United States Court of Appeals for Veterans Claims",
        "id": "leaf-508",
        "discretion": "mandatory"
      },
      {
        "value": [
          1000,
          1000,
          null
        ],
        "name": "Morris K. Udall and Stewart L. Udall Foundation",
        "id": "leaf-493",
        "discretion": "mandatory"
      },
      {
        "value": [1000, 1000, 0],
        "name": "Christopher Columbus Fellowship Foundation",
        "id": "leaf-411",
        "discretion": "discretionary"
      },
      {
        "value": [
          1000,
          1000,
          null
        ],
        "name": "Public Company Accounting Oversight Board",
        "id": "leaf-467",
        "discretion": "discretionary"
      },
      {
        "value": [1000, 1000, 0],
        "name": "Other Commissions and Boards",
        "id": "leaf-463",
        "discretion": "discretionary"
      }
    ]
  },
  {
    "value": [
      58663000,
      null,
      null
    ],
    "name": "Other Defense Civil Programs",
    "id": "branch-30",
    "discretion": null,
    "children": [
      {
        "value": [48455000, 51097000, -5.17055795839286],
        "name": "Military Retirement",
        "id": "leaf-520",
        "discretion": "mandatory"
      },
      {
        "value": [9917000, 8623000, 15.0063782906181],
        "name": "Retiree Health Care",
        "id": "leaf-521",
        "discretion": "mandatory"
      },
      {
        "value": [77000, 83000, -7.2289156626506],
        "name": "American Battle Monuments Commission",
        "id": "leaf-513",
        "discretion": "discretionary"
      },
      {
        "value": [
          76000,
          83000,
          null
        ],
        "name": "Educational Benefits",
        "id": "leaf-519",
        "discretion": "mandatory"
      },
      {
        "value": [68000, 134000, -49.2537313432836],
        "name": "Armed Forces Retirement Home",
        "id": "leaf-514",
        "discretion": "discretionary"
      },
      {
        "value": [46000, 40000, 15],
        "name": "Cemeterial Expenses",
        "id": "leaf-515",
        "discretion": "discretionary"
      },
      {
        "value": [24000, 24000, 0],
        "name": "Selective Service System",
        "id": "leaf-516",
        "discretion": "discretionary"
      }
    ]
  },
  {
    "value": [
      52092000,
      null,
      null
    ],
    "name": "Housing and Urban Development",
    "id": "branch-10",
    "discretion": null,
    "children": [
      {
        "value": [36186000, 34796000, 3.99471203586619],
        "name": "Public and Indian Housing Programs",
        "id": "leaf-178",
        "discretion": "discretionary"
      },
      {
        "value": [8211000, 8601000, -4.53435647017789],
        "name": "Community Planning and Development",
        "id": "leaf-169",
        "discretion": "discretionary"
      },
      {
        "value": [4484000, 3025000, 48.2314049586777],
        "name": "Housing Programs",
        "id": "leaf-182",
        "discretion": "mandatory"
      },
      {
        "value": [1791000, 2000000, -10.45],
        "name": "Management and Administration",
        "id": "leaf-174",
        "discretion": "discretionary"
      },
      {
        "value": [1001000, 4000, 24925],
        "name": "Community Planning and Development",
        "id": "leaf-179",
        "discretion": "mandatory"
      },
      {
        "value": [
          150000,
          4000,
          null
        ],
        "name": "Office of Sustainable Housing and Communities",
        "id": "leaf-176",
        "discretion": "discretionary"
      },
      {
        "value": [140000, 139000, 0.71942446043165],
        "name": "Office of Lead Hazard Control and Healthy Homes",
        "id": "leaf-175",
        "discretion": "discretionary"
      },
      {
        "value": [72000, 71000, 1.40845070422535],
        "name": "Fair Housing and Equal Opportunity",
        "id": "leaf-171",
        "discretion": "discretionary"
      },
      {
        "value": [57000, 48000, 18.75],
        "name": "Policy Development and Research",
        "id": "leaf-177",
        "discretion": "discretionary"
      }
    ]
  },
  {
    "value": [
      50045000,
      null,
      null
    ],
    "name": "Homeland Security",
    "id": "branch-9",
    "discretion": null,
    "children": [
      {
        "value": [10493000, 10323000, 1.64680809842099],
        "name": "Customs and Border Protection",
        "id": "leaf-147",
        "discretion": "discretionary"
      },
      {
        "value": [8935000, 8894000, 0.460984933663133],
        "name": "United States Coast Guard",
        "id": "leaf-158",
        "discretion": "discretionary"
      },
      {
        "value": [6790000, 12211000, -44.3943984931619],
        "name": "Federal Emergency Management Agency",
        "id": "leaf-151",
        "discretion": "discretionary"
      },
      {
        "value": [5495000, 5520000, -0.452898550724634],
        "name": "Immigration and Customs Enforcement",
        "id": "leaf-153",
        "discretion": "discretionary"
      },
      {
        "value": [5114000, 5515000, -7.27107887579329],
        "name": "Transportation Security Administration",
        "id": "leaf-157",
        "discretion": "discretionary"
      },
      {
        "value": [2534000, 2410000, 5.14522821576764],
        "name": "Citizenship and Immigration Services",
        "id": "leaf-160",
        "discretion": "mandatory"
      },
      {
        "value": [1699000, 1490000, 14.0268456375839],
        "name": "United States Secret Service",
        "id": "leaf-159",
        "discretion": "discretionary"
      },
      {
        "value": [1662000, 2233000, -25.5709807433945],
        "name": "United States Coast Guard",
        "id": "leaf-166",
        "discretion": "mandatory"
      },
      {
        "value": [1471000, 1295000, 13.5907335907336],
        "name": "Customs and Border Protection",
        "id": "leaf-161",
        "discretion": "mandatory"
      },
      {
        "value": [
          1428000,
          1295000,
          null
        ],
        "name": "National Protection and Programs Directorate",
        "id": "leaf-154",
        "discretion": "discretionary"
      },
      {
        "value": [1302000, 1133000, 14.9161518093557],
        "name": "Departmental Management and Operations",
        "id": "leaf-149",
        "discretion": "discretionary"
      },
      {
        "value": [1177000, 999000, 17.8178178178178],
        "name": "Science and Technology",
        "id": "leaf-156",
        "discretion": "discretionary"
      },
      {
        "value": [365000, 246000, 48.3739837398374],
        "name": "Citizenship and Immigration Services",
        "id": "leaf-146",
        "discretion": "discretionary"
      },
      {
        "value": [331000, 376000, -11.968085106383],
        "name": "Domestic Nuclear Detection Office",
        "id": "leaf-150",
        "discretion": "discretionary"
      },
      {
        "value": [311000, 275000, 13.0909090909091],
        "name": "Immigration and Customs Enforcement",
        "id": "leaf-164",
        "discretion": "mandatory"
      },
      {
        "value": [276000, 290000, -4.82758620689655],
        "name": "Federal Law Enforcement Training Center",
        "id": "leaf-152",
        "discretion": "discretionary"
      },
      {
        "value": [250000, 250000, 0],
        "name": "Transportation Security Administration",
        "id": "leaf-165",
        "discretion": "mandatory"
      },
      {
        "value": [245000, 244000, 0.409836065573765],
        "name": "United States Secret Service",
        "id": "leaf-167",
        "discretion": "mandatory"
      },
      {
        "value": [144000, 135000, 6.66666666666667],
        "name": "Office of the Inspector General",
        "id": "leaf-155",
        "discretion": "discretionary"
      },
      {
        "value": [
          23000,
          135000,
          null
        ],
        "name": "Federal Emergency Management Agency",
        "id": "leaf-163",
        "discretion": "mandatory"
      }
    ]
  },
  {
    "value": [
      41915000,
      null,
      null
    ],
    "name": "International Assistance Programs",
    "id": "branch-24",
    "discretion": null,
    "children": [
      {
        "value": [15965000, 14252000, 12.0193657030592],
        "name": "International Security Assistance",
        "id": "leaf-353",
        "discretion": "discretionary"
      },
      {
        "value": [14257000, 3257000, 337.734111145226],
        "name": "Military Sales Program",
        "id": "leaf-362",
        "discretion": "mandatory"
      },
      {
        "value": [6246000, 6127000, 1.94222294760895],
        "name": "Agency for International Development",
        "id": "leaf-350",
        "discretion": "discretionary"
      },
      {
        "value": [3713000, 3115000, 19.1974317817014],
        "name": "Multilateral Assistance",
        "id": "leaf-355",
        "discretion": "discretionary"
      },
      {
        "value": [1125000, 1055000, 6.6350710900474],
        "name": "Millennium Challenge Corporation",
        "id": "leaf-354",
        "discretion": "discretionary"
      },
      {
        "value": [440000, 400000, 10],
        "name": "Peace Corps",
        "id": "leaf-357",
        "discretion": "discretionary"
      },
      {
        "value": [70000, 20000, 250],
        "name": "Overseas Private Investment Corporation",
        "id": "leaf-363",
        "discretion": "mandatory"
      },
      {
        "value": [56000, 55000, 1.81818181818181],
        "name": "Trade and Development Agency",
        "id": "leaf-358",
        "discretion": "discretionary"
      },
      {
        "value": [24000, 30000, -20],
        "name": "African Development Foundation",
        "id": "leaf-349",
        "discretion": "discretionary"
      },
      {
        "value": [19000, 23000, -17.3913043478261],
        "name": "Inter-American Foundation",
        "id": "leaf-351",
        "discretion": "discretionary"
      }
    ]
  },
  {
    "value": [
      35403000,
      null,
      null
    ],
    "name": "Justice",
    "id": "branch-11",
    "discretion": null,
    "children": [
      {
        "value": [8076000, 7874000, 2.56540513081027],
        "name": "Federal Bureau of Investigation",
        "id": "leaf-188",
        "discretion": "discretionary"
      },
      {
        "value": [7808000, 774000, 908.785529715762],
        "name": "Office of Justice Programs",
        "id": "leaf-202",
        "discretion": "mandatory"
      },
      {
        "value": [6791000, 6205000, 9.44399677679291],
        "name": "Federal Prison System",
        "id": "leaf-189",
        "discretion": "discretionary"
      },
      {
        "value": [3909000, 4358000, -10.3028912345112],
        "name": "Legal Activities and U.S. Marshals",
        "id": "leaf-192",
        "discretion": "discretionary"
      },
      {
        "value": [2323000, 1646000, 41.1300121506683],
        "name": "Legal Activities and U.S. Marshals",
        "id": "leaf-201",
        "discretion": "mandatory"
      },
      {
        "value": [2293000, 2312000, -0.821799307958482],
        "name": "General Administration",
        "id": "leaf-190",
        "discretion": "discretionary"
      },
      {
        "value": [2012000, 2084000, -3.45489443378119],
        "name": "Drug Enforcement Administration",
        "id": "leaf-187",
        "discretion": "discretionary"
      },
      {
        "value": [1147000, 1158000, -0.949913644214162],
        "name": "Bureau of Alcohol, Tobacco, Firearms, and Explosives",
        "id": "leaf-185",
        "discretion": "discretionary"
      },
      {
        "value": [541000, 548000, -1.27737226277372],
        "name": "Interagency Law Enforcement",
        "id": "leaf-191",
        "discretion": "discretionary"
      },
      {
        "value": [282000, 272000, 3.6764705882353],
        "name": "Drug Enforcement Administration",
        "id": "leaf-198",
        "discretion": "mandatory"
      },
      {
        "value": [120000, 120000, 0],
        "name": "Radiation Exposure Compensation",
        "id": "leaf-203",
        "discretion": "mandatory"
      },
      {
        "value": [88000, 88000, 0],
        "name": "National Security Division",
        "id": "leaf-193",
        "discretion": "discretionary"
      },
      {
        "value": [13000, 13000, 0],
        "name": "United States Parole Commission",
        "id": "leaf-195",
        "discretion": "discretionary"
      }
    ]
  },
  {
    "value": [
      32746000,
      null,
      null
    ],
    "name": "State",
    "id": "branch-13",
    "discretion": null,
    "children": [
      {
        "value": [14747000, 12367000, 19.2447642920676],
        "name": "Administration of Foreign Affairs",
        "id": "leaf-223",
        "discretion": "discretionary"
      },
      {
        "value": [13080000, 12954000, 0.972672533580354],
        "name": "Other",
        "id": "leaf-227",
        "discretion": "discretionary"
      },
      {
        "value": [3539000, 3905000, -9.37259923175416],
        "name": "International Organizations and Conferences",
        "id": "leaf-226",
        "discretion": "discretionary"
      },
      {
        "value": [1257000, 1266000, -0.710900473933651],
        "name": "Administration of Foreign Affairs",
        "id": "leaf-228",
        "discretion": "mandatory"
      },
      {
        "value": [122000, 143000, -14.6853146853147],
        "name": "International Commissions",
        "id": "leaf-225",
        "discretion": "discretionary"
      },
      {
        "value": [1000, 4000, -75],
        "name": "Other",
        "id": "leaf-230",
        "discretion": "mandatory"
      }
    ]
  },
  {
    "value": [
      30779000,
      null,
      null
    ],
    "name": "Energy",
    "id": "branch-7",
    "discretion": null,
    "children": [
      {
        "value": [11836000, 8610000, 37.4680603948897],
        "name": "Energy Programs",
        "id": "leaf-110",
        "discretion": "discretionary"
      },
      {
        "value": [11712000, 9881000, 18.5305131059609],
        "name": "National Nuclear Security Administration",
        "id": "leaf-112",
        "discretion": "discretionary"
      },
      {
        "value": [6267000, 6585000, -4.82915717539863],
        "name": "Environmental and Other Defense Activities",
        "id": "leaf-111",
        "discretion": "discretionary"
      },
      {
        "value": [604000, 785000, -23.0573248407643],
        "name": "Power Marketing Administration",
        "id": "leaf-116",
        "discretion": "mandatory"
      },
      {
        "value": [171000, 256000, -33.203125],
        "name": "Departmental Administration",
        "id": "leaf-109",
        "discretion": "discretionary"
      },
      {
        "value": [103000, 62000, 66.1290322580645],
        "name": "Energy Programs",
        "id": "leaf-115",
        "discretion": "mandatory"
      },
      {
        "value": [86000, 150000, -42.6666666666667],
        "name": "Power Marketing Administration",
        "id": "leaf-113",
        "discretion": "discretionary"
      }
    ]
  },
  {
    "value": [
      17863000,
      null,
      null
    ],
    "name": "Interior",
    "id": "branch-14",
    "discretion": null,
    "children": [
      {
        "value": [2892000, 2770000, 4.40433212996389],
        "name": "National Park Service",
        "id": "leaf-241",
        "discretion": "discretionary"
      },
      {
        "value": [2501000, 2612000, -4.24961715160797],
        "name": "Bureau of Indian Affairs and Bureau of Indian Education",
        "id": "leaf-232",
        "discretion": "discretionary"
      },
      {
        "value": [2117000, 1775000, 19.2676056338028],
        "name": "Departmental Offices",
        "id": "leaf-254",
        "discretion": "mandatory"
      },
      {
        "value": [1695000, 1648000, 2.85194174757282],
        "name": "United States Fish and Wildlife Service",
        "id": "leaf-246",
        "discretion": "discretionary"
      },
      {
        "value": [1132000, 1156000, -2.07612456747405],
        "name": "Bureau of Land Management",
        "id": "leaf-233",
        "discretion": "discretionary"
      },
      {
        "value": [1118000, 1112000, 0.539568345323738],
        "name": "United States Geological Survey",
        "id": "leaf-247",
        "discretion": "discretionary"
      },
      {
        "value": [1018000, 1098000, -7.28597449908925],
        "name": "Bureau of Reclamation",
        "id": "leaf-235",
        "discretion": "discretionary"
      },
      {
        "value": [996000, 1362000, -26.8722466960352],
        "name": "United States Fish and Wildlife Service",
        "id": "leaf-260",
        "discretion": "mandatory"
      },
      {
        "value": [911000, 960000, -5.10416666666667],
        "name": "Department-Wide Programs",
        "id": "leaf-238",
        "discretion": "discretionary"
      },
      {
        "value": [538000, 542000, -0.738007380073802],
        "name": "Office of Surface Mining Reclamation and Enforcement",
        "id": "leaf-258",
        "discretion": "mandatory"
      },
      {
        "value": [437000, 626000, -30.1916932907348],
        "name": "Department-Wide Programs",
        "id": "leaf-253",
        "discretion": "mandatory"
      },
      {
        "value": [405000, 429000, -5.59440559440559],
        "name": "Insular Affairs",
        "id": "leaf-255",
        "discretion": "mandatory"
      },
      {
        "value": [395000, 393000, 0.508905852417296],
        "name": "National Park Service",
        "id": "leaf-257",
        "discretion": "mandatory"
      },
      {
        "value": [358000, 482000, -25.7261410788382],
        "name": "Office of the Special Trustee for American Indians",
        "id": "leaf-259",
        "discretion": "mandatory"
      },
      {
        "value": [242000, 138000, 75.3623188405797],
        "name": "Departmental Offices",
        "id": "leaf-239",
        "discretion": "discretionary"
      },
      {
        "value": [194000, 104000, 86.5384615384615],
        "name": "Bureau of Reclamation",
        "id": "leaf-251",
        "discretion": "mandatory"
      },
      {
        "value": [152000, 177000, -14.1242937853107],
        "name": "Office of the Special Trustee for American Indians",
        "id": "leaf-245",
        "discretion": "discretionary"
      },
      {
        "value": [146000, 163000, -10.4294478527607],
        "name": "Office of Surface Mining Reclamation and Enforcement",
        "id": "leaf-243",
        "discretion": "discretionary"
      },
      {
        "value": [133000, 208000, -36.0576923076923],
        "name": "Bureau of Land Management",
        "id": "leaf-249",
        "discretion": "mandatory"
      },
      {
        "value": [132000, 191000, -30.8900523560209],
        "name": "Bureau of Ocean Energy Management, Regulation and Enforcement",
        "id": "leaf-234",
        "discretion": "discretionary"
      },
      {
        "value": [106000, 121000, -12.396694214876],
        "name": "Bureau of Indian Affairs and Bureau of Indian Education",
        "id": "leaf-248",
        "discretion": "mandatory"
      },
      {
        "value": [69000, 60000, 15],
        "name": "Insular Affairs",
        "id": "leaf-240",
        "discretion": "discretionary"
      },
      {
        "value": [68000, 65000, 4.61538461538462],
        "name": "Office of the Solicitor",
        "id": "leaf-244",
        "discretion": "discretionary"
      },
      {
        "value": [49000, 49000, 0],
        "name": "Office of Inspector General",
        "id": "leaf-242",
        "discretion": "discretionary"
      },
      {
        "value": [33000, 52000, -36.5384615384615],
        "name": "Central Utah Project",
        "id": "leaf-236",
        "discretion": "discretionary"
      },
      {
        "value": [17000, 13000, 30.7692307692308],
        "name": "National Indian Gaming Commission",
        "id": "leaf-256",
        "discretion": "mandatory"
      },
      {
        "value": [8000, 21000, -61.9047619047619],
        "name": "Bureau of Ocean Energy Management, Regulation and Enforcement",
        "id": "leaf-250",
        "discretion": "mandatory"
      },
      {
        "value": [1000, 2000, -50],
        "name": "United States Geological Survey",
        "id": "leaf-261",
        "discretion": "mandatory"
      }
    ]
  },
  {
    "value": [
      11570000,
      null,
      null
    ],
    "name": "Federal Communications Commission",
    "id": "branch-20",
    "discretion": null,
    "children": [
      {
        "value": [11570000, 8918000, 29.7376093294461],
        "name": "Federal Communications Commission",
        "id": "leaf-334",
        "discretion": "mandatory"
      }
    ]
  },
  {
    "value": [
      10449000,
      null,
      null
    ],
    "name": "Commerce",
    "id": "branch-4",
    "discretion": null,
    "children": [
      {
        "value": [5510000, 4878000, 12.9561295612956],
        "name": "National Oceanic and Atmospheric Administration",
        "id": "leaf-61",
        "discretion": "discretionary"
      },
      {
        "value": [1400000, 197000, 610.659898477157],
        "name": "National Telecommunications and Information Administration",
        "id": "leaf-71",
        "discretion": "mandatory"
      },
      {
        "value": [1025000, 7096000, -85.5552423900789],
        "name": "Bureau of the Census",
        "id": "leaf-53",
        "discretion": "discretionary"
      },
      {
        "value": [1004000, 863000, 16.3383545770568],
        "name": "National Institute of Standards and Technology",
        "id": "leaf-60",
        "discretion": "discretionary"
      },
      {
        "value": [517000, 448000, 15.4017857142857],
        "name": "International Trade Administration",
        "id": "leaf-58",
        "discretion": "discretionary"
      },
      {
        "value": [325000, 347000, -6.34005763688761],
        "name": "Economic Development Administration",
        "id": "leaf-57",
        "discretion": "discretionary"
      },
      {
        "value": [113000, 97000, 16.4948453608248],
        "name": "Economic and Statistical Analysis",
        "id": "leaf-56",
        "discretion": "discretionary"
      },
      {
        "value": [111000, 58000, 91.3793103448276],
        "name": "National Oceanic and Atmospheric Administration",
        "id": "leaf-70",
        "discretion": "mandatory"
      },
      {
        "value": [111000, 100000, 11],
        "name": "Bureau of Industry and Security",
        "id": "leaf-52",
        "discretion": "discretionary"
      },
      {
        "value": [
          100000,
          100000,
          null
        ],
        "name": "National Institute of Standards and Technology",
        "id": "leaf-69",
        "discretion": "mandatory"
      },
      {
        "value": [95000, 109000, -12.8440366972477],
        "name": "Departmental Management",
        "id": "leaf-55",
        "discretion": "discretionary"
      },
      {
        "value": [
          50000,
          109000,
          null
        ],
        "name": "National Telecommunications and Information Administration",
        "id": "leaf-62",
        "discretion": "discretionary"
      },
      {
        "value": [32000, 32000, 0],
        "name": "Minority Business Development Agency",
        "id": "leaf-59",
        "discretion": "discretionary"
      },
      {
        "value": [30000, 30000, 0],
        "name": "Bureau of the Census",
        "id": "leaf-64",
        "discretion": "mandatory"
      },
      {
        "value": [
          20000,
          30000,
          null
        ],
        "name": "Economic Development Administration",
        "id": "leaf-67",
        "discretion": "mandatory"
      },
      {
        "value": [5000, 5000, 0],
        "name": "International Trade Administration",
        "id": "leaf-68",
        "discretion": "mandatory"
      },
      {
        "value": [1000, 1000, 0],
        "name": "Departmental Management",
        "id": "leaf-66",
        "discretion": "mandatory"
      }
    ]
  },
  {
    "value": [
      8284000,
      null,
      null
    ],
    "name": "Judicial Branch",
    "id": "branch-25",
    "discretion": null,
    "children": [
      {
        "value": [6580000, 6175000, 6.55870445344129],
        "name": "Courts of Appeals, District Courts, and other Judicial Services",
        "id": "leaf-366",
        "discretion": "discretionary"
      },
      {
        "value": [1177000, 1141000, 3.15512708150745],
        "name": "Courts of Appeals, District Courts, and other Judicial Services",
        "id": "leaf-372",
        "discretion": "mandatory"
      },
      {
        "value": [248000, 197000, 25.8883248730964],
        "name": "Judicial Retirement Funds",
        "id": "leaf-374",
        "discretion": "mandatory"
      },
      {
        "value": [89000, 83000, 7.2289156626506],
        "name": "Administrative Office of the United States Courts",
        "id": "leaf-365",
        "discretion": "discretionary"
      },
      {
        "value": [83000, 87000, -4.59770114942529],
        "name": "Supreme Court of the United States",
        "id": "leaf-368",
        "discretion": "discretionary"
      },
      {
        "value": [33000, 29000, 13.7931034482759],
        "name": "United States Court of Appeals for the Federal Circuit",
        "id": "leaf-369",
        "discretion": "discretionary"
      },
      {
        "value": [29000, 27000, 7.40740740740742],
        "name": "Federal Judicial Center",
        "id": "leaf-367",
        "discretion": "discretionary"
      },
      {
        "value": [21000, 19000, 10.5263157894737],
        "name": "United States Court of International Trade",
        "id": "leaf-370",
        "discretion": "discretionary"
      },
      {
        "value": [18000, 17000, 5.88235294117647],
        "name": "United States Sentencing Commission",
        "id": "leaf-371",
        "discretion": "discretionary"
      },
      {
        "value": [2000, 2000, 0],
        "name": "United States Court of Appeals for the Federal Circuit",
        "id": "leaf-376",
        "discretion": "mandatory"
      },
      {
        "value": [2000, 2000, 0],
        "name": "Supreme Court of the United States",
        "id": "leaf-375",
        "discretion": "mandatory"
      },
      {
        "value": [2000, 2000, 0],
        "name": "United States Court of International Trade",
        "id": "leaf-377",
        "discretion": "mandatory"
      }
    ]
  },
  {
    "value": [
      7115000,
      null,
      null
    ],
    "name": "Railroad Retirement Board",
    "id": "branch-31",
    "discretion": null,
    "children": [
      {
        "value": [6945000, 6864000, 1.18006993006994],
        "name": "Railroad Retirement Board",
        "id": "leaf-524",
        "discretion": "mandatory"
      },
      {
        "value": [170000, 181000, -6.07734806629834],
        "name": "Railroad Retirement Board",
        "id": "leaf-523",
        "discretion": "discretionary"
      }
    ]
  },
  {
    "value": [
      5173000,
      null,
      null
    ],
    "name": "Legislative Branch",
    "id": "branch-26",
    "discretion": null,
    "children": [
      {
        "value": [1334000, 1369000, -2.55661066471877],
        "name": "House of Representatives",
        "id": "leaf-384",
        "discretion": "discretionary"
      },
      {
        "value": [971000, 918000, 5.77342047930283],
        "name": "Senate",
        "id": "leaf-389",
        "discretion": "discretionary"
      },
      {
        "value": [694000, 590000, 17.6271186440678],
        "name": "Architect of the Capitol",
        "id": "leaf-378",
        "discretion": "discretionary"
      },
      {
        "value": [667000, 642000, 3.89408099688473],
        "name": "Library of Congress",
        "id": "leaf-387",
        "discretion": "discretionary"
      },
      {
        "value": [557000, 558000, -0.179211469534046],
        "name": "Government Accountability Office",
        "id": "leaf-382",
        "discretion": "discretionary"
      },
      {
        "value": [387000, 342000, 13.1578947368421],
        "name": "Capitol Police",
        "id": "leaf-380",
        "discretion": "discretionary"
      },
      {
        "value": [148000, 148000, 0],
        "name": "Government Printing Office",
        "id": "leaf-383",
        "discretion": "discretionary"
      },
      {
        "value": [130000, 57000, 128.070175438596],
        "name": "Legislative Branch Boards and Commissions",
        "id": "leaf-386",
        "discretion": "discretionary"
      },
      {
        "value": [101000, 110000, -8.18181818181818],
        "name": "House of Representatives",
        "id": "leaf-392",
        "discretion": "mandatory"
      },
      {
        "value": [60000, 49000, 22.4489795918367],
        "name": "United States Tax Court",
        "id": "leaf-390",
        "discretion": "discretionary"
      },
      {
        "value": [47000, 45000, 4.44444444444445],
        "name": "Congressional Budget Office",
        "id": "leaf-381",
        "discretion": "discretionary"
      },
      {
        "value": [33000, 33000, 0],
        "name": "Senate",
        "id": "leaf-396",
        "discretion": "mandatory"
      },
      {
        "value": [20000, 21000, -4.76190476190477],
        "name": "Joint Items",
        "id": "leaf-385",
        "discretion": "discretionary"
      },
      {
        "value": [12000, 11000, 9.09090909090908],
        "name": "Botanic Garden",
        "id": "leaf-379",
        "discretion": "discretionary"
      },
      {
        "value": [6000, 9000, -33.3333333333333],
        "name": "Library of Congress",
        "id": "leaf-395",
        "discretion": "mandatory"
      },
      {
        "value": [5000, 4000, 25],
        "name": "Office of Compliance",
        "id": "leaf-388",
        "discretion": "discretionary"
      },
      {
        "value": [
          1000,
          4000,
          null
        ],
        "name": "United States Tax Court",
        "id": "leaf-397",
        "discretion": "mandatory"
      }
    ]
  },
  {
    "value": [
      4584000,
      null,
      null
    ],
    "name": "Corps of Engineers--Civil Works",
    "id": "branch-2",
    "discretion": null,
    "children": [
      {
        "value": [4574000, 5739000, -20.2997037811465],
        "name": "Corps of Engineers--Civil Works",
        "id": "leaf-3",
        "discretion": "discretionary"
      },
      {
        "value": [
          10000,
          5739000,
          null
        ],
        "name": "Corps of Engineers--Civil Works",
        "id": "leaf-4",
        "discretion": "mandatory"
      }
    ]
  },
  {
    "value": [
      1070000,
      null,
      null
    ],
    "name": "District of Columbia",
    "id": "branch-18",
    "discretion": null,
    "children": [
      {
        "value": [603000, 523000, 15.2963671128107],
        "name": "District of Columbia General and Special Payments",
        "id": "leaf-317",
        "discretion": "mandatory"
      },
      {
        "value": [284000, 316000, -10.126582278481],
        "name": "District of Columbia Courts",
        "id": "leaf-314",
        "discretion": "discretionary"
      },
      {
        "value": [174000, 186000, -6.45161290322581],
        "name": "District of Columbia General and Special Payments",
        "id": "leaf-315",
        "discretion": "discretionary"
      },
      {
        "value": [9000, 8000, 12.5],
        "name": "District of Columbia Courts",
        "id": "leaf-316",
        "discretion": "mandatory"
      }
    ]
  },
  {
    "value": [
      915000,
      null,
      null
    ],
    "name": "Federal Deposit Insurance Corporation",
    "id": "branch-21",
    "discretion": null,
    "children": [
      {
        "value": [
          855000,
          null,
          null
        ],
        "name": "Orderly Liquidation",
        "id": "leaf-340",
        "discretion": "mandatory"
      },
      {
        "value": [45000, 33000, 36.3636363636364],
        "name": "FDIC_Office of Inspector General",
        "id": "leaf-337",
        "discretion": "discretionary"
      },
      {
        "value": [15000, 27000, -44.4444444444444],
        "name": "FSLIC Resolution",
        "id": "leaf-339",
        "discretion": "mandatory"
      }
    ]
  },
  {
    "value": [
      653000,
      null,
      null
    ],
    "name": "General Services Administration",
    "id": "branch-23",
    "discretion": null,
    "children": [
      {
        "value": [332000, 267000, 24.3445692883895],
        "name": "General Activities",
        "id": "leaf-342",
        "discretion": "discretionary"
      },
      {
        "value": [286000, 10000, 2760],
        "name": "Real Property Activities",
        "id": "leaf-344",
        "discretion": "discretionary"
      },
      {
        "value": [13000, 13000, 0],
        "name": "Supply and Technology Activities",
        "id": "leaf-348",
        "discretion": "mandatory"
      },
      {
        "value": [12000, 11000, 9.09090909090908],
        "name": "General Activities",
        "id": "leaf-345",
        "discretion": "mandatory"
      },
      {
        "value": [10000, 3000, 233.333333333333],
        "name": "Real Property Activities",
        "id": "leaf-347",
        "discretion": "mandatory"
      }
    ]
  },
  {
    "value": [
      569000,
      null,
      null
    ],
    "name": "Executive Office of the President",
    "id": "branch-19",
    "discretion": null,
    "children": [
      {
        "value": [116000, 115000, 0.869565217391299],
        "name": "Office of Administration",
        "id": "leaf-323",
        "discretion": "discretionary"
      },
      {
        "value": [
          100000,
          115000,
          null
        ],
        "name": "Unanticipated Needs",
        "id": "leaf-332",
        "discretion": "mandatory"
      },
      {
        "value": [92000, 93000, -1.0752688172043],
        "name": "Office of Management and Budget",
        "id": "leaf-324",
        "discretion": "discretionary"
      },
      {
        "value": [81000, 39000, 107.692307692308],
        "name": "Unanticipated Needs",
        "id": "leaf-330",
        "discretion": "discretionary"
      },
      {
        "value": [59000, 60000, -1.66666666666667],
        "name": "The White House",
        "id": "leaf-329",
        "discretion": "discretionary"
      },
      {
        "value": [51000, 48000, 6.25],
        "name": "Office of the United States Trade Representative",
        "id": "leaf-327",
        "discretion": "discretionary"
      },
      {
        "value": [23000, 30000, -23.3333333333333],
        "name": "Office of National Drug Control Policy",
        "id": "leaf-325",
        "discretion": "discretionary"
      },
      {
        "value": [15000, 17000, -11.7647058823529],
        "name": "Executive Residence at the White House",
        "id": "leaf-321",
        "discretion": "discretionary"
      },
      {
        "value": [13000, 12000, 8.33333333333333],
        "name": "National Security Council and Homeland Security Council",
        "id": "leaf-322",
        "discretion": "discretionary"
      },
      {
        "value": [7000, 7000, 0],
        "name": "Office of Science and Technology Policy",
        "id": "leaf-326",
        "discretion": "discretionary"
      },
      {
        "value": [5000, 5000, 0],
        "name": "Special Assistance to the President and the Official Residence",
        "id": "leaf-328",
        "discretion": "discretionary"
      },
      {
        "value": [4000, 4000, 0],
        "name": "Council of Economic Advisers",
        "id": "leaf-319",
        "discretion": "discretionary"
      },
      {
        "value": [3000, 3000, 0],
        "name": "Council on Environmental Quality and Office of Environmental Qua",
        "id": "leaf-320",
        "discretion": "discretionary"
      }
    ]
  },
  {
    "value": [
      407000,
      null,
      null
    ],
    "name": "National Archives and Records Administration",
    "id": "branch-27",
    "discretion": null,
    "children": [
      {
        "value": [407000, 458000, -11.1353711790393],
        "name": "National Archives and Records Administration",
        "id": "leaf-399",
        "discretion": "discretionary"
      }
    ]
  },
  {
    "value": [
      32000,
      null,
      null
    ],
    "name": "Recovery Accountability and Transparency Board",
    "id": "branch-32",
    "discretion": null,
    "children": [
      {
        "value": [
          32000,
          null,
          null
        ],
        "name": "Recovery Act Accountability and Transparency Board",
        "id": "leaf-526",
        "discretion": "discretionary"
      }
    ]
  },
  {
    "value": [
      7000,
      null,
      null
    ],
    "name": "Access Board",
    "id": "branch-0",
    "discretion": null,
    "children": [
      {
        "value": [7000, 7000, 0],
        "name": "Architectural and Transportation Barriers Compliance Board",
        "id": "leaf-1",
        "discretion": "discretionary"
      }
    ]
  },
  {
    "value": [
      6000,
      null,
      null
    ],
    "name": "Committee for Purchase from People Who Are Blind or Severely Dis",
    "id": "branch-1",
    "discretion": null,
    "children": [
      {
        "value": [6000, 5000, 20],
        "name": "Committee for Purchase from People who are Blind or Severely Dis",
        "id": "leaf-2",
        "discretion": "discretionary"
      }
    ]
  },
  {
    "value": [
      2000,
      null,
      null
    ],
    "name": "Federal Financial Institutions Examination Council",
    "id": "branch-22",
    "discretion": null,
    "children": [
      {
        "value": [2000, 3000, -33.3333333333333],
        "name": "Federal Financial Institutions Examination Council Appraisal Sub",
        "id": "leaf-341",
        "discretion": "mandatory"
      }
    ]
  },
  {
    "value": [
      0,
      null,
      null
    ],
    "name": "Securities and Exchange Commission",
    "id": "branch-33",
    "discretion": null
  }
];
myChart.hideLoading();
    function buildData(mode, originList) {
      let out = [];
      for (let i = 0; i < originList.length; i++) {
        let node = originList[i];
        let newNode = cloneNodeInfo(node);
        if (!newNode) {
          continue;
        }
        out[i] = newNode;
        let value = newNode.value;
        // Calculate amount per household.
        value[3] = value[0] / household_america_2012;
        // if mode === 0 and mode === 2 do nothing
        if (mode === 1) {
          // Set 'Change from 2010' to value[0].
          let tmp = value[1];
          value[1] = value[0];
          value[0] = tmp;
        }
        if (node.children) {
          newNode.children = buildData(mode, node.children);
        }
      }
      return out;
    }
    function cloneNodeInfo(node) {
      if (!node) {
        return;
      }
      const newNode = {};
      newNode.name = node.name;
      newNode.id = node.id;
      newNode.value = (node.value || []).slice();
      return newNode;
    }
    function getLevelOption(mode) {
      return [
        {
          color:
            mode === 2
              ? [
                  '#c23531',
                  '#314656',
                  '#61a0a8',
                  '#dd8668',
                  '#91c7ae',
                  '#6e7074',
                  '#61a0a8',
                  '#bda29a',
                  '#44525d',
                  '#c4ccd3'
                ]
              : undefined,
          colorMappingBy: 'id',
          itemStyle: {
            borderWidth: 3,
            gapWidth: 3
          }
        },
        {
          colorAlpha: mode === 2 ? [0.5, 1] : undefined,
          itemStyle: {
            gapWidth: 1
          }
        }
      ];
    }
    function isValidNumber(num) {
      return num != null && isFinite(num);
    }
    function getTooltipFormatter(mode) {
      let amountIndex = mode === 1 ? 1 : 0;
      let amountIndex2011 = mode === 1 ? 0 : 1;
      return function (info) {
        let value = info.value;
        let amount = value[amountIndex];
        amount = isValidNumber(amount)
          ? echarts.format.addCommas(amount * 1000) + '$'
          : '-';
        let amount2011 = value[amountIndex2011];
        amount2011 = isValidNumber(amount2011)
          ? echarts.format.addCommas(amount2011 * 1000) + '$'
          : '-';
        let perHousehold = value[3];
        perHousehold = isValidNumber(perHousehold)
          ? echarts.format.addCommas(+perHousehold.toFixed(4) * 1000) + '$'
          : '-';
        let change = value[2];
        change = isValidNumber(change) ? change.toFixed(2) + '%' : '-';
        return [
          '<div class="tooltip-title">' +
            echarts.format.encodeHTML(info.name) +
            '</div>',
          '2012 Amount: &nbsp;&nbsp;' + amount + '<br>',
          'Per Household: &nbsp;&nbsp;' + perHousehold + '<br>',
          '2011 Amount: &nbsp;&nbsp;' + amount2011 + '<br>',
          'Change From 2011: &nbsp;&nbsp;' + change
        ].join('');
      };
    }
    function createSeriesCommon(mode) {
      return {
        type: 'treemap',
        tooltip: {
          formatter: getTooltipFormatter(mode)
        },
        label: {
          position: 'insideTopLeft',
          formatter: function (params) {
            let arr = [
              '{name|' + params.name + '}',
              '{hr|}',
              '{budget|$ ' +
                echarts.format.addCommas(params.value[0]) +
                '} {label|budget}'
            ];
            mode !== 1 &&
              arr.push(
                '{household|$ ' +
                  echarts.format.addCommas(+params.value[3].toFixed(4) * 1000) +
                  '} {label|per household}'
              );
            return arr.join('\n');
          },
          rich: {
            budget: {
              fontSize: 22,
              lineHeight: 30,
              color: 'yellow'
            },
            household: {
              fontSize: 14,
              color: '#fff'
            },
            label: {
              fontSize: 9,
              backgroundColor: 'rgba(0,0,0,0.3)',
              color: '#fff',
              borderRadius: 2,
              padding: [2, 4],
              lineHeight: 25,
              align: 'right'
            },
            name: {
              fontSize: 12,
              color: '#fff'
            },
            hr: {
              width: '100%',
              borderColor: 'rgba(255,255,255,0.2)',
              borderWidth: 0.5,
              height: 0,
              lineHeight: 10
            }
          }
        },
        itemStyle: {
          borderColor: 'black'
        },
        levels: getLevelOption(0)
      };
    }
    let modes = ['2012Budget', '2011Budget', 'Growth'];
    myChart.setOption(
      (option = {
        title: {
          top: 5,
          left: 'center',
          text: 'How $3.7 Trillion is Spent',
          subtext: 'Obama’s 2012 Budget Proposal'
        },
        legend: {
          data: modes,
          selectedMode: 'single',
          top: 55,
          itemGap: 5,
          borderRadius: 5
        },
        tooltip: {},
        series: modes.map(function (mode, idx) {
          let seriesOpt = createSeriesCommon(idx);
          seriesOpt.name = mode;
          seriesOpt.top = 80;
          seriesOpt.visualDimension = idx === 2 ? 2 : undefined;
          seriesOpt.data = buildData(idx, obama_budget_2012);
          seriesOpt.levels = getLevelOption(idx);
          return seriesOpt;
        })
      })
    );

```
