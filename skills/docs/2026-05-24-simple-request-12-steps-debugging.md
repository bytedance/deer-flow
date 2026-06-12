# Data-Analysis Skill 调试报告：简单请求为何需要 12+ 步骤

**日期**：2026-05-24
**调查人**：Claude Code (Systematic Debugging Process)
**根因**：Skill 缺少 Simple 级触发示例，LLM 默认采用保守多步骤方案

---

## 问题描述

用户上传 Excel/CSV 文件后，说"分析我上传的文件"或类似的简单请求，Agent 需要 12+ 步骤才能完成，而实际上 Simple 级请求应该在 4-6 步内完成。

---

## 第一阶段：根因调查

### 1.1 Skill 调用流程分析

**结论**：完全由 LLM 驱动，没有程序化的 skill 匹配器。

```
用户上传文件 → UploadsMiddleware 注入 <uploaded_files> → LLM 处理系统提示
→ LLM 根据 skill 描述匹配 "Excel/CSV 分析" → 读取 SKILL.md → 执行 analyze.py
```

关键发现：
- Skill 触发机制完全依赖 LLM 对描述的语义匹配
- 没有程序化条件判断或 step counting 机制
- LoopDetectionMiddleware 有适当阈值，未阻塞合法工作

### 1.2 analyze.py 分析

**结论**：工作正常，无 bug。

- 支持 `inspect`、`query`、`summary`、`overview` 四种 action
- 双层缓存机制（L1 展平 CSV + L2 DuckDB）工作正常
- 多级表头展平功能正常（header_processor.py）

### 1.3 UploadsMiddleware 分析

**结论**：正确注入 `<uploaded_files>` 上下文。

- 正确读取 `additional_kwargs.files` 并注入文件信息
- 正确处理历史文件和新建文件
- 文件路径解析正确

### 1.4 LoopDetectionMiddleware 分析

**结论**：未阻塞合法工作。

- 哈希层：警告阈值 3，停止阈值 5（相同工具调用）
- 频率层：警告阈值 30，停止阈值 50（同类工具调用）
- 日志显示警告正确注入，未强制停止

---

## 第二阶段：根因确定

### 主根因：Simple 级请求处理存在歧义

SKILL.md 的复杂度表格：

| 级别 | 原判断标准 | 执行模式 |
|------|-----------|----------|
| **Simple** | 模糊/泛化请求，不知问什么 | inspect → 一句话描述 → 结束 |
| **Medium** | 明确的多维度聚合需求 | inspect → 合并 query → 结束 |
| **Complex** | 明确要求报告/趋势/对比 | inspect → overview → summary → query → 结束 |

**问题**：
1. "模糊/泛化请求" 定义过于抽象，LLM 难以匹配
2. 缺少具体的触发示例
3. "分析我上传的文件" 处于模糊地带，LLM 采取保守策略

### 次根因：Skill 缺少 Simple 级示例

SKILL.md 有：
- Medium 级完整示例（"Analyze my sales data — show top products by revenue"）
- Complex 级查询模式示例

**缺少**：
- Simple 级触发短语示例
- Simple vs Medium vs Complex 的明确边界

### 第三根因：inspect 本身的成本

对于 Excel 文件，`inspect` 需要：
1. 统计每个 sheet 的行数
2. 获取每个列的类型和空值信息
3. 计算每列非空计数（每列一次独立 SQL）
4. 取样 5 行数据

如果 LLM 选择 Simple → inspect，然后又追加 query，就形成了浪费。

---

## 第三阶段：解决方案

### 修复内容

| 修改点 | 内容 |
|--------|------|
| **1. 复杂度表格重构** | 将抽象描述改为具体触发短语 |
| **2. 新增 Simple 级触发示例** | 5 个具体示例（中英双语） |
| **3. Simple 执行流程规则** | 严格遵守：仅 inspect → 一句话 → 结束 |
| **4. 执行边界规则** | inspect 后不自动追加 query |
| **5. 4 步 vs 12 步对比** | 直观展示两种请求的执行差异 |

