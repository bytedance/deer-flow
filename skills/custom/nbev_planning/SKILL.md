---
name: nbev_planning
version: 2.1.0
author: marketing-planning-team
compatibility: deerflow>=2.0
description: 万能营销规划（从零新建达成路径）。当内勤需要根据目标NBEV，从产品、客户、队伍三个维度规划"如何达成"时使用。触发场景：万能营销规划、新建规划、达成路径、NBEV怎么达成、产品/客户/队伍达成测算。能力边界——本skill只做"从零新建"；若用户在已有规划上调整某个数值（"把X调到Y"），改用 nbev_modify；若用户只想看现状画像，改用 nbev_profile。测算维度（产品/客户/队伍）与目标NBEV为必填，缺失须先向用户澄清；测算月份缺省取下个月1号。机构信息由登录用户自动解析，无需也不应向用户索取 org_id/org_name。
---

# 万能营销规划 Skill（达成测算 · 从零新建）

围绕目标 NBEV，从 **产品 / 客户 / 队伍** 三维度生成达成路径。底层是三个同构的达成测算接口，通过 `scripts/run_planning.py` 统一编排。

## 第一步：判断是否该用本 skill

| 用户意图 | 处理 |
|----------|------|
| "怎么达成6000万 / 做产品达成路径 / 看队伍如何达成" | ✅ 用本 skill |
| "把银钻调到45人 / 活动率改到6%"（在已有规划上改某值） | ❌ 转 `nbev_modify` |
| "看当前队伍画像 / 客户结构现状" | ❌ 转 `nbev_profile` |

## 第二步：必填澄清（仅这两项，其余直接用默认）

只有以下**两项硬必填**缺失时才澄清，**一次只补问缺的那一项，已知的绝不重复问**；其余信息一律用默认值直接执行，不要反问：

1. **测算维度**：产品 / 客户 / 队伍（可多选）。完全没提到时才问："您想从哪个维度看达成？产品、客户还是队伍？（可多选）"
2. **目标 NBEV（万元）**：完全没提到金额时才问："目标 NBEV 是多少万元？"

> 用户只要给了维度和目标（哪怕只给一个维度），就**直接测算**，不要追问其他维度、不要追问月份。
> 若脚本返回 `status=needs_clarification`，按其 `error.hint` 提问，不要当报错。

**可选信息（不要为此反问）：**
- **业务月份**：缺省自动取**下个月1号**（如今天 2026-06-16 → 2026-07-01）。用户说"6月""下个月"这类能直接确定的，直接用，**不要确认月份**。
- **机构信息**：org_id/org_name 由脚本依据登录用户自动解析，**不要问用户、不要在命令里写机构**。

## 第三步：调用脚本

```bash
python scripts/run_planning.py \
  --user-id "{当前登录用户ID}" \
  --dimensions 产品 队伍 客户 \
  --target-nbev 8000 \
  --month 2026-07-01 \
  --format md
```

- 脚本内部固定按 **产品 → 队伍 → 客户** 顺序调用，无需手动排序。
- `--format md` 直接返回美观 Markdown（含表格），推荐用于向用户呈现；`--format json` 返回含完整 `data` 的结构化结果。

### 参数

| 参数 | 短参 | 必填 | 说明 |
|------|------|------|------|
| `--user-id` | `-uid` | 是 | 登录用户ID，脚本据此解析机构 |
| `--dimensions` | `-d` | 是* | `产品` `客户` `队伍`，可多选（*缺失会触发澄清） |
| `--target-nbev` | `-tv` | 是* | 目标NBEV（万元）（*缺失会触发澄清） |
| `--month` | `-m` | 否 | `YYYY-MM-01`，缺省下月1号 |
| `--format` | `-f` | 否 | `md`（美观表格）/ `json`（默认） |
| `--request-id` / `--session-id` | | 否 | 缺省自动生成 |
| `--max-product-activity-rate` / `--max-avg-fyp-range` / `--max-double-gold-diamond-ratio` | | 否 | 浮动范围/占比上限，缺省走接口默认 |
| `--output` | `-o` | 否 | 结果落盘路径 |

## 第四步：呈现给用户（输出规范）

- 用 `--format md` 时，脚本输出已是组织好的 Markdown，**直接呈现**，再用一两句话点评要点（尤其护栏未过项）。
- 数据一律以 **Markdown 表格**呈现，不要堆成长段文字。
- 每个维度结果含一个 `status`：

| status | 含义 | 你的动作 |
|--------|------|----------|
| `success` | 测算成功（注意看 `validation`） | 展示表格 + summary；**务必转达是否达标**：若 `ACH_target_met` 未过说明预测未达目标 NBEV，需提示用户调整或下调目标；C2/C4 护栏未过也要转达 |
| `needs_clarification` | 缺必填项 | 按 `error.hint` 向用户提问，不要报错 |
| `target_unreachable` | 目标不可达 | 按 `error.hint` 引导下调目标或换维度 |
| `runtime_error`(retryable) | 服务繁忙 | 告知"稍后重试"，不展示堆栈 |
| `validation_error` | 入参非法 | 按 `error.hint` 纠正后重试 |

## 错误码速查

| error_code | 对用户怎么说 |
|------------|--------------|
| `NEED_CLARIFY` | （按 hint 提问，非报错） |
| `TARGET_NBEV_NONPOSITIVE` / `TARGET_NBEV_INVALID` | 目标NBEV需为正数 |
| `MONTH_FORMAT_INVALID` | 月份请用 YYYY-MM-01 |
| `DIMENSION_INVALID` / `DIMENSIONS_EMPTY` | 维度仅支持 产品/客户/队伍 |
| `RATIO_OUT_OF_BOUND` / `RATIO_NOT_NUMBER` | 比率参数需为 0~1 小数 |
| `PRODUCT_FALLBACK_CARD` / `PRODUCT_RESULT_EMPTY` | 该机构当月暂无产品历史/配置，无法完成产品测算 |
| `TARGET_UNREACHABLE` | 历史数据难支撑该目标，建议下调或换维度 |
| `DEPENDENCY_MISSING` | 运行环境缺依赖，请联系管理员 |
| `API_TIMEOUT` / `UPSTREAM_5XX` / `API_CONN_ERROR` | 测算服务繁忙，请稍后重试 |
| `CALCULATION_EXCEPTION` | 测算异常，请稍后重试 |

## 与其他 Skill 的边界

| 场景 | Skill |
|------|-------|
| 从零新建达成路径 | **nbev_planning（本skill）** |
| 调整已有规划 | nbev_modify |
| 查看现状画像 | nbev_profile |

## 工程说明（维护者）

- 入口：`scripts/run_planning.py`（薄壳：解析CLI→调 planner→输出 json/md）
- 核心：`scripts/nbev_core/`（**skill 自包含**，不依赖外部目录）
  - `planner.py` 编排 · `validators.py` 校验(月份缺省=下月) · `api_client.py` 调接口(超时/重试)
  - `interpreters.py` 解读+护栏 · `render.py` Markdown渲染 · `envelope.py` 信封 · `errors.py` 错误体系
  - `org_context.py` 机构解析（**当前写死 05/深圳**，未来替换此文件一处即可）
  - `config.py` 环境变量配置
- 后端测算接口：`http://8.148.158.241:8001/api/v1/marketing-planning/get-{product|team|customer}-card-data`
- 环境变量：`MARKETING_PLANNING_API_BASE`（默认上述地址）、`MARKETING_PLANNING_TIMEOUT`、`MARKETING_PLANNING_MAX_RETRY`、`NBEV_LOG_LEVEL`
