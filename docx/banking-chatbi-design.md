# 银行智能问数系统 — ChatBI 设计方案

> 基于 Hermes Agent 构建银行内部智能数据分析平台，采用 SwiftAgent NL2Semantics 范式，
> 面向支行行长/营销人员，提供自然语言问数、归因分析、预警报告能力。

---

## 一、目标与范围

### 1.1 核心目标

| 目标 | 描述 |
|------|------|
| **自然语言问数** | 用户用日常语言查询数据，无需 SQL 或 Python |
| **渐进式澄清** | 模糊查询自动引导细化，避免"幻觉" |
| **统一口径** | 基于语义层的指标体系，一次定义，多次复用 |
| **归因分析** | 自动识别指标异动的原因（维度/因子/时间序列） |
| **自动化报告** | 整合图表+结论+策略建议，输出专业级洞察 |
| **实时预警** | 监控关键指标异动，自动通知负责人 |

### 1.2 面向角色

- **支行行长 / 营销人员**（主要用户）
  - 业绩对比分析（本行 vs 其他支行）
  - 时间趋势分析（本月/本季/本年）
  - 简单归因分析
- **总行管理层**（后续扩展）
  - 全行汇总指标
  - 同比环比分析
  - 跨部门关联分析

### 1.3 数据范围

| 维度 | 说明 |
|------|------|
| **数据源** | PostgreSQL + 达梦 DM（T+1 数据仓库） |
| **数据权限** | 总行 / 分行 / 支行三级分级 |
| **敏感指标** | 不良率、拨备覆盖率等需脱敏或审批 |
| **用户规模** | 几百个网点，预计百级并发 |

---

## 二、整体架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Web 用户界面                                  │
│                 (PC 端 / 渐进式多轮对话)                              │
└────────────────────────────────┬────────────────────────────────────┘
                                 │ HTTPS / WebSocket
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      Hermes Agent（主控大脑）                         │
│  ┌────────────────┐  ┌─────────────────┐  ┌──────────────────────┐  │
│  │  Intent Router  │  │  Memory Manager │  │  Permission Injector │  │
│  │  (意图分类)      │  │  (多轮状态)     │  │  (权限注入)          │  │
│  └────────────────┘  └─────────────────┘  └──────────────────────┘  │
│  ┌─────────────────────────────────────────────────────────────────┐│
│  │                    Skill Context (技能层)                       ││
│  │   banking-nl2sql  │  banking-insight  │  banking-report        ││
│  └─────────────────────────────────────────────────────────────────┘│
└──────────────┬─────────────────┬──────────────────┬────────────────┘
               │                 │                  │
               ▼                 ▼                  ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────────┐
│  Metric Agent    │  │  Insight Agent   │  │  Report Agent           │
│  (子 Agent)       │  │  (子 Agent)       │  │  (工具)                 │
│                  │  │                  │  │                         │
│  NL2Semantics    │  │  归因分析         │  │  报告生成               │
│  语义映射         │  │  异常检测         │  │  图表+结论+建议         │
│  指标查询         │  │  时间序列分析     │  │                         │
└────────┬─────────┘  └────────┬─────────┘  └──────────────────────────┘
         │                     │
         ▼                     ▼
┌──────────────────┐  ┌──────────────────────────┐
│   NL2SQL Router  │  │   Code Agent            │
│                  │  │   (工具)                 │
│  简单查询=LLM直译 │  │                         │
│  复杂查询=SQLBot  │  │  复杂业务逻辑            │
│                  │  │  Python代码执行          │
└────────┬─────────┘  └──────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        数据访问层                                     │
│  ┌─────────────────────┐    ┌─────────────────────────────────┐   │
│  │   PostgreSQL         │    │   达梦 DM                       │   │
│  │   (业务数据)          │    │   (国产库)                      │   │
│  └─────────────────────┘    └─────────────────────────────────┘   │
│                      T+1 数据仓库                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 三、核心组件设计

### 3.1 主控 Agent（Hermes）

