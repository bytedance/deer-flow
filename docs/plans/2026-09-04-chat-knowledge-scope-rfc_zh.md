# RFC：自定义智能体对话的知识检索范围选择（最小版本）

**状态：** 草案，按最小实现推进迭代
**日期：** 2026-09-06
**前置能力：** RAGFlow 只读检索、混合 embedding 分组召回、Gateway 知识库管理代理与 `/workspace/knowledge`。实施时先核对现有能力，复用已有实现。
**RAGFlow 兼容性基线：** v0.27.0。

## 1. 本版决定

仅在自定义智能体对话输入框的模式选择器右侧增加“知识库”入口。用户可以选择全部允许知识库、指定知识库、库内指定文件，或关闭本轮知识检索。

**输入框选择只保存在当前页面的前端内存中，允许丢失。** 同一页面连续发送时沿用当前选择；刷新、重新打开、切换到另一对话或另一个智能体时恢复默认 `all`。不承诺跨设备或多标签页同步，不从历史消息恢复输入框选择。新对话首次发送后变为实际 thread ID 时，应保留同一次页面会话中的选择，不将这次路由替换误判成切换对话。

每次发送时，将当时的执行范围写入 `HumanMessage.additional_kwargs.knowledge_scope`。这份消息快照决定该轮范围，不随之后的输入框操作变化。服务端保留消息快照，但**不保存独立的输入框状态，不修改 thread metadata，也不新增业务数据表**。

模型仍只能调用：

```python
knowledge_search(query: str)
```

后端负责校验并强制范围。用户选择只能收窄运维 allowlist，模型不能改写范围。

## 2. 范围与延期项

本版保留：

- 由 `knowledge_base.scope_selection_enabled` 全局开关控制自定义智能体对话入口，默认关闭；普通对话 UI 和原有检索行为不变。
- `all`、`selected`、`disabled` 三种模式。
- 多知识库选择，以及每个已选库的全部文件或指定文件选择。
- 页面内沿用选择、发送时记录消息快照。
- 服务端校验、模型输入清洗、工具执行约束与子智能体传播。
- 历史回显：消息内保留有容量上限的知识库/文件名称快照，直接展示名称与数量，无需重新查询目录。

本版不做：

- thread metadata 中的 `knowledge_scope`、`knowledge_scope_revision`。
- 对话范围 GET/PUT、revision CAS、`knowledge_scope_write` 锁及默认值同步。
- 首次发送原子保存默认值、分支继承默认值、跨设备恢复。
- localStorage/sessionStorage 草稿持久化或从最后一条消息恢复选择。
- “全部减去若干库”的排除模式；需要部分库时切换到显式选择。
- 复杂历史详情面板、历史目录恢复与专用 resolve/tombstone API。
- 智能体永久配置、目录缓存服务、通用 RAG provider 抽象。
- 在选择弹窗中上传、解析或管理知识库和文件。

这些能力不作为本版上线前置条件。后续根据使用反馈独立迭代。

## 3. 最小交互

按钮放在自定义智能体对话的模式选择器右侧，显示“知识库 · 全部 / N库 / N库·M文件 / 关闭”。其中 M 只统计显式指定文件，不代表全部文件库的实际文件总数。

### 3.1 全局 UI 开关

在根目录 `config.yaml` 的 `knowledge_base` 下新增配置：

```yaml
knowledge_base:
  enabled: true
  scope_selection_enabled: false  # 是否开放对话输入框的知识库范围选择按钮；默认 false
```

`scope_selection_enabled` 是部署级 UI 开关，缺省为 `false`，由运维通过配置文件控制，不提供用户设置页或新的配置写入 API。

