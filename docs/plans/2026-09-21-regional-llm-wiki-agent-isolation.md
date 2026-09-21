# 区域 LLM Wiki 专属 Agent：真实访问隔离设计

> 状态：**待审核，未实施**  
> 目标：在不改变现有 Agent、`/mnt/knowledge`、产品知识库 Skill 或 DeerFlow 问答链路的前提下，新增一个只能读取已发布 LLM Wiki 与其受限证据快照的专属 Agent。

## 1. 结论

本方案不把 LLM Wiki 作为通用 sandbox 挂载给 DeerFlow，也不依赖 `SOUL.md` 或 Skill 文本约束模型“不要读别的目录”。

采用三层同时生效的边界：

```text
专属 Agent 的工具白名单
        +
专用只读检索工具的资源白名单
        +
Gateway 专属只读发布快照挂载
```

模型只能调用四个专用工具，工具只接受页面/证据 ID，绝不接受主机路径或任意 shell 参数。通用 `read_file`、`grep`、`glob`、`bash`、Web、MCP 与写入工具均不绑定给该 Agent。即使 Skill 指令被忽略或用户提示词含有越权要求，也不能扩展该 Agent 的可读范围。

现有 `product-kb-qa` Skill 和使用 `/mnt/knowledge` 的生产知识库不变。

## 2. 范围与非目标

### 本次范围

- 新增一个区域 LLM Wiki 专属 Agent。
- 新增一个只读问答 Skill。
- 新增四个只读、路径受控的 DeerFlow 工具。
- 为该 Agent 增加构建期工具名白名单和必需 Skill 注入能力。
- 约定 LLM Wiki 发布快照给 Agent 消费的只读清单格式。
- 增加单元、集成、容器挂载和问答验收测试。

### 明确不做

- 不修改现有 `product-kb-qa`、已有 Agent、`/mnt/knowledge`、DeerFlow 全局知识库挂载或原始同步任务。
- 不让 Agent 自动访问 TFS 原件、Git 仓库、DeerFlow 聊天记录或 LLM Wiki 编译工作目录。
- 不授予该 Agent Bash、文件写入、网络、Web、MCP、子 Agent 或 Agent 管理能力。
- 不在本期实现面向所有 Agent 的通用 RBAC；本方案只为新增 Agent 提供可验证的最小权限边界。

## 3. 当前事实与风险

现有自定义 Agent 可用 `skills` 与 `tool_groups` 控制可发现的 Skill 和普通配置工具，但它们不足以构成资源隔离：

1. `sandbox.mounts` 是应用级配置。若将新知识库挂到通用 sandbox，任何持有 `file:read` 的 Agent 理论上均可尝试读取。
2. `tool_groups` 仅筛选配置化工具；MCP 与内建工具的装配路径不同，不能把它单独当作全量能力白名单。
3. Skill 的 `allowed-tools` 在 Skill 被显式激活或实际加载后才会执行；单靠“Agent 有这个 Skill”并不能在首个模型调用前移除其他工具。
4. 当前产品知识库 Skill 直接使用 `/mnt/knowledge` 和通用文件工具，适用于既有生产链路，但不满足本方案的 Agent 级访问边界。

因此，本方案在 **Agent 装配阶段** 移除不应出现的工具，并在 **专用工具执行阶段** 校验资源 ID、发布版本、路径解析和读取范围。

## 3.1 既有 Agent 与 Skill 的复用边界

本方案不是从零重新定义问答质量规则。现有 `product-kb-qa` 已积累了适用于 LLM Wiki 的证据工作流，应当以新的专用工具重新实现这些规则；但不能直接复制其权限模型。