**职责**：
- 统一入口，对话管理
- Intent Router 分类（简单查询 / 复杂分析 / 归因 / 报告）
- 协调子 Agent 工作
- 权限注入（根据用户行员号 + 机构码注入 WHERE 条件）
- Memory 多轮状态管理

**关键集成点**：
```python
# toolsets.py 新增
TOOLSETS = {
    ...,
    "banking": {
        "tools": ["metric_agent", "insight_agent", "report_agent", "code_agent"],
        "includes": []
    }
}
```

### 3.2 Metric Agent（子 Agent）

**职责**：语义层映射与指标查询

**核心能力**：

1. **NL2Semantics 语义映射**
   ```
   用户: "本月存款情况"
   → 语义映射表查询
   → "存款余额" = SUM(balance) WHERE acct_type IN ('对公', '对私') AND stat_period = '本月'
   → 命中已有指标 → 直接生成 SQL
   ```

2. **渐进式澄清**
   ```
   用户: "最近销售情况"
   → 语义模糊，返回澄清选项:
     "请问您想看哪个时间范围？"
     - 近7天
     - 本月
     - 本季
     "以及哪个地区或产品线？"
   ```

3. **指标补全（缺失指标）**
   ```
   用户: "客户流失率"
   → 语义映射表未命中
   → LLM 语义补全 + 标注 [待确认]
   → 存入待确认队列，定期由数据团队审核沉淀到语义层
   ```

**技术实现**：
```python
# tools/metric_agent.py
def metric_agent(action: str, query: str, user_context: dict) -> str:
    """
    action: "semantic_map" | "collect" | "clarify"
    """
    if action == "semantic_map":
        # 1. 查语义映射表
        metric = semantic_lookup(query)
        if metric:
            return {"status": "found", "metric": metric}
        else:
            # 2. LLM 补全，标注 [待确认]
            llm_suggestion = llm_semantic_fill(query)
            return {"status": "pending_confirm", "suggestion": llm_suggestion}

    elif action == "clarify":
        # 生成澄清选项
        return generate_clarification_options(query)
```

### 3.3 Insight Agent（子 Agent）

**职责**：归因分析与异常检测

**核心能力**：

1. **智能归因分析**
   ```
   用户: "本月存款为何下降？"
   → Insight Agent 自动拆解:
     - 时间维度：本月 vs 上月 vs 去年同期
     - 机构维度：存款减少主要来自哪些支行
     - 产品维度：哪类产品下降最多（定期/活期/理财）
   → 输出归因结论：如 "主要由 A 支行定期存款下降 15% 导致"
   ```

2. **异常检测**
   ```
   用户: "有什么指标异常吗？"
   → 自动扫描关键指标
   → 检测偏离正常范围/趋势的指标
   → 输出预警列表 + 置信度
   ```

3. **对比分析**
   ```
   用户: "和上海对比呢？"
   → 触发对比分析流程
   → 结构化输出差异 + 可能的解释
   ```

**技术实现**：
```python
# tools/insight_agent.py
def insight_agent(action: str, query: str, context: dict) -> str:
    """
    action: "attribute" | "anomaly" | "compare"
    """
    if action == "attribute":
        # 多维度拆解归因
        result = multi_dimensional_attribution(
            metric=context["metric"],
            baseline=context.get("baseline"),
            dimensions=["branch", "product", "period"]
        )
        return format_attribution_result(result)

    elif action == "anomaly":
        # 异常检测
        anomalies = detect_anomalies(
            metrics=context["metrics"],
            method="statistical"  # or "ml"
        )
        return format_anomaly_result(anomalies)
```

### 3.4 Report Agent（工具）

**职责**：自动化报告生成

**核心能力**：

1. **报告结构生成**
   ```
   用户: "生成本月业绩报告"
   → Report Agent 输出:
     ## 一、本月业绩概览
     ## 二、各指标表现
     ## 三、与上月/去年同期对比
     ## 四、异常指标说明
     ## 五、优化建议
   ```

2. **图表生成**
   - 调用代码生成图表（Matplotlib / ECharts）
   - 自动选择最合适的图表类型