### 修改文件

- `skills/public/data-analysis/SKILL.md`（+49 行）

### 修改前后对比

**修改前**：
```
| Level | 判断标准 | 执行模式 |
|-------|----------|----------|
| **Simple** | 模糊/泛化请求，不知问什么 | inspect → 一句话描述 → 结束 |
| **Medium** | 明确的多维度聚合需求 | inspect → 合并 query → 结束 |
| **Complex** | 明确要求报告/趋势/对比 | inspect → overview → summary → 1次 query → 结束 |
```

**修改后**：
```
| Level | 判断标准 | 执行模式 |
|-------|----------|----------|
| **Simple** | "分析文件"、"看看数据"、"这是什么" | inspect → 一句话描述 → 结束 |
| **Medium** | "哪些"、"top N"、"按...汇总" | inspect → 合并 query → 结束 |
| **Complex** | "报告"、"趋势"、"环比同比" | inspect → overview → summary → 1次 query → 结束 |
```

### 新增内容

#### Simple 级请求的触发示例

```markdown
### Simple 级请求的触发示例

以下用户话语**明确属于 Simple 级**，应直接返回一句话数据概览后结束：

| 用户输入（中文） | 用户输入（英文） | 说明 |
|----------------|----------------|------|
| "分析这个文件" | "analyze this file" | 最典型的 Simple 请求 |
| "看看数据情况" | "look at the data" | 泛化了解数据 |
| "这是什么表" | "what is this table" | 仅需了解表结构 |
| "帮我看看" | "take a look at it" | 无明确目标的查看 |
| "数据怎么样" | "how's the data" | 泛化数据质量了解 |

**Simple 级执行流程**（必须严格遵守）：
1. 仅执行一次 `inspect` action
2. 用一句话描述数据概况（行数、列数、关键字段）
3. **不执行任何 query、summary、overview**

❌ **常见错误**：执行完 inspect 后又追加 query — 这属于 Medium 级
```

#### 执行边界规则

```markdown
> [!IMPORTANT]
> **执行边界规则**：
> - `inspect` = 表结构 + 行数 + 列类型 + 非空率 → 足以回答"这是什么"
> - 如果用户追问"哪些"、"多少"、"排序"，**那是新的 Medium 级请求**
> - 不要在 inspect 后自动追加 query，除非用户明确要求分析
```

#### 执行步骤对比

```markdown
### 执行步骤对比

**Simple 请求示例**（4 步完成）：
```
用户: "分析这个文件"
Agent:
  Step 1: inspect → 获取表结构
  Step 2: 一句话描述 → "该表为销售订单表，共 1523 行，8 列，包含 order_id、product、amount、date 等字段"
  [结束]
```

**Complex 请求示例**（12 步完成）：
```
用户: "生成季度销售报告，包含各产品线环比同比分析"
Agent:
  Step 1-2: inspect + overview → 获取表结构和大致数据
  Step 3: summary → 获取数值列统计
  Step 4-12: 多次 query → 聚合、环比、同比计算
  [结束]
```

**核心原则**：用户说"分析"不代表要报告。用最少的步骤满足用户需求。
```

---

## 验证计划

1. 上传一个 Excel/CSV 文件
2. 输入简单请求如"分析这个文件"或"看看数据情况"
3. 观察 Agent 是否在 4-6 步内完成（而非 12+ 步）
4. 检查输出是否为一话数据概览（而非多步查询结果）

---

## 相关文件

| 文件 | 说明 |
|------|------|
| `skills/public/data-analysis/SKILL.md` | Skill 定义文件（已修改） |
| `skills/public/data-analysis/scripts/analyze.py` | DuckDB 分析脚本 |
| `skills/public/data-analysis/scripts/header_processor.py` | Excel 多级表头展平 |
| `backend/packages/harness/deerflow/agents/middlewares/uploads_middleware.py` | 文件上传中间件 |
| `backend/packages/harness/deerflow/agents/middlewares/loop_detection_middleware.py` | 循环检测中间件 |