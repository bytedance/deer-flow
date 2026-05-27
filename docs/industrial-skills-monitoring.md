# 工业智能技能监控系统

本文档介绍工业智能平台的监控和遥测系统，用于跟踪**采用深度（Adoption Depth）**、引导流程完成率和技能分层管理效果。

## 监控指标概览

### 1. 技能调用统计

跟踪所有技能的调用情况，关注 Top 热门技能：

- **工业智能技能** (`core-industrial`): 设备诊断、监测分析、趋势报告等
- **基础技能** (`foundation`): 数据分析、通用问答等

**关键指标**：
- 总调用次数
- Top 10 热门技能列表
- 每日调用趋势（最近 7 天）

### 2. 采用深度指标（Adoption Depth）

跟踪用户对工业智能功能的深度采用情况：

- **工作流完成次数**: 用户完成的工业工作流（诊断、趋势分析等）
- **模板使用次数**: 用户使用的工业报告模板
- **Agent 创建次数**: 用户创建的工业智能 Agent

**关键指标**：

- 工作流完成次数
- 模板使用次数
- Agent 创建次数

### 3. 采用漏斗（Adoption Funnel）

五阶段用户采用漏斗，跟踪从引导到深度采用的完整路径：

| 阶段                          | 描述                   |
| ----------------------------- | ---------------------- |
| 1. `onboarding_started`       | 用户开始引导流程       |
| 2. `onboarding_completed`     | 用户完成引导流程       |
| 3. `first_workflow_run`       | 用户首次运行工业工作流 |
| 4. `workflow_completed`       | 用户完成工业工作流     |
| 5. `template_or_agent_created` | 用户创建模板或 Agent  |

**转化率计算**：各阶段用户数相对于第一阶段（`onboarding_started`）的百分比。

### 4. 价值实现时间（Time-to-Value）

从用户开始使用到完成首次工作流的时间统计：

- **中位数**：50% 用户的价值实现时间
- **P25**：25% 用户的价值实现时间（较快用户）
- **P75**：75% 用户的价值实现时间（较慢用户）
- **最小值 / 最大值**

### 5. 引导流程完成率

跟踪新用户引导流程的完成情况：

- **完成引导**: 用户完成所有 5 个引导步骤
- **跳过引导**: 用户主动跳过引导

**关键指标**：
- 完成次数
- 跳过次数
- 完成率（目标：≥ 70%）

### 6. 技能分层管理

跟踪管理员对技能层级的调整操作：

- **单独调整**: 管理员修改单个技能的层级
- **批量调整**: 管理员批量修改多个技能的层级
- **升级**: 技能从基础层升级到工业智能层
- **降级**: 技能从工业智能层降级到基础层

**关键指标**：
- 单独调整次数
- 批量调整次数
- 升级技能数量
- 降级技能数量

## 数据来源

### 前端遥测

前端通过 `frontend/src/core/industrial-skills/telemetry.ts` 收集以下事件：

```typescript
// 技能调用
trackSkillInvocation("vibration-diagnosis", "core-industrial", userId, tenantId);

// 引导流程完成
trackOnboardingComplete(userId, tenantId);

// 引导流程跳过
trackOnboardingSkip(userId, tenantId);

// 技能层级调整
trackSkillTierChange("data-analysis", "foundation", "core-industrial", userId, tenantId);
```

**缓冲策略**：
- 最大缓冲数量：100 个事件
- 刷新间隔：15 秒
- 批量发送到后端

### 后端 API

后端提供两个 API 端点：

#### 1. 接收遥测数据

```http
POST /api/telemetry/industrial-skills
Content-Type: application/json

{
  "events": [
    {
      "type": "skill_invocation",
      "skill_name": "vibration-diagnosis",
      "tier": "core-industrial",
      "timestamp": "2026-05-26T10:30:00Z"
    }
  ]
}
```

#### 2. 查询监控摘要

```http
GET /api/telemetry/industrial-skills/summary
```

**响应示例**：

```json
{
  "skill_invocations": {
    "total": 1250,
    "top_skills": {
      "vibration-diagnosis": 320,
      "trend-report": 280,
      "device-monitoring": 245
    }
  },
  "onboarding": {
    "completed": 89,
    "skipped": 23,
    "completion_rate": 79.5
  },
  "adoption_depth": {
    "workflow_completions": 456,
    "template_usage_count": 234,
    "agent_creation_count": 78
  },
  "tier_management": {
    "single_changes": 15,
    "batch_changes": 3,
    "promoted": 12,
    "demoted": 6
  }
}
```

#### 3. 查询采用漏斗

```http
GET /api/telemetry/industrial-skills/adoption-funnel
```

**响应示例**：

```json
{
  "stages": {
    "onboarding_started": 100,
    "onboarding_completed": 85,
    "first_workflow_run": 72,
    "workflow_completed": 58,
    "template_or_agent_created": 35
  },
  "conversion_rates": {
    "onboarding_started": 100.0,
    "onboarding_completed": 85.0,
    "first_workflow_run": 72.0,
    "workflow_completed": 58.0,
    "template_or_agent_created": 35.0
  },
  "total_users_at_top": 100
}
```

