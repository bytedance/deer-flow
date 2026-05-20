# DeerFlow 2.0 Banking Platform — 功能裁剪计划

**目标**：100 并发用户，Standard 模式，金融银行 AI 平台
**原则**：仅裁剪无关模块，暂不新增功能

---

## 1. Skills 裁剪 — 删除 20 个无关 Skill

**删除 `skills/public/` 下所有无关 Skill**：
```
academic-paper-review, bootstrap, chart-visualization,
claude-to-deerflow, code-documentation, consulting-analysis,
data-analysis, deep-research, find-skills, frontend-design,
github-deep-research, image-generation, newsletter-generation,
podcast-generation, ppt-generation, skill-creator, surprise-me,
systematic-literature-review, vercel-deploy-claimable,
video-generation, web-design-guidelines
```

**保留**：`find-skills`（技能发现可用）

---

## 2. Feature Flags 关闭

修改 `config.yaml`：

| 配置项 | 当前值 | 改为 | 原因 |
|--------|--------|------|------|
| `summarization.enabled` | true | **false** | 节省延迟，100用户无需上下文压缩 |
| `title.enabled` | true | **false** | 银行线程使用正式ID，无需自动标题 |
| `guardrails` | 未设置 | **false** | 无需 Guardrail 中间件 |
| `memory.enabled` | false | 保持 false | 银行数据合规 |
| `token_usage.enabled` | false | 保持 false | 已是关闭状态 |

**无需代码修改**，全部通过 config.yaml 控制。

---

## 3. Community Tools 移除

从 `config.yaml` 的 `tools[]` 中删除：
- `web_search` (tavily)
- `image_search`

这些默认已禁用，但明确列出则会被加载。确认无其他 community tools。

---

## 4. IM Channels — 已确认关闭

6 个通道（Feishu、Slack、Telegram、WeChat、WeCom、Discord）均默认 `enabled: false`。Web 端部署无需 IM 集成。确认配置中无 `channels:` 段落。

---

## 5. Middleware 裁剪

**始终启用（8个，架构性）**：无法移除
- ThreadDataMiddleware — 每线程隔离目录
- UploadsMiddleware — 文件上传追踪
- DanglingToolCallMiddleware — 中断 ToolCall 修复
- LLMErrorHandlingMiddleware — Provider 错误标准化
- SandboxAuditMiddleware — 安全审计
- ToolErrorHandlingMiddleware — 工具异常恢复
- LoopDetectionMiddleware — 循环检测
- ClarificationMiddleware — 澄清拦截

**配置控制（关闭）**：

| Middleware | Config Key | 操作 |
|-----------|-----------|------|
| SummarizationMiddleware | `summarization.enabled` | 设为 false |
| TitleMiddleware | `title.enabled` | 设为 false |
| GuardrailMiddleware | `guardrails` | 设为 false |
| MemoryMiddleware | `memory.enabled` | 保持 false |
| TokenUsageMiddleware | `token_usage.enabled` | 保持 false |

---

## 6. 多租户隔离 — 确认可用

`ThreadDataMiddleware` 创建每线程隔离目录：
```
backend/.deer-flow/threads/{thread_id}/user-data/{workspace,uploads,outputs}
```
Thread ID 是租户隔离键。开箱即用，无需修改。

---

## 7. 实施步骤

| 步骤 | 操作 | 说明 |
|------|------|------|
| 1 | 删除 20 个 Skill 目录 | `skills/public/` 下无关 Skill |
| 2 | 更新 `config.yaml` | 关闭 summarization、title、guardrails |
| 3 | 从 `tools[]` 移除 | web_search、image_search |
| 4 | 验证 | `make check` → `make dev` |

---

## 8. 关键文件

| 文件 | 操作 |
|------|------|
| `config.yaml` | 修改 — 关闭 features |
| `skills/public/` | 删除 20 个无关 Skill 目录 |

**无代码修改需求**，全部通过配置和文件删除完成。

---

## 9. 验证方式

```bash
# 1. 检查配置
make check

# 2. 启动服务
make dev

# 3. 确认 Skill 列表（只剩 find-skills）
curl http://localhost:8001/api/skills

# 4. 确认中间件链（关闭的中间件不加载）
# 查看 agent.py 日志确认启动无报错
```

---

**后续（本次不执行）**：
- 创建 banking-chatbi、banking-rag、banking-ocr、banking-report 技能 → `skills/custom/`
- 在 `extensions_config.json` 中启用上述技能
- MCP 服务器集成（SQLBot、Dify、RAGFlow）