# 银行 ChatBI — Hermes Agent + SQLBot 集成方案

> 基于 Hermes Agent 构建银行内部智能数据分析平台，NL2SQL 由 SQLBot 提供，Hermes 担任大脑角色。

---

## 一、整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                      银行员工（用户）                          │
│         自然语言查询 → ChatBI 界面 → 可视化结果                  │
└────────────────────────────┬────────────────────────────────┘
                             │ NL 查询
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                   Hermes Agent（大脑）                        │
│  ┌────────────────┐  ┌─────────────────┐  ┌──────────────┐ │
│  │  Intent Router │  │ Memory (多轮状态) │  │Self-Correction│ │
│  └────────────────┘  └─────────────────┘  └──────────────┘ │
│  ┌─────────────────────────────────────────────────────────┐│
│  │              技能层（Skills / Tools）                   ││
│  │  NL2SQL_Router  │  RAG_Retriever  │  Workflow_Engine  ││
│  └─────────────────────────────────────────────────────────┘│
└──────────────┬──────────────────┬─────────────────┬───────┘
               │                  │                 │
               ▼                  ▼                 ▼
      ┌──────────────┐   ┌──────────────┐  ┌──────────────┐
      │ SQLBot API    │   │ Vector DB     │  │ 元数据中心    │
      │ (NL2SQL 专家) │   │ (RAG 知识库)  │  │ (Metadata)   │
      └───────┬──────┘   └──────────────┘  └──────┬───────┘
              │                                     │
              ▼                                     │
      ┌──────────────┐                             │
      │ 执行 SQL      │◄────────────────────────────┘
      │ 验证结果      │        Schema 映射 / 指标定义
              │
              ▼
      ┌──────────────┐
      │ 可视化 + 响应  │
      └──────────────┘
```

---

## 二、核心组件职责

### 2.1 Hermes Agent — 大脑

Hermes 承担所有协调、推理、纠错工作：

| 能力 | 用途 |
|------|------|
| **Intent Router** | 判断查询类型（简单 SQL / 复杂多步 / 纯知识检索 / 需澄清） |
| **Memory 多轮状态** | 记住当前分析的业务范围、时间上下文、已选指标 |
| **Self-Correction** | SQL 执行失败或结果异常时自动纠错重试 |
| **RAG 上下文补充** | 调用 Vector DB 检索补充业务规则和 Schema 说明 |
| **Workflow 编排** | 复杂多步骤任务拆解调度 |
| **权限审批** | 敏感 SQL 执行前触发人工审批流程 |

### 2.2 SQLBot — NL2SQL 专家

Hermes 通过工具调用 SQLBot 的 NL2SQL API：

```
Hermes 工具调用:
  sqlbot_nl2sql(
    query="杭州分行Q1存款情况",
    schema_context={
      "tables": [...],           # 从元数据中心获取
      "metrics": ["deposit"],    # 指标定义
      "dims": ["branch", "period"],
      "filters": {"branch": "杭州"}
    }
  )
  → 返回: { "sql": "...", "confidence": 0.92, "explanation": "..." }
```

SQLBot 负责：
- Schema 自动映射（物理名 ↔ 逻辑名）
- NL → SQL 转换
- SQL 优化建议

Hermes 负责：
- 调用 SQLBot API
- 补充业务上下文（通过元数据中心）
- 结果验证与纠错

### 2.3 多轮对话 Memory

```
Session Memory 存储内容:
├── current_scope: "杭州分行"
├── current_metrics: ["存款余额"]
├── time_context: "Q1" → "2024Q1"
├── last_query_result: { ... }   # 上次查询结果摘要
└── clarification_history: []     # 澄清历史

Example 对话流:
  用户: "杭州分行的存款情况"
        → Hermes 加载 Memory（无）
        → SQLBot 生成 SQL → 执行 → 结果

  用户: "和上海对比呢？"
        → Hermes 从 Memory 补全"杭州分行"上下文
        → "和[杭州分行]对比呢？"
        → SQLBot 生成对比 SQL

  用户: "加上贷款一起看"
        → Hermes 补全"存款+贷款多指标"
        → 跨指标联合查询
```

### 2.4 RAG 知识库（现有 Vector DB）

```
知识库内容:
├── 指标计算逻辑文档
│   e.g., "净利差(NIM) = (利息收入 - 利息支出) / 生息资产平均余额"
├── 数据库 Schema 说明
│   e.g., "T_DEMAND_DEPOSITS 表 = 活期存款明细"
├── 业务规则文档
│   e.g., "不良贷款 = 逾期90天以上的贷款"
└── 历史 Q&A 案例
    e.g., "Q: 如何查询不良率? A: 使用 T_LOAN_BALANCE ..."

