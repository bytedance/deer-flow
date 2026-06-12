# DeerFlow SOUL.md 定义指南

## 什么是 SOUL.md

SOUL.md 是定义 DeerFlow Agent 灵魂/人格的核心文件，用于定义 Agent 的：
- **人格特质**：性格、价值观、行为准则
- **专业能力**：擅长领域、服务范围
- **对话风格**：交流方式、语气用词
- **行为边界**：禁止事项、风险提示

SOUL.md 的内容会被注入到 Lead Agent 的系统提示词中，影响 Agent 的整体行为模式。

---

## SOUL.md 存放位置

### 目录结构

```
{base_dir}/                    # DeerFlow 根目录（.deer-flow/）
├── SOUL.md                    # ⭐ 全局默认 Agent 灵魂文件
├── USER.md                    # 全局用户配置文件
├── config.yaml
└── agents/
    └── {agent_name}/
        ├── SOUL.md            # Agent 特定的灵魂文件（覆盖全局）
        └── config.yaml
```

### 实际路径

| 类型 | 路径 |
|------|------|
| Docker 部署 | `/backend/.deer-flow/SOUL.md` |
| 本地开发 | `./.deer-flow/SOUL.md` |
| 用户私有 Agent | `{base_dir}/users/{user_id}/agents/{name}/SOUL.md` |
| 共享 Agent | `{base_dir}/agents/{name}/SOUL.md` |

可通过 `DEER_FLOW_HOME` 环境变量配置基础目录。

---

## SOUL.md 创建方式

### 方式一：手动创建

直接在 DeerFlow 根目录（`.deer-flow/`）创建 `SOUL.md` 文件。

### 方式二：通过 API

```bash
# 创建 Agent 时附带 SOUL
POST /api/agents
{
  "name": "my-agent",
  "description": "我的智能助手",
  "soul": "# SOUL.md 内容..."
}

# 更新现有 Agent 的 SOUL
PUT /api/agents/my-agent
{
  "soul": "# 新 SOUL 内容..."
}
```

---

## SOUL.md 模板示例

### 基础模板

```markdown
# SOUL.md

## 身份定位
[Agent 的名称、角色定位]

## 核心能力
[擅长的领域和服务]

## 行为准则
[应该怎么做]

## 禁止行为
[什么不能做]

## 对话风格
[如何交流]
```

### 银行智能助手示例

```markdown
# 银行智能助手 SOUL

## 身份定位
你是一个专业的银行内部智能助手，名为"小银"，专为银行员工提供智能化服务。

## 核心能力
- **知识问答**：解答银行规章制度、业务流程相关问题
- **文档校验**：帮助审核各类银行文档
- **AI 写作**：协助撰写报告、邮件、公文等
- **制度问答**：解读银行制度政策
- **反洗钱查询**：辅助反洗钱相关问题查询

## 行为准则
1. **安全优先**：不泄露客户隐私信息，不提供违规建议
2. **专业严谨**：引用准确制度条款，注明信息来源
3. **主动服务**：预判用户需求，提供延伸建议
4. **及时反馈**：遇到无法解答的问题，主动说明并建议咨询相关部门

## 禁止行为
- 不回答与银行业务无关的闲聊问题
- 不提供未经授权的业务操作建议
- 不承诺任何涉及风险的操作
- 不在回复中透露内部系统细节

## 对话风格
- 称呼用户为"您"
- 使用正式、专业的银行用语
- 回复结构清晰，要点分明
- 重要信息用列表或表格呈现
```

### 通用助手示例

```markdown
# 智能助手 SOUL

## 身份定位
你是一个乐于助人的 AI 助手，名为"小智"。

## 核心能力
- 回答各类问题，提供信息检索服务
- 协助完成写作、编程、分析等任务
- 提供建议和方案参考

## 行为准则
1. **诚实透明**：不清楚的问题如实告知，不编造答案
2. **有礼貌**：使用友好、专业的语气
3. **有条理**：回复逻辑清晰，重点突出

## 禁止行为
- 不进行任何违法活动
- 不传播虚假信息
- 不参与有争议的政治话题

## 对话风格
- 亲切友好，专业可靠
- 回答简洁明了，必要时提供详细说明
```

---

## SOUL.md 最佳实践

### 1. 结构清晰

使用 Markdown 标题层级划分不同部分，便于维护和阅读。

### 2. 角色具体

避免泛泛而谈，定义具体的 Agent 人设和形象。

### 3. 边界明确

清晰列出禁止行为，避免 Agent 执行不当操作。

### 4. 语言一致

用词风格统一，与 Agent 的人设一致。

### 5. 适度长度

建议控制在 500-1500 字，过长会影响 prompt 效果。

---

## Agent 定义所需文件

### 必须文件

| 文件 | 说明 | 必填 |
|------|------|------|
| `config.yaml` | Agent 配置文件 | ✅ 必须 |
| `SOUL.md` | Agent 灵魂/人格定义 | 建议有 |

### config.yaml 结构

```yaml
name: my-agent           # Agent 名称（必须）
description: "描述"      # Agent 描述
model: "gpt-4"          # 指定模型（可选）
tool_groups:            # 工具组合（可选）
  - "dify"
skills:                 # 技能白名单（可选）
  - "skill1"
  # - None: 加载所有技能
  # - []: 禁用所有技能
```

### Agent 目录结构

```
{base_dir}/
├── agents/                    # 共享 Agent（遗留）
│   └── my-agent/
│       ├── config.yaml
│       └── SOUL.md
└── users/{user_id}/agents/    # 用户私有 Agent
    └── my-agent/
        ├── config.yaml
        └── SOUL.md
```

---

## 验证 SOUL.md 是否生效

### 1. 检查文件存在

```bash
ls -la {base_dir}/SOUL.md
```

### 2. 通过 API 查看

```bash
# 查看所有 Agent
GET /api/agents

# 查看特定 Agent
GET /api/agents/my-agent
```

### 3. 查看日志

启动时观察日志中是否有 SOUL 加载记录。

---

## 注意事项

| 项目 | 说明 |
|------|------|
| 编码 | 必须 UTF-8 |
| 格式 | Markdown |
| 加载时机 | Agent 初始化时注入到 Lead Agent 的系统提示词 |
| 优先级 | Agent 专属 SOUL > 全局 SOUL |
| 继承关系 | 子 Agent 继承父 Agent 的部分 SOUL 特性 |

---

## 相关文件

- `backend/packages/harness/deerflow/config/agents_config.py` - SOUL 加载逻辑
- `backend/app/gateway/routers/agents.py` - Agent 管理 API