- `false`：隐藏选择按钮，不初始化 selector 状态、不加载选择目录，也不为新消息自动附加 scope；历史消息仍按已保存的 display 回显。
- `true`：在全局知识库能力与 RAGFlow 范围选择能力可用时，为自定义智能体对话开放按钮。
- 此开关只控制 UI 入口，不改变既有 `knowledge_search` 的装配和运维默认范围，不撤销已接纳运行或历史消息的 scope。后端对已提交 scope 的校验和强制约束始终有效；关闭按钮不能使重新生成或恢复执行扩大到默认范围。

Gateway 通过现有 `/api/features` 返回计算后的 `knowledge_base.scope_selection_enabled`，前端不直接读取 YAML。该有效值为 true 必须同时满足：`knowledge_base.enabled`、配置中的 `scope_selection_enabled` 均为 true，且实际生效的检索工具 entry 为 `deerflow.community.ragflow.tools:knowledge_search_tool`。不能仅凭同名 `knowledge_search` 判断；LightRAG、未知 provider 或未配置检索工具时返回 false。

前端仅在自定义智能体对话、非静态 demo 且 features 有效值为 true 时显示按钮。当前智能体未允许 `knowledge` 工具组时，按钮显示为禁用并附简短原因。配置读取和生效时机沿用现有配置系统，不为此开关增加独立热更新或推送机制。

### 3.2 选择弹窗

复用现有 Dialog 和列表组件，提供：

1. “全部允许知识库”“指定知识库”“关闭”三种模式。
2. 指定模式下勾选知识库；选中一个库时默认使用其全部可检索文件。
3. 按需展开某个库，切换到指定文件；指定文件必须至少选一个。
4. 点击“应用”只更新页面内选择；“取消”丢弃弹窗未应用的修改。

全部模式不提供文件过滤；需要文件过滤时切换到指定模式。全部是动态语义，包含后续新增且运维允许的可检索库，不能为实现全选而枚举全部 ID。

知识库和文件复用现有服务端搜索、分页能力，展开时才加载文件。显式选择跨分页保留；未解析、解析中、失败和零 chunk 文件不能勾选。目录加载失败时保留当前选择。若现有接口不能按运维 allowlist 返回安全目录，只补必要的只读列表接口，不增加状态写入接口。

弹窗用简短文案说明：“选择仅在当前页面保留，刷新后恢复全部允许知识库。” 同时保留部署共享知识库的提示。

运行中禁止应用变更，减少交互分支。键盘操作、焦点返回、窄屏滚动和中英文文案沿用现有组件规范，不单独建设新的 UI 框架。

## 4. 消息数据契约

消息中的 `knowledge_scope` 保存执行字段与可选的 `display` 名称快照，不含 revision。`display` 仅用于回显，不参与执行范围、权限或文件归属判断：

```json
{
  "version": 1,
  "mode": "selected",
  "dataset_ids": ["dataset-a", "dataset-b"],
  "document_filters": [
    {"dataset_id": "dataset-b", "document_ids": ["doc-1", "doc-2"]}
  ],
  "display": {
    "datasets": [
      {"id": "dataset-a", "name": "农业技术库"},
      {
        "id": "dataset-b",
        "name": "水稻种植库",
        "documents": [
          {"id": "doc-1", "name": "水稻栽培指南.pdf"},
          {"id": "doc-2", "name": "病虫害防治手册.pdf"}
        ]
      }
    ]
  }
}
```

上述例子表示：查询 A 的全部可检索文件，以及 B 中的 doc-1、doc-2。

```json
{"version": 1, "mode": "all"}
```

```json
{"version": 1, "mode": "disabled"}
```

共享 canonicalizer 必须保证：

- 仅接受已知 version 和字段；未知版本或字段拒绝。
- `all`、`disabled` 的 dataset 和 document filter 字段必须缺省或为空。
- `selected` 的 `dataset_ids` 必须非空。
- 每个 dataset 最多一个 document filter，且必须属于 `dataset_ids`。
- 缺少 document filter 表示该库全部文件；显式 `document_ids` 必须非空，空数组不能解释为全部文件。
- ID 去除首尾空白、保序去重；单个 ID 非空且不超过 256 个 Unicode code point。
- 最多 100 个显式 dataset、总计 1000 个显式 document ID；规范 JSON 不超过 64 KiB。
- 超限或结构非法时拒绝，不能静默截断执行范围。