3. **策略建议**
   ```
   结合 RAG 知识库（如历史成功案例）
   输出可执行建议：
   - "建议加强 A 产品营销，本月该产品表现优于同类 20%"
   ```

### 3.5 Code Agent（工具）

**职责**：复杂业务逻辑的代码执行

**核心能力**：

1. **复杂查询逻辑**
   ```
   用户: "计算客户生命周期价值"
   → SQL 难以直接表达
   → Code Agent 接收：Python 代码片段定义
   → 执行后返回结果
   ```

2. **数据处理管道**
   ```python
   # 用户或分析团队编写
   def calc_customer_ltv():
       customers = query("SELECT * FROM customer_transactions")
       # 复杂计算逻辑
       return ltv_by_segment
   ```

3. **安全沙箱执行**
   - 只允许预定义的函数库
   - 超时控制
   - 结果验证

**注册方式**：
```python
# tools/code_agent.py
registry.register(
    name="code_executor",
    toolset="banking",
    schema=CODE_AGENT_SCHEMA,
    handler=code_executor_handler,
    check_fn=lambda: ENABLE_CODE_AGENT in os.environ,
)
```

---

## 四、NL2SQL Router 设计

### 4.1 查询复杂度分类

```
Intent Router 判断查询类型:

┌──────────────────────────────────────────────┐
│                  用户查询                      │
│         "本月杭州分行的存款情况"                 │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
              ┌─────────────────┐
              │  复杂度分类       │
              └────────┬────────┘
                       │
         ┌─────────────┼─────────────┐
         │             │             │
         ▼             ▼             ▼
    ┌─────────┐   ┌─────────┐   ┌─────────┐
    │  简单   │   │  中等   │   │  复杂   │
    │  LLM直译 │   │  SQLBot │   │ Code Agent│
    └─────────┘   └─────────┘   └─────────┘
```

| 类型 | 判断标准 | 处理方式 |
|------|---------|---------|
| **简单** | 单表 + 单指标 + 无复杂计算 | LLM 直接翻译 SQL |
| **中等** | 多表 JOIN + 聚合 + 简单计算 | SQLBot API |
| **复杂** | 嵌套查询 + 窗口函数 + 复杂业务逻辑 | Code Agent |

### 4.2 SQL 执行流程

```
用户查询: "本月杭州分行存款余额"
         │
         ▼
┌─────────────────────────────────────────────────────┐
│ Step 1: Intent Router 判断 = 中等                    │
│         → 路由到 SQLBot                              │
└──────────────────────┬────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│ Step 2: Metric Agent 语义映射                        │
│         "存款余额" → {table: T_DEMAND_DEPOSITS,      │
│                       calc: SUM(balance),            │
│                       filters: {branch: "杭州"}}     │
└──────────────────────┬────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│ Step 3: Permission Injector 注入权限                 │
│         追加 WHERE: branch_code IN ({用户可访问机构})  │
│                     AND stat_period = '202604'       │
└──────────────────────┬────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│ Step 4: SQLBot 生成 + 执行                           │
│         SELECT SUM(balance) FROM T_DEMAND_DEPOSITS   │
│         WHERE branch_code IN (...) AND stat_period='202604'
│         → 返回结果集                                  │
└──────────────────────┬────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│ Step 5: 结果格式化 + 图表生成                        │
│         → 自然语言解读: "本月杭州分行存款余额为 X 亿元" │
└─────────────────────────────────────────────────────┘
```

---

## 五、NL2Semantics 语义层设计

### 5.1 语义层架构

