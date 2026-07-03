# 王益联社 2026 年 3 月经营分析报告

## 一、行社经营效益分析

### 1.1 整体利润分析

> 机构:
>   branch_num=27020199; branch_short_name=王益联社
>   branch_num=27020100; branch_short_name=印台联社
> 时期: time_info=["2022", "2023", "2024", "2025"]
> 图表:
>   标题: 利润总额趋势
>   类型: line
>   x轴: 时期
>   y轴: 利润总额
>   系列: 行社
>   单位: 万元
>   输出: profit-trend
>
> 图表:
>   标题: 2025年利润同比对比
>   类型: bar
>   x轴: 行社
>   y轴: 2025利润同比
>   单位: %
>   输出: profit-yoy-2025
> 描述:
>   请基于表格数据生成经营分析描述，重点关注利润总额同比变化、与铜川平均值和全省平均值的对比，并给出盈利能力判断。
> 计算:
>   2023利润同比 = 2023年值减2022年值再除2022年值
>   2024利润同比 = 2024年值减2023年值再除2023年值
>   2025利润同比 = 2025年值减2024年值再除2024年值
>   2024利润同比.示例: BAS_0263[2024=1200, 2023=1000] -> 0.2
>   2025利润同比.示例: BAS_0263[2025=1500, 2024=1200] -> 0.25

<table>
  <thead>
    <tr>
      <th rowspan="2">行社</th>
      <th colspan="3" data-unit="万元">利润总额</th>
      <th colspan="3" data-unit="%">同比增速</th>
    </tr>
    <tr>
      <th data-idx="BAS_0263" data-period="2023" data-unit="万元">2023年</th>
      <th data-idx="BAS_0263" data-period="2024" data-unit="万元">2024年</th>
      <th data-idx="BAS_0263" data-period="2025" data-unit="万元">2025年</th>
      <th data-period="2023" data-unit="%">{{2023利润同比}}</th>
      <th data-period="2024" data-unit="%">{{2024利润同比}}</th>
      <th data-period="2025" data-unit="%">{{2025利润同比}}</th>
    </tr>
  </thead>
  <tbody>
    <tr><td>王益</td><td></td><td></td><td></td><td></td><td></td><td></td></tr>
    <tr><td>印台</td><td></td><td></td><td></td><td></td><td></td><td></td></tr>
    <tr><td>铜川平均值</td><td></td><td></td><td></td><td></td><td></td><td></td></tr>
    <tr><td>全省平均值</td><td></td><td></td><td></td><td></td><td></td><td></td><td></td></tr>
  </tbody>
</table>

### 1.2 贷款质量分析

> 机构:
>   branch_num=27020199; branch_short_name=王益联社
>   branch_num=27020100; branch_short_name=印台联社
>   branch_num=27020101; branch_short_name=耀州联社
>   branch_num=27020102; branch_short_name=宜君联社
>   branch_num=99999901; branch_short_name=市平均
>   branch_num=99999902; branch_short_name=省平均
> 时期: time_info=["2025"]
> 图表:
>   标题: 贷款余额与不良率
>   类型: bar_line
>   x轴: 行社
>   y轴左: 贷款余额
>   y轴右: 不良率
>   左轴单位: 万元
>   右轴单位: %
>   条形配色: #3498db
>   折线配色: #e74c3c
>   输出: loan-npl-combo

<table>
  <thead>
    <tr>
      <th rowspan="2">行社</th>
      <th data-unit="万元">贷款余额</th>
      <th data-unit="%">不良率</th>
    </tr>
    <tr>
      <th data-idx="BAS_0128" data-period="2025" data-unit="万元">2025年</th>
      <th data-idx="BAS_0129" data-period="2025" data-unit="%">2025年</th>
    </tr>
  </thead>
  <tbody>
    <tr><td>王益</td><td></td><td></td></tr>
    <tr><td>印台</td><td></td><td></td></tr>
    <tr><td>耀州</td><td></td><td></td></tr>
    <tr><td>宜君</td><td></td><td></td></tr>
    <tr><td>市平均</td><td></td><td></td></tr>
    <tr><td>省平均</td><td></td><td></td></tr>
  </tbody>
</table>

### 1.3 贷款多指标综合分析

> 机构:
>   branch_num=27020199; branch_short_name=王益联社
>   branch_num=27020100; branch_short_name=印台联社
>   branch_num=27020101; branch_short_name=耀州联社
>   branch_num=27020102; branch_short_name=宜君联社
>   branch_num=99999901; branch_short_name=市平均
>   branch_num=99999902; branch_short_name=省平均
> 时期: time_info=["2025"]
> 图表:
>   标题: 贷款余额与不良率综合分析
>   类型: bar_line
>   x轴: 行社
>   y轴左: 贷款余额, 存款日均净增
>   y轴右: 不良率, 占比
>   系列: 指标
>   左轴单位: 万元
>   右轴单位: %
>   条形配色: #3498db, #2ecc71
>   折线配色: #e74c3c, #f39c12
>   输出: loan-multi-combo

<table>
  <thead>
    <tr>
      <th rowspan="2">行社</th>
      <th colspan="2" data-unit="万元">资产规模</th>
      <th colspan="2" data-unit="%">风险指标</th>
    </tr>
    <tr>
      <th data-idx="BAS_0128" data-period="2025" data-unit="万元">贷款余额</th>
      <th data-idx="BAS_0130" data-period="2025" data-unit="万元">存款日均净增</th>
      <th data-idx="BAS_0129" data-period="2025" data-unit="%">不良率</th>
      <th data-idx="BAS_0131" data-period="2025" data-unit="%">占比</th>
    </tr>
  </thead>
  <tbody>
    <tr><td>王益</td><td></td><td></td><td></td><td></td></tr>
    <tr><td>印台</td><td></td><td></td><td></td><td></td></tr>
    <tr><td>耀州</td><td></td><td></td><td></td><td></td></tr>
    <tr><td>宜君</td><td></td><td></td><td></td><td></td></tr>
    <tr><td>市平均</td><td></td><td></td><td></td><td></td></tr>
    <tr><td>省平均</td><td></td><td></td><td></td><td></td></tr>
  </tbody>
</table>