`display` 的最小契约：

- 前端在选择时保留选中项的 ID 与名称，跨分页和列表刷新不丢失；发送时一并复制到消息快照，无需为发送重新查询目录。
- 最多保存 20 个 dataset 名称、总计 50 个 document 名称；每个名称最多 256 个 Unicode code point，包含 display 的整个规范消息 scope 仍不超过 64 KiB。
- display 中的 dataset ID 必须属于执行选择，document ID 必须属于对应库的显式 document filter；同层 ID 不重复。Gateway 校验结构、关联与容量，不为验证名称而访问 RAGFlow。
- 名称是前端提交的发送时展示快照，不作为服务端认证的目录事实。超出展示容量时，前端省略部分名称；单个名称超长时直接省略该名称条目，不保存被截短的名称。若加入 display 会使总 payload 超限，继续减少展示条目。执行 ID 不得截断；仅执行字段就超限时拒绝发送。Gateway 对不合规 payload 返回错误，不静默裁剪。
- 历史 UI 使用快照名称作为纯文本，不解析 HTML/Markdown。库或文件之后改名、删除，不改写历史名称，也不发目录或 resolve 请求。
- 数量和“全部文件/指定文件”语义始终从执行字段计算，不根据 display 是否列出文件推断。前端按执行 ID 与 display 条目的 ID 对应关系判断名称是否齐全；缺失部分用数量摘要补充，旧消息没有 display 时回退到数量摘要，无需额外保存裁剪标记。
- `all` / `disabled` 不保存 display，按 mode 显示本地化摘要，不枚举目录或保存本地化标签。动态 all 不保证记录当时完整目录或文档内容版本。

这样只增加消息快照中的展示字段，无需恢复服务端输入框状态或建设历史目录查询接口。

## 5. 前后端数据流

```text
页面内选择
  → 发送时创建 HumanMessage scope 快照
  → Gateway 校验并接纳
  → KnowledgeScopeMiddleware 投影为 runtime scope
  → lead / tool / subagent 使用同一范围
  → RAGFlow 按范围检索
```

### 5.1 前端

`AgentChatPage` 持有选择状态，并显式将能力传给共享 `InputBox`。普通 `ChatPage` 不传该能力，不加载目录、不创建 scope state、不提交 scope。

普通发送与编辑后重新生成复用同一个 snapshot builder，一次生成执行字段和有容量上限的 display。快照应复制并规范化当前状态，不能继续引用可变的组件数组。optimistic 与持久化消息使用同一份名称快照；发送后修改输入框选择不会修改旧消息。

新线程和既有线程使用同一套消息提交方式，不需要先写 metadata 或等待额外保存请求。不同标签页拥有独立输入框选择，允许各自提交不同 scope，沿用现有 run 并发规则。

前端模块按现有目录组织，只提取实际需要的 selector、类型和 snapshot helper；不预先增加 storage、revision、resolve 或同步层。

### 5.2 Gateway

在现有消息标准化、权限检查和 run admission 路径中增加 scope 校验：

- 只允许本次正常提交的用户 HumanMessage 携带 scope；拒绝 AI/System/Tool message 或异常位置携带 scope，以及一次提交多个含 scope 的新增 HumanMessage。
- 确认用户有权访问线程/智能体、线程绑定匹配、自定义智能体允许 knowledge 工具组，且生效 provider 为 RAGFlow。
- 普通对话伪造 scope 时在持久化和执行前拒绝；未提交 scope 则沿用现有行为。
- 清除客户端从自由格式 `config.context` / `configurable` 注入的同名 runtime 字段，不能把它们作为执行来源。
- 使用 harness 的共享 canonicalizer 校验结构和容量；只有规范化后的消息进入持久化和 worker。
- admission 不请求 RAGFlow；当前可见性和文件归属在目录读取或工具调用时校验。