检索时机:
├── 查询前：补充业务上下文到 SQLBot prompt
├── SQL 生成后：验证是否符合业务规则
└── 纠错时：找相似历史正确案例
```

### 2.5 元数据中心（Metadata Center）

作为 Hermes 外部工具接入：

```
元数据中心 = Hermes Tool（读取外部 DB/API）

核心数据:
├── 物理表 → 逻辑名映射
│   T_DEMAND_DEPOSITS → 活期存款
│   T_LOAN_BALANCE    → 贷款余额
│   T_INTERESTFLOW    → 利息流
├── 字典表值
│   BRANCH_CODE: 001=杭州分行, 002=上海分行, 003=深圳分行
│   ACCT_TYPE: 01=对公, 02=对私
├── 指标计算逻辑
│   NIM = (利息收入 - 利息支出) / 生息资产平均余额
│   不良率 = 不良贷款余额 / 贷款总额 × 100%
└── 数据权限
    用户ID → 可访问的 [分支行, 业务线, 数据级别]
```

### 2.6 Self-Correction 纠错流程

```
SQL 执行失败 or 结果异常
        │
        ▼
Hermes 捕获错误信息
        │
        ▼
分析错误类型
        │
        ├── 语法错误 → 提取错误片段 → 反馈 SQLBot 重写
        ├── 语义错误 → 查 RAG 找正确业务逻辑 → 更新 prompt 重试
        ├── 权限不足 → 触发权限申请 + 通知审批人
        ├── 结果为空 → 反问用户收窄范围
        └── 超时/超时 → 提示可尝试的优化方向
        │
        ▼
最多重试 2 次，仍失败 → 给出解释 + 手动调整建议
```

---

## 三、Intent Router 分类

```
用户: "看一下Q1杭州分行的存款情况"

Intent Router 判断:
├── SIMPLE_SQL
│   └── 单一指标 + 单一维度 → 直接走 NL2SQL，单次完成
│
├── COMPLEX_SQL
│   ├── 多指标联合: "存款+贷款+中间业务收入"
│   ├── 多维度对比: "杭州vs上海vs深圳"
│   └── 跨时间对比: "Q1 vs Q2 vs Q3"
│   → 拆解为多个子 SQL → Workflow 编排
│
├── RAG_ONLY
│   └── 纯知识问答: "什么是不良贷款？"
│   → 仅检索 Vector DB，不生成 SQL
│
└── CLARIFICATION
    └── 意图模糊: "存款情况？"
    → 反问澄清: "您想看哪个时间段的哪家分行的存款？"
```

---

## 四、关键集成点

| 集成点 | 方式 | 优先级 |
|--------|------|--------|
| SQLBot NL2SQL | Custom tool `tools/sqlbot_tool.py` | P0 |
| Vector DB (RAG) | MCP Server 或 custom tool | P1 |
| 元数据中心 | Custom tool `tools/metadata_center_tool.py` | P0 |
| Memory 多轮 | Hermes 内置 `memory` 工具 | P0 |
| Workflow 编排 | Hermes `delegate_task` / `cron` 工具 | P2 |
| 权限审批 | `tools/approval.py` 机制 | P1 |
| 可视化输出 | Rich table / 图表库 | P2 |

### 4.1 SQLBot 工具示例

```python
# tools/sqlbot_tool.py

def sqlbot_nl2sql(
    query: str,
    schema_context: dict = None,
    conversation_history: list = None,
) -> str:
    """
    调用 SQLBot NL2SQL API。
    schema_context 从元数据中心获取。
    conversation_history 从 Memory 获取。
    """
    import requests

    response = requests.post(
        f"{SQLBOT_API_URL}/nl2sql",
        json={
            "query": query,
            "schema_context": schema_context or {},
            "history": conversation_history or [],
        },
        timeout=30,
    )
    result = response.json()
    return json.dumps(result, ensure_ascii=False)

# Registry
registry.register(
    name="sqlbot_nl2sql",
    toolset="banking",
    schema=SQLBOT_NL2SQL_SCHEMA,
    handler=lambda args, **kw: sqlbot_nl2sql(
        query=args.get("query", ""),
        schema_context=args.get("schema_context"),
        conversation_history=kw.get("conversation_history"),
    ),
)
```

### 4.2 元数据中心工具示例

```python
# tools/metadata_center_tool.py

def get_schema_mapping(business_domain: str = None) -> str:
    """获取物理表→逻辑名映射。"""
    ...