```
┌─────────────────────────────────────────────────────────────────┐
│                      语义层（Semantic Layer）                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 第一层：已有指标（直接复用）                               │   │
│  │                                                         │   │
│  │  指标ID    │   指标名   │   计算逻辑    │   口径说明    │   │
│  │  MET_001  │  存款余额  │  SUM(balance) │  境内存款    │   │
│  │  MET_002  │  贷款余额  │  SUM(loan_bal)│  境内贷款    │   │
│  │  MET_003  │  不良率   │  NPL/总贷款   │  五级分类    │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 第二层：缺失指标（LLM 语义补全 → [待确认]）                │   │
│  │                                                         │   │
│  │  用户查询 "客户满意度" → 语义映射表未命中                 │   │
│  │  → LLM 推断计算逻辑 → 标注 [待确认]                      │   │
│  │  → 存入 pending_metrics 表，定期由数据团队审核             │   │
│  │  → 审核通过后 → 沉淀到第一层                              │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 第三层：Code Agent 兜底（复杂逻辑）                       │   │
│  │                                                         │   │
│  │  无法用 SQL 表达的 → 业务团队编写 Python 代码             │   │
│  │  代码注册到 code_repository → Code Agent 调用执行        │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 5.2 语义映射表结构

```sql
CREATE TABLE semantic_metrics (
    metric_id       VARCHAR(50) PRIMARY KEY,
    metric_name     VARCHAR(200) NOT NULL,        -- 中文名称
    metric_name_en  VARCHAR(200),                  -- 英文别名
    business_domain VARCHAR(100),                  -- 业务领域：存款/贷款/中间业务
    calc_logic      TEXT NOT NULL,                 -- 计算逻辑（SQL 或代码引用）
    calc_type       VARCHAR(20),                   -- SQL | CODE
    table_name      VARCHAR(100),                  -- 主表
    dimensions      JSONB,                         -- 可用维度
    filters         JSONB,                         -- 固定过滤条件
    unit            VARCHAR(20),                   -- 单位：万元/百分比
    description     TEXT,                          -- 指标说明
    status          VARCHAR(20),                   -- ACTIVE | PENDING | DEPRECATED
    created_at      TIMESTAMP,
    updated_at      TIMESTAMP
);

CREATE TABLE pending_metrics (
    id              SERIAL PRIMARY KEY,
    query_text      TEXT NOT NULL,                 -- 用户原始查询
    llm_suggestion  JSONB NOT NULL,                -- LLM 推断的指标定义
    confidence      FLOAT,                         -- LLM 置信度
    status          VARCHAR(20),                   -- PENDING | APPROVED | REJECTED
    reviewed_by     VARCHAR(50),
    reviewed_at     TIMESTAMP,
    created_at      TIMESTAMP
);
```

---

## 六、权限体系设计

### 6.1 数据分级权限

```
┌─────────────────────────────────────────────────────────┐
│                    权限注入流程                           │
└─────────────────────────────────────────────────────────┘

用户行员号 → 查用户机构表 → 获取可访问机构列表
                              │
                              ▼
                    注入到所有 SQL WHERE 条件
                    branch_code IN ('001', '002', ...)
```

### 6.2 敏感指标脱敏

```python
# tools/permission_injector.py

SENSITIVE_METRICS = {
    "不良率": {"require_approval": True, "min_level": "分行"},
    "拨备覆盖率": {"require_approval": True, "min_level": "分行"},
    "净利差(NIM)": {"require_approval": True, "min_level": "总行"},
}

def check_metric_access(user_level: str, metric: str) -> dict:
    """检查用户是否有权访问敏感指标"""
    if metric not in SENSITIVE_METRICS:
        return {"accessible": True, "reason": "非敏感指标"}

    required_level = SENSITIVE_METRICS[metric]["min_level"]
    if user_level >= required_level:
        return {"accessible": True}
    else:
        return {
            "accessible": False,
            "reason": f"该指标需要{required_level}级别权限",
            "action": "apply_approval"  # 触发审批流程
        }
```

### 6.3 用户权限表结构

```sql
CREATE TABLE user_permissions (
    user_id       VARCHAR(50) PRIMARY KEY,
    user_name     VARCHAR(200),
    branch_code   VARCHAR(20),                  -- 所属机构
    user_level    VARCHAR(20),                  -- 总行/分行/支行
    data_scope    JSONB,                        -- 可访问的机构范围
    metrics_scope JSONB,                        -- 可访问的指标范围（NULL=全部）
    created_at    TIMESTAMP
);
```

---

## 七、预警体系设计

### 7.1 预警触发机制

基于 Cron 系统实现：

```
┌─────────────────────────────────────────────────────────────┐
│                    Cron 定时扫描                             │
│                                                             │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────────┐  │
│  │ 每日凌晨扫描 │ → │ 指标异动检测 │ → │ 触发通知流程     │  │
│  │             │   │ (vs 上期/同期)│   │                 │  │
│  └─────────────┘   └─────────────┘   └─────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### 7.2 预警配置