不读取、比较或更新 thread scope，不引入 revision 校验或额外线程操作锁。保持现有 durable run admission 与 worker attachment 的生命周期约束。

### 5.3 重试、澄清与分支

| 入口 | 范围来源 |
| --- | --- |
| 普通发送 | 提交时输入框选择 |
| 编辑后重新生成 | 提交编辑时输入框选择，创建新快照 |
| 普通重新生成 | 服务端原始 HumanMessage 快照，忽略客户端伪造的替换 scope |
| 澄清回复 / resume | 沿用该执行链已接纳的 scope，不从重置后的输入框重新取值 |
| 分支对话 | 历史消息保留各自快照；新页面输入框回到 all |
| 旧消息或未接入的 IM / TUI / SDK / 定时任务 | 运维默认范围，保持兼容 |

重放和恢复必须通过现有运行身份、源消息或 checkpoint 找到对应快照，不能扫描历史随意取最后一条 HumanMessage。恢复已选择范围的执行链时，scope 丢失或非法必须报错，不能伪装成旧调用方而回退到全部。

## 6. 运行时强制边界

`KnowledgeScopeMiddleware` 只负责：

1. 从经接纳的当前消息或合法恢复路径读取 scope，仅将执行字段投影到 runtime context，去掉 display；明确区分 legacy 缺失与非法/丢失的 scope。
2. 每次模型调用前，复制并清除所有历史消息中的 `additional_kwargs.knowledge_scope`，不修改持久化消息。
3. disabled 时从模型可见工具中移除 `knowledge_search`；与其他工具过滤取交集，不重新加入已禁用工具。

middleware 不读取 thread store、不访问 RAGFlow，保持 `app → harness` 依赖方向。同步与异步模型调用执行相同清洗规则。

工具通过注入 runtime 读取执行范围，模型可见 schema 仍只有 `query`。工具本身也检查 disabled 和范围合法性，不能仅依赖模型侧隐藏。

native subagent 和 durable batch subagent 必须继承父级同一份 execution scope，不复制 display，恢复时也不能丢失。子智能体直接使用已验证的 runtime scope，不要求伪造新的用户消息快照；任务 prompt 或模型工具参数不能扩大范围。这部分与后端范围约束一起交付。

dataset/document ID 和 display 名称快照可以出现在受鉴权保护的消息持久化与历史 API 中，但 scope（包括 display）必须在模型调用前整体移除，不得作为模型请求或工具参数传入。检索结果沿用现有引用名称规则，不输出 UUID；display 不参与检索结果生成。若 tracing/callback 在 middleware 之前捕获输入，沿用或补充同一 scope 清洗。API key 始终只在服务端；日志与错误沿用已有脱敏规则。

## 7. 检索实现

复用已有 RAGFlow client、运维 allowlist、embedding 分组和结果合并，只增加 scope 与文件过滤所需的逻辑。

- `all`：使用运维允许的当前可检索知识库。
- `selected`：限定为显式知识库，并受运维 allowlist 约束。
- `disabled`：不检索。
- 显式选中的库失权、被删除或超出 allowlist，或文件不再可检索/不属于指定库时，整次检索失败；不得丢弃失效项后继续，更不能退回全部。
- 动态 all 下跳过空库等行为沿用现有实现。

调用 RAGFlow 时，`dataset_ids` 必须非空；`document_ids=None` 表示全部文件，非空数组表示指定文件，空数组在发请求前拒绝。

每种 embedding 下，全部文件的库合为一组，指定文件的库合为另一组。例如 A 全文件、B 指定文件，即使 embedding 相同也必须分两次请求，避免文档过滤语义串用。