def get_metric_definition(metric_name: str) -> str:
    """获取指标计算逻辑。"""
    ...

def get_dict_values(dict_code: str) -> str:
    """获取字典表值。"""
    ...

def get_user_permissions(user_id: str) -> str:
    """获取用户数据权限范围。"""
    ...
```

---

## 五、实现阶段

```
Phase 1: 核心链路跑通
─────────────────────────────────────────
目标: 单表查询 + 多轮对话 + 基础纠错

组件:
  ✓ Hermes Agent (核心)
  ✓ SQLBot NL2SQL (API 接入)
  ✓ Memory 多轮状态
  ✓ 简单 Intent Router

交付: 用户输入自然语言 → 返回 SQL + 结果

Phase 2: 上下文增强
─────────────────────────────────────────
目标: Schema 自动映射 + RAG 知识补充

组件:
  + 元数据中心接入 (Schema 映射/指标定义/字典表)
  + Vector DB RAG (指标计算逻辑/业务规则)
  + 权限数据注入

交付: 带业务上下文的 NL2SQL，权限自动过滤

Phase 3: 复杂场景扩展
─────────────────────────────────────────
目标: 多指标、多维度、跨时间对比

组件:
  + Workflow 编排 (复杂查询拆解)
  + 复杂意图拆解 (Intent Router v2)
  + 可视化输出 (表格/图表)

交付: "杭州+上海+深圳三地Q1-Q3存贷款对比"

Phase 4: 安全与治理
─────────────────────────────────────────
目标: 生产级安全管控

组件:
  + 敏感 SQL 审批流程 (approval.py)
  + 执行审计日志
  + 数据脱敏处理
  + 行级权限控制

交付: 符合银行合规要求的生产部署
```

---

## 六、Skill 技能设计

为银行 ChatBI 场景创建专属技能：

```
~/.hermes/skills/banking/
├── nl2sql-query/
│   ├── SKILL.md          # NL2SQL 查询规范
│   └── references/
│       ├── schema-mapping.md
│       └── metric-definitions.md
├── multi-turn-analysis/
│   └── SKILL.md          # 多轮对话分析规范
├── complex-query-splitter/
│   └── SKILL.md          # 复杂查询拆解工作流
└── self-correction/
    └── SKILL.md          # SQL 纠错规范
```

### Skill 示例: `nl2sql-query/SKILL.md`

```yaml
---
name: banking-nl2sql-query
description: 银行 NL2SQL 查询规范 — 如何构造查询、补充上下文、验证结果
version: 1.0.0
platforms: [linux, darwin]
metadata:
  hermes:
    tags: [banking, nl2sql, sqlbot]
    requires_tools: [sqlbot_nl2sql, metadata_center]
---

# 银行 NL2SQL 查询规范

## 查询流程

1. **解析用户意图**
   - 提取关键实体：机构名、产品名、时间
   - 判断查询类型：余额/发生额/对比/趋势

2. **补充 Schema 上下文**
   ```
   调用: metadata_center.get_schema_mapping(business_domain="存款")
   调用: metadata_center.get_metric_definition("存款余额")
   调用: metadata_center.get_dict_values("BRANCH_CODE")
   ```

3. **构造 SQLBot 请求**
   ```json
   {
     "query": "杭州分行Q1存款余额",
     "schema_context": {
       "tables": ["T_DEMAND_DEPOSITS"],
       "metrics": [{"name": "存款余额", "calc": "SUM(balance)"}],
       "dims": ["branch_code", "period"]
     }
   }
   ```

4. **结果验证**
   - 检查是否为空结果
   - 检查是否符合业务逻辑（如：存款余额 > 0）
   - 异常时触发 Self-Correction

## 已知问题

- 时间表达 "Q1" 需要映射为具体日期范围
- "分行" 需要映射为 BRANCH_CODE
```

---

## 七、与传统 BI 的对比

| 维度 | 传统 BI | ChatBI (Hermes+SQLBot) |
|------|---------|----------------------|
| **查询方式** | 拖拽构建 | 自然语言 |
| **多轮对话** | 不支持 | 支持 Memory 状态记忆 |
| **复杂查询** | 需要深刻业务理解 | AI 辅助拆解 |
| **上下文理解** | 需要手动选择 | 自动从 Memory/RAG 补全 |
| **纠错方式** | 重新拖拽 | 自动 Self-Correction |
| **Schema 变更** | 需手动更新 | SQLBot 自动映射 |
| **权限控制** | 手动配置行列权限 | 自动注入用户权限 |
| **学习曲线** | 高（需培训） | 低（自然语言） |
