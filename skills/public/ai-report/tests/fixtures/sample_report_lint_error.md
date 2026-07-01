# Test Report

## 一、缺时期

### 表1 无时期

> 机构:
>   branch_short_name=x

<table>
  <thead><tr><th data-idx="A">col</th></tr></thead>
</table>

## 二、缺thead

### 表2 无thead

> 机构:
>   branch_short_name=x
> 时期: time_info = ["202603"]

<table><tbody><tr><td>no header</td></tr></tbody></table>

## 三、错单位

### 表3 错单位

> 机构:
>   branch_short_name=x
> 时期: time_info = ["202603"]

<table>
  <thead><tr><th data-idx="A" data-unit="千美元" data-period="202603">col</th></tr></thead>
</table>