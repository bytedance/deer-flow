---
name: nbev_profile
version: 1.0.0
author: marketing-planning-team
compatibility: deerflow>=2.0
description: 万能营销画像（现状分析）。当内勤想查看机构当前的队伍、客户、产品现状结构时使用。触发场景：队伍画像、客户画像、产品画像、万能营销画像、画像、队伍/客户/产品分析、看看现状/结构。能力边界——本skill只做"看现状画像"；若用户想规划"如何达成某NBEV目标"，改用 nbev_planning；若用户想在已有规划上调整数值，改用 nbev_modify。画像维度可选队伍/客户/产品，缺省则查全部三维。数据月份缺省取当前月1号。机构信息由登录用户自动解析（branch_code=org_id），无需也不应向用户索取。
---

# 万能营销画像 Skill（现状分析）

查询机构在某月份的 **队伍 / 客户 / 产品** 现状画像。底层是通用画像查询接口，通过 `scripts/run_profile.py` 统一编排。

## 第一步：判断是否该用本 skill

| 用户意图 | 处理 |
|----------|------|
| "看队伍画像 / 客户结构如何 / 产品现状 / 给我看下机构画像" | ✅ 用本 skill |
| "怎么达成6000万 / 规划达成路径" | ❌ 转 `nbev_planning` |
| "把银钻调到45人"（改已有规划） | ❌ 转 `nbev_modify` |

## 第二步：确认信息（画像【绝不反问】，直接查）

画像是只读查询，所有信息都有合理默认，**不存在需要向用户确认的场景**。直接查询并展示，不要反问。

- **画像维度（可选）**：队伍 / 客户 / 产品 / 全部。
  - 用户没指定 → **默认查全部三维**，不要问"先看哪个"。
  - 用户提到多个（如"客户画像或产品画像"）→ 把提到的维度**一次全查出来**展示，不要让用户二选一。
- **数据月份（可选）**：缺省取**当前月1号**（如今天 2026-06-16 → 2026-06-01）。用户没说月份就直接用默认，**不要问月份**。
- **机构信息**：由脚本依据登录用户自动解析（branch_code 即 org_id），**不要问用户、不要在命令里写机构**。

**示例（务必照此行为）：**
- 用户："看下画像" → 直接查全部三维并展示，不反问。
- 用户："客户画像或产品画像可以吗" → 直接 `-d 客户 产品` 一次查两个并展示，不要问"先看哪个"。
- 用户："看队伍画像" → 直接 `-d 队伍`，不问月份。

## 第三步：调用脚本

```bash
# 查全部三维画像（缺省月份=当前月1号）
python scripts/run_profile.py --user-id "{当前登录用户ID}" --format md

# 只看队伍画像，指定月份
python scripts/run_profile.py --user-id "{当前登录用户ID}" -d 队伍 -m 2026-06-01 --format md
```

- 维度固定按 **队伍 → 客户 → 产品** 顺序查询。
- `--format md` 直接返回美观 Markdown（含表格），推荐呈现给用户。

### 参数

| 参数 | 短参 | 必填 | 说明 |
|------|------|------|------|
| `--user-id` | `-uid` | 是 | 登录用户ID，脚本据此解析机构（branch_code=org_id） |
| `--dimensions` | `-d` | 否 | `队伍` `客户` `产品` `全部`；缺省=全部三维 |
| `--month` | `-m` | 否 | `YYYY-MM-01`，缺省=当前月1号 |
| `--format` | `-f` | 否 | `md`（美观表格）/ `json`（默认） |
| `--request-id` | `-rid` | 否 | 缺省自动生成 |
| `--output` | `-o` | 否 | 结果落盘路径 |

## 第四步：呈现给用户（输出规范）

- 用 `--format md` 时，脚本输出已组织好（队伍按钻石层级表、客户九宫格表、产品按NBEV排序表），**直接呈现**，再用一两句话点评结构特征。
- 数据一律以 **Markdown 表格**呈现。
- 每个维度结果含 `status`：

| status | 含义 | 你的动作 |
|--------|------|----------|
| `success` | 查询成功 | 展示该维度 Markdown 表 + summary |
| `no_data` | 该维度该月无数据 | 如实告知"该机构该月暂无XX画像数据"，不编造 |
| `runtime_error`(retryable) | 服务繁忙 | 告知"稍后重试"，不展示堆栈 |
| `validation_error` | 入参非法（如月份格式） | 按 `error.hint` 纠正后重试 |

## 三维画像内容说明

| 维度 | 表结构 | 关键字段 |
|------|--------|----------|
| 队伍 | 按钻石层级（双金钻/金钻/银钻/钻石/活动非钻/非活动） | 在职人力、人力占比、NBEV、NBEV占比 |
| 客户 | 客温×客价 九宫格 | 各格签单客户数、行列合计 |
| 产品 | 按 产品×缴期，NBEV 降序（Top15） | 出单人力、活动率、NBEV、NBEV占比 |

## 错误码速查

| error_code | 对用户怎么说 |
|------------|--------------|
| `MONTH_FORMAT_INVALID` | 月份请用 YYYY-MM-01 |
| `DIMENSION_INVALID` | 维度仅支持 队伍/客户/产品/全部 |
| `DIMENSION_DATA_EMPTY` | 该机构该月暂无此维度画像数据 |
| `PROFILE_API_404xx` | 画像配置缺失，请联系管理员 |
| `PROFILE_API_500xx` | 画像服务异常，请稍后重试 |
| `DEPENDENCY_MISSING` | 运行环境缺依赖，请联系管理员 |
| `API_TIMEOUT` / `UPSTREAM_5XX` / `API_CONN_ERROR` | 画像服务繁忙，请稍后重试 |
| `PROFILE_EXCEPTION` | 画像处理异常，请稍后重试 |

## 与其他 Skill 的边界

| 场景 | Skill |
|------|-------|
| 查看现状画像 | **nbev_profile（本skill）** |
| 从零新建达成路径 | nbev_planning |
| 调整已有规划 | nbev_modify |

## 工程说明（维护者）

- 入口：`scripts/run_profile.py`（薄壳：解析CLI→调 profiler→输出 json/md）
- 核心：`scripts/profile_core/`（**skill 自包含**）
  - `profiler.py` 编排 · `validators.py` 校验(月份缺省=当前月) · `api_client.py` 通用查询(超时/重试/按code判错)
  - `interpreters.py` 行聚合+预渲染MD表 · `render.py` 拼装 · `envelope.py` 信封 · `errors.py` 错误体系
  - `org_context.py` 机构解析（**当前写死 05/深圳**）
  - `config.py` 维度→(tableName, sqlid)映射 + 环境变量
- 环境变量：`PROFILE_QUERY_API_BASE`、`PROFILE_QUERY_TIMEOUT`、`PROFILE_QUERY_MAX_RETRY`