```python
# cron/alert_rules.py

ALERT_RULES = [
    {
        "name": "存款异动预警",
        "metric": "存款余额",
        "condition": "change_ratio < -0.1",  # 下降超过 10%
        "action": "notify_branch_manager",
        "channels": ["企业微信", "短信"],
    },
    {
        "name": "不良率超标预警",
        "metric": "不良率",
        "condition": "value > 0.05",  # 超过 5%
        "action": "notify_risk_manager",
        "channels": ["企业微信", "短信"],
    },
]
```

---

## 八、渐进式对话设计

### 8.1 典型对话流

```
用户: "本月业绩怎么样？"
      │
      ▼
Hermes: "以下是本月主要业绩指标概览：

| 指标 | 数值 | 环比 |
|------|------|------|
| 存款余额 | 12.5 亿元 | +3.2% |
| 贷款余额 | 8.3 亿元 | +5.1% |
| 中间业务收入 | 2100 万 | -1.2% |

请问您想深入了解哪项指标？比如：
- 存款：想看结构（定期/活期）还是趋势？
- 贷款：想看行业分布还是担保方式？
- 中间业务：想看具体是哪些产品下降？"

────────────────────────────────────────────────

用户: "中间业务下降的原因是什么？"
      │
      ▼
Insight Agent: "经分析，本月中收下降主要原因是：

【归因分析】
1. 代理保险收入下降 45 万（-18%）
   - 主因：主力客户群保险配置意愿下降
   - 次因：产品竞争力下降（收益率 vs 同行）

2. 信用卡分期收入下降 20 万（-12%）
   - 主因：活跃客户数下降 8%

【建议】
- 可重点关注代理基金业务，近期表现优于同类产品
- 建议加强客户分层营销，提升高净值客户粘性"

────────────────────────────────────────────────

用户: "生成本月业绩报告"
      │
      ▼
Report Agent: "## XX支行 2026年4月业绩报告

### 一、本月业绩概览
...

### 二、各指标表现
...

### 三、与上月对比
...

### 四、异常说明
...

### 五、优化建议
[内容已根据上下文自动生成]"
```

### 8.2 意图分类

```python
# tools/intent_classifier.py

INTENTS = {
    "SIMPLE_QUERY": {
        "patterns": ["查一下", "看看", "有多少", "是多少"],
        "handler": "metric_agent.collect",
        "requires_clarification": True,
    },
    "COMPARISON": {
        "patterns": ["对比", "和...相比", "差异", "哪个好"],
        "handler": "insight_agent.compare",
    },
    "ATTRIBUTION": {
        "patterns": ["为什么", "原因", "下降", "上升", "由什么导致"],
        "handler": "insight_agent.attribute",
    },
    "TREND": {
        "patterns": ["趋势", "走势", "变化", "历史"],
        "handler": "insight_agent.trend",
    },
    "REPORT": {
        "patterns": ["报告", "总结", "分析报告"],
        "handler": "report_agent.generate",
    },
    "ALERT": {
        "patterns": ["预警", "异常", "监控"],
        "handler": "insight_agent.anomaly_detect",
    },
    "CLARIFICATION": {
        "patterns": ["...", "具体点", "详细一点"],
        "handler": "metric_agent.clarify",
    },
}
```

---

## 九、技术实现路径

### 9.1 工具注册