| 既有能力 | 处理决定 | 在新方案中的落点 |
| --- | --- | --- |
| 每轮先读索引、再读少量相关正文 | **复用** | `search_llm_wiki` 作为每轮知识问答的首个必经调用，返回有限候选页面。 |
| 本轮证据状态机；历史消息、模型记忆不能充当资料依据 | **复用** | `regional-llm-wiki-qa` Skill 要求结论只能基于本轮工具返回的页面或证据。 |
| 查不到直接说明；资料不可用即停止，不以外部来源补答 | **复用** | 专用工具统一返回 `not_found` / `release_unavailable` / `integrity_failed`，Skill 定义固定、保守的答复。 |
| 冲突并列、缺口明确、来源必须是实际读取内容 | **复用** | 页面与证据工具返回的 `page_id`、`evidence_id`、定位单元成为答案唯一可引用来源。 |
| 精确参数、条款、版本需回到证据正文核验 | **扩展复用** | 默认先读 LLM Wiki；出现精确核验意图时按页面声明调用 `read_llm_wiki_evidence`。 |
| TFS 原件只作为人工查看入口 | **复用并收紧** | 只返回 manifest 中已校验的 `tfs_url`；不向 Agent 提供 TFS 访问工具。 |
| `/mnt/knowledge` 固定路径和通用文件工具 | **不复用** | 保留给现有生产知识库；新 Agent 不获得 `read_file`、`grep`、`glob` 或 `bash`。 |
| Gateway + sandbox 双层通用挂载 | **不复用** | 新资料仅挂到 Gateway 专属只读发布根，不加入 `sandbox.mounts`。 |
| `skills` 发现白名单 | **复用但不单独依赖** | 新 Agent 仍使用 `skills: [regional-llm-wiki-qa]`；新增 `mandatory_skills` 保证其在首个模型调用前生效。 |
| Skill `allowed-tools` | **复用为第二道控制** | 与 Agent 的 `tool_names` 保持同一集合，但不替代装配阶段的硬白名单。 |

这样既能保持既有知识问答的证据严谨性，也不会把原来“全局挂载 + 通用文件工具”的权限范围带入新的专属 Agent。

## 4. 目标架构

```text
                 ┌──────────────────────────────────────────────┐
                 │ DeerFlow Gateway                              │
                 │                                              │
用户 ────────►  │ regional-llm-wiki Agent                       │
                 │  ├─ mandatory Skill                          │
                 │  └─ 精确工具白名单                           │
                 │       ├─ search_llm_wiki                     │
                 │       ├─ read_llm_wiki_page                  │
                 │       ├─ read_llm_wiki_evidence              │
                 │       └─ get_llm_wiki_release_state          │
                 └──────────────┬───────────────────────────────┘
                                │ 仅 Gateway 内的只读 bind mount
                                ▼
             /mnt/regional-llm-wiki-runtime/current/
                    ├─ agent-access-manifest.json
                    ├─ llm-wiki/
                    └─ evidence/

现有 Agent ───► 通用 sandbox（不含上述挂载） ───► /mnt/knowledge（保持原样）
```

### 4.1 双重隔离

| 层级 | 实现 | 防护内容 |
| --- | --- | --- |
| 能力装配 | 新增 `tool_names` 严格白名单 | Agent 看不到、也不能经 `tool_search` 或 MCP 调用未列工具。 |
| 资源执行 | 四个专用工具只接受受控 ID | 无路径、通配符、命令或 URL 入参；禁止读取任意文件。 |
| 容器挂载 | 仅 Gateway 有专属发布根目录 bind mount；不加入 `sandbox.mounts` | 通用 `read_file`/sandbox 无法看到 LLM Wiki。 |
| Skill 策略 | 必需 Skill 声明同一工具集合 | 将问答工作流和运行时工具策略与装配白名单保持一致。 |

任何一层失效都不得使该 Agent 获得通用文件或命令访问；测试必须覆盖这项否定性保证。

## 5. 发布快照消费契约

### 5.1 为什么不能把 `current` 单目录直接暴露给模型

维护任务会原子切换发布快照。如果工具在一次问答中先读取旧索引、再读取新页面，可能出现引用断裂。因此 Gateway 读取的是保留版本的发布根，首个检索结果携带固定 `release_id`；后续页面和证据读取必须使用同一 `release_id`。

### 5.2 目录契约

维护层在已通过校验并发布时生成如下只读结构；`current` 只指向已完整发布的版本：

```text
<runtime>/published/
├─ current -> releases/<release_id>
└─ releases/
   └─ <release_id>/
      ├─ agent-access-manifest.json
      ├─ llm-wiki/
      │  ├─ index.md
      │  ├─ global/
      │  └─ 00-产品设计中心/ ... 04-个性化方案/
      └─ evidence/
         └─ wiki/ ...
```

