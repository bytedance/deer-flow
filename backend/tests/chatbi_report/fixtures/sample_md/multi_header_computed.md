# 多级表头含计算列样例

## 第一章: 经营规模

### 报表: 商户与贷款概览

> 机构: branch_num=27020199; branch_short_name=王益联社
> 时期: time_info=["2025"]
> 计算:
>   收单商户同比 = 本期BAS_0263减去年同期再除同期

<table>
  <thead>
    <tr>
      <th rowspan="2">季度</th>
      <th colspan="2">商户与贷款</th>
    </tr>
    <tr>
      <th data-idx="BAS_0263" data-unit="个">贷款收单商户数</th>
      <th data-unit="%">{{收单商户同比}}</th>
    </tr>
  </thead>
  <tbody><tr><td>2025-Q4</td><td></td><td></td></tr></tbody>
</table>