并行上限沿用 4；单组保留原排序，多组沿用现有 rank 合并，最后统一去重并应用全局 `page_size` 与字符上限。任一应检索分组失败时整体失败，不将部分结果伪装成完整结果。

最小新增错误类别为：范围非法/超限、智能体或工具不支持、库/文件选择已失效；复用现有稳定错误格式和本地化机制。不增加 revision 冲突或 scope 保存错误。

## 8. 实施顺序与验证

本 RFC 只规定目标行为，具体文件触点先核对当前代码和模块 AGENTS，避免重复实现已有能力。后端遵循仓库 TDD 要求。

### 第一步：后端完整执行链

同一可审查变更完成 contract、admission、middleware、工具文件过滤与 native/durable subagent 传播。无须先实现任何对话默认值 API。

必要测试：

- 三种模式、未知字段/版本、空数组、ID 与 payload 上限；display 的 ID 关联、重复项、名称/数量/总字节上限。
- 普通对话/错误 provider 拒绝 scope，客户端 runtime 伪造不能成为执行来源。
- 超出 allowlist、错误文件归属、失效选择均不扩大范围。
- 模型实际输入和外部 trace 不含 scope 或 display；runtime 与 subagent payload 仅有执行字段，工具 schema 仍只有 query。
- disabled 的模型过滤和执行侧拒绝同时成立。
- 混合 embedding、全文件/指定文件分组和结果合并。
- lead、native、durable、恢复与重新生成使用正确范围；已有无 scope 调用行为不变。

### 第二步：最小前端入口

复用或补齐必要目录列表，完成全局配置与 features 映射、selector、页面内 state、带 display 的发送快照和简单历史名称/数量回显。配置 schema 与 `config.example.yaml` 同步新增默认关闭的 `knowledge_base.scope_selection_enabled`，并更新 README 和涉及架构变化的 AGENTS。

必要测试与人工验收：

- 配置缺省/false 时隐藏入口，不请求选择目录或自动附加 scope；配置为 true 且 provider 可用时，仅自定义智能体对话显示入口。覆盖总开关关闭、LightRAG/未知 provider、agent 工具组缺失和静态 demo。
- 关闭 UI 开关后，历史 display 仍回显；重新生成/恢复仍使用原 scope，普通无 scope 调用行为不变。普通对话无目录请求或 scope 提交。
- 全部、指定库、指定文件、关闭均能通过 UI 产生正确检索范围。
- 同页面连续发送沿用选择；首次发送创建线程的路由变化不丢选择。
- 刷新或切换对话恢复 all，不调用任何 scope 保存 API，不写 thread metadata。
- 改变选择或目录改名/删除不改变旧消息名称快照；历史回显无需目录请求。覆盖 optimistic 一致性、名称纯文本、display 容量缩减及缺失时的数量回退。
- 普通重新生成用原快照；编辑后重新生成用当前选择；澄清恢复沿用原执行范围。
- 分页选择、加载错误、键盘操作和窄屏可用。

完成上述两步即可交付本版，不以跨设备同步、复杂历史展示或额外可观测性建设阻塞。现有 feature/provider 开关保持生效，关闭功能的部署行为不变。

## 9. 参考

- RAGFlow v0.27.0 SDK `retrieve()`：https://github.com/infiniflow/ragflow/blob/v0.27.0/sdk/python/ragflow_sdk/ragflow.py#L190-L225
- RAGFlow retrieval 校验：https://github.com/infiniflow/ragflow/blob/v0.27.0/api/apps/restful_apis/chunk_api.py#L329-L374
- 当前代码入口：`backend/packages/harness/deerflow/community/ragflow/`、`backend/packages/harness/deerflow/agents/middlewares/`、`backend/packages/harness/deerflow/subagents/`、`backend/app/gateway/routers/thread_runs.py`、`frontend/src/core/threads/`、`frontend/src/core/knowledge/`、`frontend/src/components/workspace/input-box.tsx`。