- `release_id` 必须由 `source_commit`、发布时间和发布内容摘要确定，且不使用用户输入。
- 发布目录在切换前完成所有写入和校验；`current` 仅在成功后原子切换。
- 至少保留当前及前一版，保留时间覆盖最长允许问答运行时间；回收由维护层在确认无活跃引用后处理。
- DeerFlow 只读挂载 `<runtime>/published`，不会挂载 `llm-wiki-work`、诊断、缓存、密钥或源仓库。

### 5.3 `agent-access-manifest.json`

该文件由发布校验程序生成，**不是模型自由输出**，并与 `release.json` 一起校验。最小字段如下：

```json
{
  "schema_version": 1,
  "release_id": "...",
  "source_commit": "...",
  "published_at": "...",
  "pages": [
    {
      "page_id": "concept:...",
      "path": "llm-wiki/01-产品策划中心/concepts/....md",
      "sha256": "...",
      "type": "concept",
      "domain": "01-产品策划中心",
      "evidence_ids": ["evidence:..."]
    }
  ],
  "evidence": [
    {
      "evidence_id": "evidence:...",
      "path": "evidence/wiki/01-产品策划中心/....md",
      "sha256": "...",
      "allowed_locations": ["S003", "L012-L018", "T002:R004-R006"],
      "tfs_url": "https://..."
    }
  ]
}
```

校验规则：页面、证据路径均为相对 POSIX 路径；不得含空路径、绝对路径、`..`、符号链接逃逸或不在当前 release 根内的路径；每个 `evidence_id` 必须被至少一页引用；哈希必须匹配实际文件。没有通过清单校验的发布版本不能被专用工具读取。

## 6. 专用工具接口

所有工具执行于 Gateway 进程，使用 Python 文件 API，不执行 shell、不接受任意路径、不联网、不写文件。耗时文件 I/O 必须在 `asyncio.to_thread` 中运行，避免阻塞 Gateway 事件循环。

| 工具 | 允许输入 | 返回 | 拒绝条件 |
| --- | --- | --- | --- |
| `search_llm_wiki` | `query`、可选领域、`limit<=5` | 固定 `release_id`、候选 `page_id`、标题、类型、简短命中片段 | 空/超长 query、未知领域、无有效当前 release。 |
| `read_llm_wiki_page` | `release_id`、`page_id` | 已验证页面正文、元数据、关联 `evidence_id` 与可用定位单元 | 非当前或保留 release、未知 page ID、哈希不符、页面不在 manifest。 |
| `read_llm_wiki_evidence` | `release_id`、`evidence_id`、可选已声明定位单元 | 对应证据片段、行号/表格范围、TFS 原件链接 | 未声明的证据、未声明的定位单元、哈希不符、越界请求。 |
| `get_llm_wiki_release_state` | 无 | 发布版本、源 commit、发布时间、降级/隔离统计 | 状态文件或清单校验失败。 |

工具只返回用户问题所需的有限内容，并对 query、页数、行数和输出字符数设上限。错误统一分为：`release_unavailable`、`not_found`、`integrity_failed`、`invalid_request`；不得把宿主机路径、堆栈、密钥或原始模型输出返回给模型。

### TFS 边界

`read_llm_wiki_evidence` 可以返回清单中已校验的 `tfs_url`，供最终答案展示给用户；不提供打开 URL、下载附件或访问 TFS 的工具。原件版式、图片、扫描件与附件仍由用户自行通过该链接查看。

## 7. Agent 与 Skill 设计

### 7.1 Agent 配置

新增配置目录 `agents/regional-llm-wiki/`，由运维人员以文件方式管理。安全字段不通过普通 Agent 编辑界面暴露，避免聊天或 UI 编辑扩大权限。

```yaml
name: regional-llm-wiki
description: 基于已发布区域 LLM Wiki 的只读、可追溯知识问答
model: <沿用已验证的 DeerFlow 模型名>
tool_groups:
  - regional-llm-wiki
tool_names:
  - search_llm_wiki
  - read_llm_wiki_page
  - read_llm_wiki_evidence
  - get_llm_wiki_release_state
  - ask_clarification
skills:
  - regional-llm-wiki-qa
mandatory_skills:
  - regional-llm-wiki-qa
```

新增字段的语义：