```python
# tools/banking_metrics.py

from tools.registry import registry

def metric_collect_handler(args: dict, context: dict) -> str:
    """指标查询入口"""
    query = args.get("query")
    user_context = context.get("user", {})
    return metric_agent(action="collect", query=query, user_context=user_context)

registry.register(
    name="metric_collect",
    toolset="banking",
    schema={
        "name": "metric_collect",
        "description": "查询银行业务指标",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "自然语言查询"},
                "time_range": {"type": "string", "description": "时间范围"},
            }
        }
    },
    handler=metric_collect_handler,
)

# tools/banking_insight.py
# tools/banking_report.py
# tools/code_agent.py
```

### 9.2 工具集配置

```python
# toolsets.py

TOOLSETS = {
    ...,
    "banking": {
        "description": "银行数据分析",
        "tools": [
            "metric_collect",
            "metric_semantic_map",
            "metric_clarify",
            "insight_attribute",
            "insight_anomaly",
            "insight_compare",
            "insight_trend",
            "report_generate",
            "code_executor",
        ],
        "includes": []
    }
}
```

---

## 十、实现阶段规划

```
Phase 1: 核心链路跑通
─────────────────────────────────────────────────────────
目标: 单指标查询 + 多轮对话 + 基础语义映射

组件:
  ✅ Hermes Agent (核心)
  ✅ Metric Agent (语义映射 + 指标查询)
  ✅ 简单 NL2SQL (LLM 直译)
  ✅ Permission Injector (数据分级)
  ✅ Memory 多轮状态

交付: 用户问数 → 返回指标结果 + 图表

─────────────────────────────────────────────────────────
Phase 2: 归因分析与预警
─────────────────────────────────────────────────────────
目标: 归因分析 + 异常检测 + 定时预警

组件:
  + Insight Agent (归因分析)
  + Alert Rule Engine (基于 Cron)
  + 渐进式澄清流程
  + 通知渠道集成 (企微/短信)

交付: "本月存款为何下降？" → 归因结论 + 建议

─────────────────────────────────────────────────────────
Phase 3: 报告与 Code Agent
─────────────────────────────────────────────────────────
目标: 自动化报告生成 + 复杂逻辑兜底

组件:
  + Report Agent (报告结构 + 图表)
  + Code Agent (Python 代码执行)
  + SQLBot API 集成 (复杂查询)
  + NL2Semantics 语义层完善

交付: "生成月度业绩报告" → 完整分析报告

─────────────────────────────────────────────────────────
Phase 4: 生产化与安全治理
─────────────────────────────────────────────────────────
目标: 符合银行合规的生产部署

组件:
  + 敏感指标审批流程
  + 执行审计日志
  + 数据脱敏
  + RAG 知识库融合
  + 多租户隔离

交付: 生产级 ChatBI 系统
```

---

## 十一、与传统 BI 的对比

| 维度 | 传统 BI | ChatBI (本系统) |
|------|---------|----------------|
| **查询方式** | 拖拽构建 | 自然语言 |
| **多轮对话** | 不支持 | 支持 Memory 状态记忆 |
| **复杂查询** | 需要深刻业务理解 | AI 辅助拆解 |
| **上下文理解** | 需要手动选择 | 自动从 Memory/RAG 补全 |
| **归因分析** | 不支持 | 自动多维度归因 |
| **预警机制** | 手动配置阈值 | 自动异常检测 + Push |
| **报告生成** | 手动制作 | 自动生成 + 策略建议 |
| **Schema 变更** | 需手动更新 | 语义层自动映射 |
| **权限控制** | 手动配置行列权限 | 自动注入 |
| **学习曲线** | 高（需培训） | 低（自然语言） |
| **分析延迟** | 小时～天 | 秒～分钟 |

---

## 附录 A: 术语表

| 术语 | 说明 |
|------|------|
| **NL2Semantics** | 自然语言到统一语义层的映射，解决 LLM 幻觉问题 |
| **NL2SQL** | 自然语言到 SQL 的直接转换 |
| **Intent Router** | 意图分类器，判断用户查询类型 |
| **归因分析** | 分析指标异动的根本原因 |
| **语义层** | 统一的指标/标签定义层，确保口径一致 |
| **Code Agent** | 通过执行代码完成复杂业务逻辑 |
| **T+1** | 数据延迟一天，如当日查昨日的数据 |