#### 4. 查询价值实现时间

```http
GET /api/telemetry/industrial-skills/time-to-value
```

**响应示例**：

```json
{
  "sample_count": 456,
  "median_ms": 180000,
  "p25_ms": 120000,
  "p75_ms": 300000,
  "min_ms": 45000,
  "max_ms": 900000
}
```

## 健康检查与告警

### 建议告警阈值

| 指标                    | 警告阈值      | 严重阈值      | 说明                       |
| ----------------------- | ------------- | ------------- | -------------------------- |
| 引导完成率              | < 60%         | < 50%         | 引导流程可能存在问题       |
| 工作流完成率（日）      | < 20          | < 10          | 工业功能采用率过低         |
| 技能调用总量（日）      | < 50          | < 20          | 系统使用率过低             |
| 价值实现时间 P75        | > 600000ms    | > 900000ms    | 用户上手速度过慢           |

### 监控仪表板

建议配置以下仪表板面板：

1. **采用漏斗图**: 五阶段用户转化漏斗
2. **每日调用趋势折线图**: 最近 7 天的调用量趋势
3. **引导完成率仪表盘**: 实时显示完成率
4. **Top 10 技能排行榜**: 最受欢迎技能列表
5. **价值实现时间分布**: 中位数、P25、P75 统计
6. **技能层级变更日志**: 管理员操作记录

## 功能开关

工业智能优先已成为平台的永久战略方向，不再是可配置的实验性特性。

`NEXT_PUBLIC_INDUSTRIAL_FIRST` 特性开关已被移除。工业智能优先策略始终启用，无法通过配置回滚到通用优先模式。

如需临时调整平台行为，请联系开发团队通过代码变更实现。

## 数据分析建议

### 定期分析（每周/每月）

1. **工业技能采用率趋势**
   - 计算过去 30 天的工业技能占比变化
   - 识别增长或下降趋势

2. **引导流程效果评估**
   - 对比完成引导 vs 跳过引导用户的后续行为
   - 分析完成率与用户留存的关系

3. **技能分层合理性**
   - 分析被降级技能的原始使用频率
   - 评估升级技能的新增使用量

4. **用户行为分群**
   - 按引导完成情况分群
   - 按技能偏好分群（工业派 vs 通用派）

### 报告模板

可创建专门的报告模板，定期生成工业智能监控报告：

```yaml
name: industrial-skills-monitoring
sections:
  - name: 概览
    components:
      - type: metric-cards
        data:
          - label: 工作流完成次数
            value: $workflow_completions
          - label: 模板使用次数
            value: $template_usage_count
          - label: Agent 创建次数
            value: $agent_creation_count
          - label: 引导完成率
            value: $onboarding_completion_rate
            unit: "%"

  - name: 采用漏斗
    components:
      - type: funnel-chart
        data: $adoption_funnel
        stages:
          - onboarding_started
          - onboarding_completed
          - first_workflow_run
          - workflow_completed
          - template_or_agent_created

  - name: 价值实现时间
    components:
      - type: metric-cards
        data:
          - label: 中位数
            value: $ttv_median_ms
            unit: "ms"
          - label: P25
            value: $ttv_p25_ms
            unit: "ms"
          - label: P75
            value: $ttv_p75_ms
            unit: "ms"

  - name: 热门技能
    components:
      - type: table
        data: $top_skills
        columns:
          - name: 技能名称
            key: name
          - name: 调用次数
            key: count
```

## 故障排查

### 遥测数据未上报

**检查步骤**：
1. 浏览器开发者工具 → Network 标签
2. 查找 `/api/telemetry/industrial-skills` 请求
3. 检查请求状态码和响应
4. 查看控制台是否有错误日志

**常见原因**：
- 后端 API 未启动
- 网络请求被 CORS 阻止
- 遥测缓冲区未达到刷新阈值

### 监控数据不准确

**检查步骤**：
1. 确认前端正确调用跟踪函数
2. 验证后端 API 接收到的事件数据
3. 检查时区设置是否正确
4. 确认聚合逻辑无误

### 引导流程完成率异常低

**可能原因**：
- 引导流程设计过于复杂
- 引导内容不够吸引人
- 跳过按钮过于显眼
- 目标用户不是新用户

**优化建议**：
- 简化引导步骤
- 增加互动元素
- 突出引导价值
- 优化跳过按钮位置

## 扩展功能

### 计划中的增强

1. **实时通知**: 当采用漏斗转化率低于阈值时发送告警
2. **用户旅程分析**: 追踪用户从引导到技能使用的完整路径
3. **A/B 测试框架**: 对比不同引导流程版本的效果
4. **预测模型**: 基于历史数据预测技能使用趋势
5. **自动化报告**: 定期生成并发送监控报告

## 相关文件

- 前端遥测: `frontend/src/core/industrial-skills/telemetry.ts`
- 后端 API: `backend/app/gateway/routers/industrial_skills_telemetry.py`
- 后端测试: `backend/tests/test_industrial_telemetry.py`
- 前端导航: `frontend/src/components/workspace/workspace-nav-chat-list.tsx`
- 引导流程: `frontend/src/components/workspace/industrial-onboarding-overlay.tsx`