- `tool_names: null`：旧 Agent 的兼容模式，不改变现有装配结果。
- 非空 `tool_names`：在普通工具、内建工具、MCP、延迟工具和 Agent 管理工具全部汇总后，按名称过滤，再交给模型与 `tool_search`；未出现的工具不可调用。
- `mandatory_skills`：仅限此 Agent `skills` 白名单中的已启用 public Skill。完整 Skill 内容由服务器安全读取并在首个模型调用前注入；不依赖用户输入 `/skill-name` 或通用 `read_file`。
- 普通 Web/HTTP API 不提供对 `tool_names`、`mandatory_skills` 的修改入口。若未来要提供 UI，只能由管理员接口管理，并要重新进行权限审查。

`SOUL.md` 只描述角色、答复语气和“先结论后来源”的呈现要求，不能承担任何安全控制。

### 7.2 Skill

新增 committed public Skill：`skills/public/regional-llm-wiki-qa/SKILL.md`。

Skill 的 `allowed-tools` 与 Agent 的 `tool_names` 相同，不含 `read_file`、Bash、Web 或写工具。核心规则：

1. 每个知识问题先调用 `search_llm_wiki`；不可直接编造 `page_id`、`evidence_id` 或 release。
2. 默认读取少量 LLM Wiki 页面，先给综合结论、适用范围、版本/有效期与冲突提示。
3. 用户要求条款、原句、数值、表格、版本或核验时，调用 `read_llm_wiki_evidence`，仅引用工具返回的定位单元。
4. 每个事实必须来自本轮实际读取的页面；精确事实必须同时来自本轮实际读取的证据片段。
5. 查不到、发布不可用、页面隔离或证据不支持时明确说明，不以模型记忆、历史回答、旧知识库或 Web 补全。
6. 需要查看原件时提供实际返回的 TFS 链接，不自动读取原件。
7. 不生成、修改、归档或反馈任何知识库页面，不访问聊天历史作知识回写。

### 7.3 双重工具策略

Agent 装配白名单是强制边界；Skill 的 `allowed-tools` 是运行时第二道边界和行为契约。即使模型跳过 Skill 工作流，前者仍禁止越权；即使后续误把额外工具加入工具组，后者仍会在必需 Skill 激活后收紧工具集。

## 8. DeerFlow 代码改造点

| 区域 | 改造 | 兼容性要求 |
| --- | --- | --- |
| `config/agents_config.py` | 为 `AgentConfig` 增加 `tool_names`、`mandatory_skills`，校验名称及其与 `skills` 的关系。 | 缺省为 `null`，旧 Agent 行为不变。 |
| `agents/lead_agent/agent.py` | 所有工具汇总后、任何模型绑定或延迟工具暴露前执行 `tool_names` 过滤；安全加载必需 Skill 内容。 | 未配置字段时不执行过滤。 |
| Skill middleware | 支持安全注入 `mandatory_skills`，并以同一 allowlist 作为工具策略输入。 | 现有 slash Skill 语义不变。 |
| `tools/builtins/` | 新增 LLM Wiki release resolver、manifest 校验器和四个 read-only tools。 | 不影响现有 file/sandbox 工具。 |
| `config.yaml` | 注册四个工具到新组 `regional-llm-wiki`，配置 Gateway 内发布根。 | 不修改既有工具组。 |
| `docker-compose` | 仅给 Gateway 添加 `<runtime>/published:/mnt/regional-llm-wiki-runtime:ro`。 | 不给通用 sandbox 添加对应 mount。 |
| Agent/Skill 文件 | 新增，不修改 `product-kb-qa`。 | 现有线程继续使用原 Agent 与 Skill。 |

## 9. 部署顺序与回退

### 9.0 开发工作区隔离

审核通过后的开发不得直接在当前 DeerFlow 检出、现有服务器部署目录或 LLM Wiki 维护目录中进行。实施开始时：

1. 从审核时确认的 DeerFlow Git 基线创建一个独立 Git worktree，例如 `deer-flow-llm-wiki-agent/`。
2. 代码、单元测试、合成 release fixture、临时配置和本地容器测试产物均只写入该 worktree 或系统临时目录；不得写入现有 `deer-flow/` 工作目录的未提交用户文件。
3. worktree 使用独立分支；只在通过本地验收后提交该分支。合并/部署仍需单独确认。
4. 服务器验证使用隔离影子目录和独立容器/配置副本，不直接修改生产 Gateway、现有 Agent 或挂载。

该隔离只约束开发与验证的写入位置，不改变第 4 节定义的运行时安全边界。

### 9.1 前置门禁

1. LLM Wiki 维护层已产生通过校验的 `agent-access-manifest.json` 和至少一份 `current` 发布快照。
2. 新 API Key 已按生产门禁轮换；DeerFlow 不读取该 Key。
3. 以 DeerFlow 运行用户验证 Gateway 内可读发布根、不可写；通用 sandbox 内该根不存在。
4. 已确认该 Agent 的模型名为 DeerFlow 中已配置且可用的模型，不在 Agent 文件写入模型密钥。

### 9.2 实施与发布

1. 在本地完成工具、Agent 配置解析、Skill 与测试。
2. 在隔离环境用合成 release fixture 进行端到端测试。
3. 部署代码、Skill、Agent 配置与 Gateway 单一只读 bind mount；不改现有 `/mnt/knowledge`。
4. 重建 Gateway 后创建新会话，仅测试新 Agent；原 Agent 做回归冒烟。
5. 在小范围 canary 中运行问题集，连续稳定后再开放使用。

### 9.3 回退

- 新 Agent 或工具异常：从 Agent 列表下线/禁用其专用工具，重建 Gateway；现有 Agent 不受影响。
- 当前 LLM Wiki release 校验失败：专用工具返回 `release_unavailable`，不读取前一版本以外的未验证内容；维护层继续保留 last-good。
- 不回退或覆盖现有 `product-kb-qa`、`/mnt/knowledge`、DeerFlow 线程或原知识库同步任务。

## 10. 验收测试

### 10.1 安全与隔离（必须 100% 通过）

- 新 Agent 的模型工具 schema 仅包含五个白名单工具；MCP、Web、Bash、`read_file`、`grep`、写工具、`task`、`update_agent` 不出现。
- `tool_search` 无法检索或提升任何未授权工具。
- 工具拒绝绝对路径、`..`、URL、通配符、未知 ID、旧 release ID、未经页面声明的 evidence ID 与超范围定位单元。
- 清单哈希或符号链接校验失败时不返回文件内容。
- 普通 Agent 的 sandbox 无法列出或读取 `/mnt/regional-llm-wiki-runtime`；现有 Agent 回归仍可读取原 `/mnt/knowledge`。
- 工具与日志不输出主机真实路径、API Key、请求头、模型原始输出或工作目录内容。

### 10.2 功能与证据

- 代表性问题可从索引命中领域、概念、实体和分析页面。
- 需要精确核验时，答案可读取并列出证据行号/表格范围；不需要核验时不无故读取证据。
- 证据失效、降级页、找不到内容、发布切换中均给出明确且保守的结果。
- 返回的 TFS 链接只来自 manifest，且工具从不访问该链接。
- 同一轮中 `release_id` 固定；发布切换后新轮才使用新 release。

### 10.3 回归与运维

- 现有 `product-kb-qa` 的测试与原 Agent 冒烟通过。
- 新增 Agent 配置字段为空时，旧自定义 Agent 工具集完全不变。
- Gateway 重启、LLM Wiki 发布切换、前一版保留和 release 不可用均有集成测试。
- 使用 110 题本地验收题库的对应知识问答子集，检查可导航性、证据支持、错误拒答与来源格式。

## 11. 审核清单

审核通过后，实施必须以以下结论为前提：

- [ ] 接受“Gateway 专属只读挂载 + 非 sandbox 挂载”的隔离边界。
- [ ] 接受新增 `tool_names` 与 `mandatory_skills`，并将其作为所有后续高隔离 Agent 的复用能力。
- [ ] 接受 Agent 消费 `agent-access-manifest.json`，而非让模型直接遍历发布目录。
- [ ] 接受新 Agent 初期仅提供问答与证据核验，不生成文档、不写入知识库、不调用 TFS。
- [ ] 确认试运行阶段使用独立 LLM Wiki 发布根和新 Agent，不替换现有 `/mnt/knowledge` 或旧 Agent。

审核通过后，按第 9 节顺序实施；任何需要放宽工具白名单、开放通用 sandbox 挂载或修改现有 Agent 的请求，都必须作为新的设计变更重新审核。
