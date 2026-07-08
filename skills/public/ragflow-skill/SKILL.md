---
name: ragflow-retrieval
version: 0.2.0
description: |
  Query RAGFlow 0.26.1 knowledge bases with vector retrieval and metadata filtering.
  Auto-routes questions to the correct KB by intent (e.g. 信贷 vs 制度) without user
  specifying dataset_id. Supports POST /api/v1/retrieval (metadata_condition) and
  POST /api/v1/datasets/search (meta_data_filter).

  Triggers: "查知识库 / 制度怎么规定 / 贷款利率 / 检索规章 / RAGFlow 检索 / 带元数据过滤".

  Do NOT use for: uploading or parsing documents, building datasets, chat completions,
  agent canvas, or non-RAGFlow vector stores.
---

# ragflow-retrieval Skill

调用 RAGFlow 0.26.1 的**检索**与**元数据过滤** API，从知识库召回 chunks 并输出 JSON。

## 触发匹配规则（Agent 加载后必读）

**Step 1 — 匹配判断**：用户消息含以下任一条件时加载本 Skill：

- 动词 + RAGFlow / 知识库：`检索 / 搜索 / 召回 / 查知识库 / retrieve / search`
- 明确提到元数据过滤：`metadata filter / 元数据过滤 / 按 author 过滤 / 按部门筛选`
- 业务问答且应由信贷/制度知识库回答（**用户无需指定 dataset_id**）

**反例（不要触发）**：

- 上传 PDF、解析文档、创建 dataset → RAGFlow UI 或 ingest 流程
- OpenAI chat / agent 对话 → 其他 skill
- 非 RAGFlow 的向量库（Milvus/Qdrant 直连）→ 不用本 skill

**Step 2 — 选择 API 路径**：

| 场景 | CLI 子命令 | 过滤字段 | 过滤模式 |
|------|-----------|---------|---------|
| SDK 集成、外部脚本、明确的手动条件 | `retrieve` | `metadata_condition` | 仅 manual |
| 需要 LLM 自动推断过滤条件 | `search` | `meta_data_filter` | auto |
| 限定部分 metadata 字段让 LLM 推断 | `search` | `meta_data_filter` | semi_auto |
| 与 RAGFlow UI「检索测试」一致的手动过滤 | `search` | `meta_data_filter` | manual |

详细字段格式见 [references/metadata_filter.md](references/metadata_filter.md)。

## 沙箱路径

| 类型 | 路径 |
|---|---|
| 意图路由配置 | `/mnt/skills/public/ragflow-retrieval/config/routing.json` |
| 意图识别提示 | `/mnt/skills/public/ragflow-retrieval/prompts/intent_routing.md` |
| 元数据过滤自动加载 | `/mnt/skills/public/ragflow-retrieval/prompts/metadata_filter_autoload.md` |
| intent 绑定过滤文件 | `/mnt/skills/public/ragflow-retrieval/config/filters/{intent}.*.json` |
| 路由结果 | `/mnt/user-data/outputs/route.json` |
| 检索输出 | `/mnt/user-data/outputs/query.retrieval.json` |
| 溯源 Markdown | `/mnt/user-data/outputs/query.retrieval.citations.md` |
| 溯源 JSON | `/mnt/user-data/outputs/query.retrieval.citations.json` |
| 回答+溯源提示 | `/mnt/skills/public/ragflow-retrieval/prompts/answer_with_citations.md` |
| 过滤文件目录（运维） | `config/filters/`（信贷/制度各一对 json） |
| 兜底 example | `example/metadata_condition.author.json`, `example/meta_data_filter.manual.json` |
| 技能脚本 | `/mnt/skills/public/ragflow-retrieval/scripts/{route_intent.py,ragflow_client.py,routing_utils.py}` |
| 参考文档 | `/mnt/skills/public/ragflow-retrieval/references/metadata_filter.md` |
| Mock 样例 | `/mnt/skills/public/ragflow-retrieval/example/mock_retrieval/chunks.json` |
| RAGFlow 配置 | skill 目录 `.env`（`RAGFLOW_BASE_URL`, `RAGFLOW_API_KEY`，见 `.env.example`）；脚本启动时自动加载 |

## 意图路由（默认行为 — 用户不指定知识库）

> **用户不会在问题里写 dataset_id。** 优先用 **一键 query**（见下），避免多轮 Agent + 多次 bash。

### 运维一次性配置

编辑 `config/routing.json`：

**1. RAGFlow 连接 — 复制并编辑 skill 目录 `.env`**

```bash
cp /mnt/skills/public/ragflow-retrieval/.env.example \
   /mnt/skills/public/ragflow-retrieval/.env
```

```env
RAGFLOW_BASE_URL=http://your-ragflow-host:9380
RAGFLOW_API_KEY=ragflow-xxxxxxxx
```

`ragflow_client.py` / `route_intent.py` 启动时会自动加载该文件，**无需**写入 `routing.json`。

**2. 各 intent 填入真实 `dataset_id`**

```json
{
  "intent": "信贷",
  "dataset_id": "b2a62730759d11ef987d0242ac120004",
  "dataset_name": "信贷"
}
```

| intent | 知识库 | 部门过滤 | 典型问题 |
|--------|--------|----------|----------|
| `信贷` | 信贷知识库 | ✅ top 3 | 贷款、授信、利率、还款、抵押、征信 |
| `制度` | 制度知识库 | ✅ top 3 | 规章、办法、内控、审批流程、人事制度 |

两个 intent 均在 `routing.json` 中设置 `department_filter_enabled: true`；各自维护独立的 `departments` 列表与 `keywords`。

### 快速路径（默认 — 一条命令完成路由 + 检索）

**不要**先读 `intent_routing.md` / `metadata_filter_autoload.md` 再分步执行。直接运行：

```bash
python /mnt/skills/public/ragflow-retrieval/scripts/route_intent.py query \
  --question "{用户原问题}" \
  --quiet \
  --out /mnt/user-data/outputs/query.summary.json
```

一条命令内完成：**关键词意图识别 → resolve（含部门 top_k）→ RAGFlow 检索 → 溯源文件**。

输出文件（与 `--out` 同目录）：

| 文件 | 用途 |
|------|------|
| `query.summary.json` | 紧凑摘要 + `citations`（Agent 读这个即可） |
| `route.json` | 路由结果 |
| `query.retrieval.json` | 完整检索 JSON |
| `query.retrieval.citations.md` | 可读溯源 |

Agent 后续只需 **一轮**：读 `query.summary.json` 的 `citations`（或 `.citations.md`），按 `prompts/answer_with_citations.md` 生成回答。

若 `dataset_id` 未配置，加 `--resolve-names`（会慢一次；运维应填好 `dataset_id` 后去掉）。

意图无法自动区分时（`ambiguous_intent`），再读 `prompts/intent_routing.md` 请用户澄清或手动 `--intent`。

### 分步路径（仅 debug / 需手动指定 intent 时）

#### Step 0 — 意图识别（agent-turn，query 失败时用）

必读：
1. `prompts/intent_routing.md`
2. `prompts/metadata_filter_autoload.md`

判断用户问题属于 `信贷` / `制度` / `ambiguous`；对启用部门过滤的库，再识别 **top_k 个部门**（默认 3 个）。**不要**让用户选 dataset_id、部门或过滤文件路径。

#### Step 1 — resolve（库 + 部门 + metadata 过滤一次写入 route.json）

**推荐 — Agent 指定多个部门**：

```bash
python /mnt/skills/public/ragflow-retrieval/scripts/route_intent.py resolve \
  --intent "{信贷|制度}" \
  --question "{用户原问题}" \
  --departments "零售,对公,风控" \
  --out /mnt/user-data/outputs/route.json
```

**或 — 自动 keyword top_k 部门**（Agent 未把握时）：

```bash
python /mnt/skills/public/ragflow-retrieval/scripts/route_intent.py resolve \
  --intent "{信贷|制度}" \
  --question "{用户原问题}" \
  --department-top-k 3 \
  --out /mnt/user-data/outputs/route.json
```

若 `routing.json` 里 `dataset_id` 为空，加 `--resolve-names`。

- `route.json` → `dataset_ids[0]`：知识库
- `route.json` → `filters.department_selection`：部门选择结果
- `route.json` → `filters.active_filter`：运行时 metadata 过滤（`department in [...]`，字段名见 `department_metadata_field`）
- `信贷` / `制度` 均启用部门过滤；命中 top_k 部门后写入 `active_filter`
- 部门 keyword 全未命中：不做部门过滤，全库检索（`selection_method=none_matched`）

### Step 2 — 一键检索（bash，自动加载 metadata 过滤文件）

分步模式下用此命令；**正常场景请用上面的 `query` 快速路径**。

```bash
python /mnt/skills/public/ragflow-retrieval/scripts/ragflow_client.py run \
  --route /mnt/user-data/outputs/route.json \
  --question "{用户原问题}" \
  --quiet \
  --out /mnt/user-data/outputs/query.retrieval.json
```

`--quiet` 只向 stdout 输出摘要 + citations，完整 JSON 写入 `--out` 文件。

`run` 从 `route.json` 读取 `dataset_ids` + `filters.active_filter`（含多部门 metadata），**禁止**让用户提供过滤 JSON 路径。

运维/debug 列出全部过滤文件：

```bash
python /mnt/skills/public/ragflow-retrieval/scripts/route_intent.py list-filters \
  --out /mnt/user-data/outputs/filters.catalog.json
```

### Step 3 — 手动检索（仅 debug，生产不要用）

用 Step 1 得到的 `dataset_ids[0]` 和 `filters.active_filter_path` 执行 retrieve/search（见下文），**禁止**要求用户在问题里补充 dataset_id 或过滤文件路径。

### Rerank + 召回/返回条数（默认）

`config/routing.json` → `defaults`：

| 字段 | 默认值 | 含义 |
|------|--------|------|
| `rerank_enabled` | **true** | 是否启用 rerank |
| `rerank_id` | **`auto`** | 自动读取 RAGFlow 租户默认 rerank 模型；手动填写时需用**完整 ID**。若 `model_instance` 不是 `default`，格式为 `模型名@实例名@Provider`（如 `bge-rerank-large@bge-rerank-large@HugginFace`），两段式 `模型名@Provider` 在实例名非 default 时会失败 |
| `recall_top_k` | **64** | 初次向量召回候选池（传给 RAGFlow `top_k`） |
| `page_size` | **10** | rerank 后最终返回条数 |
| `max_citations` | **10** | 溯源展示条数 |
| `similarity_threshold` | **0.2** | 最低相似度过滤 |

流程：**64 候选 →（可选 rerank）→ 返回 top 10**。`rerank_enabled: false` 时直接向 RAGFlow 请求 top 10，不经 rerank。

`query` / `run` 从 `route.json` 自动读取，无需每次传参。临时覆盖：

```bash
python .../route_intent.py query \
  --question "..." \
  --recall-top-k 128 \
  --page-size 5 \
  --quiet \
  --out query.summary.json
```

（`--top-k` 是 `--recall-top-k` 的别名。）

临时换 rerank 模型：`--rerank-id "BAAI/bge-reranker-v2-m3@Builtin"`

查看租户实际 rerank 模型 ID（运维/debug）：

```bash
python /mnt/skills/public/ragflow-retrieval/scripts/ragflow_client.py list-models \
  --out /mnt/user-data/outputs/models.json
```

输出 `default_rerank_id` 即为应填入 `routing.json` 的值（`auto` 会自动使用它）。

## 前置条件

1. RAGFlow 0.26.1 服务可访问，且目标 dataset 已完成解析（chunk 已入库）。
2. 同一检索请求中的多个 dataset 必须使用**相同 embedding 模型**。
3. 使用 `auto` / `semi_auto` 过滤时，RAGFlow 租户需配置 chat 模型。
4. 连接 RAGFlow（任选其一）：
   - **skill 目录 `.env`**（推荐）：复制 `.env.example` → `.env`，填入 `RAGFLOW_BASE_URL`、`RAGFLOW_API_KEY`
   - 环境变量：同上两个 key
   - CLI：`--base-url` / `--api-key`
   - `base_url` 不含 `/api/v1` 后缀，例如 `http://localhost:9380`
   - `api_key` 从 RAGFlow UI → Settings → API Keys 获取

## 工作流

**默认（快）**：`route_intent.py query --quiet` → Agent 读 summary/citations → 回答。

**分步（debug）**：Step 0 意图识别 → Step 1 resolve → Step 2 run（均加 `--quiet`）。

> **禁止**向用户索要 metadata 过滤 JSON 路径；过滤文件由 `config/filters/{intent}.*.json` 自动绑定并在 `route.json` 输出。

### 辅助 — 列出 dataset（仅运维/debug）

```bash
python /mnt/skills/public/ragflow-retrieval/scripts/ragflow_client.py list-datasets \
  --out /mnt/user-data/outputs/datasets.json
```

### Step 2 — 选择过滤方式（可选）

**A. 手动 metadata_condition（retrieve 路径）**

适用于已知 metadata 字段和值。示例条件文件：

`/mnt/skills/public/ragflow-retrieval/example/metadata_condition.author.json`

**B. meta_data_filter（search 路径）**

- `manual`：与 UI 检索测试一致
- `auto`：LLM 从问题推断过滤条件
- `semi_auto`：限定 metadata 字段后 LLM 推断

示例 manual 文件：`/mnt/skills/public/ragflow-retrieval/example/meta_data_filter.manual.json`

### Step 3 — 执行检索

`--dataset-ids` **必须来自** `/mnt/user-data/outputs/route.json` 的 `dataset_ids`，不要用占位符。

**retrieve（SDK 兼容，metadata_condition）**：

```bash
python /mnt/skills/public/ragflow-retrieval/scripts/ragflow_client.py retrieve \
  --question "{用户原问题}" \
  --dataset-ids "{route.json 中的 dataset_ids[0]}" \
  --metadata-condition /mnt/user-data/uploads/filter.json \
  --top-k 10 \
  --similarity-threshold 0.2 \
  --out /mnt/user-data/outputs/query.retrieval.json
```

**search（UI 路径，meta_data_filter）**：

```bash
python /mnt/skills/public/ragflow-retrieval/scripts/ragflow_client.py search \
  --question "{用户原问题}" \
  --dataset-ids "{route.json 中的 dataset_ids[0]}" \
  --meta-data-filter /mnt/user-data/uploads/meta_filter.json \
  --top-k 10 \
  --out /mnt/user-data/outputs/query.search.json
```

**LLM 自动过滤（auto）**：

```bash
python /mnt/skills/public/ragflow-retrieval/scripts/ragflow_client.py search \
  --question "{用户原问题}" \
  --dataset-ids "{route.json 中的 dataset_ids[0]}" \
  --meta-data-filter /mnt/user-data/uploads/auto_filter.json \
  --out /mnt/user-data/outputs/query.auto.json
```

其中 `auto_filter.json` 内容为：`{"method": "auto"}`

### Mock 模式（无 RAGFlow 服务时）

```bash
python /mnt/skills/public/ragflow-retrieval/scripts/ragflow_client.py retrieve \
  --mock \
  --question "metadata filtering" \
  --dataset-ids "kb-demo-001" \
  --metadata-condition /mnt/skills/public/ragflow-retrieval/example/metadata_condition.author.json \
  --out /mnt/user-data/outputs/mock.retrieval.json
```

## 输出与后续处理（回答 + 溯源）

> 必读：`prompts/answer_with_citations.md`

### Step 3 — 检索并生成溯源文件

```bash
python /mnt/skills/public/ragflow-retrieval/scripts/ragflow_client.py run \
  --route /mnt/user-data/outputs/route.json \
  --question "{用户原问题}" \
  --quiet \
  --out /mnt/user-data/outputs/query.retrieval.json
```

`run` 会自动额外生成：

| 文件 | 用途 |
|------|------|
| `query.retrieval.json` | 完整检索结果 + `citations` 数组 |
| `query.retrieval.citations.json` | 结构化溯源 |
| `query.retrieval.citations.md` | 可读溯源（文件名 + 片段 + 相似度） |

JSON 中每条 citation 包含：

```json
{
  "ref": 1,
  "document_name": "贷款管理办法.pdf",
  "document_id": "...",
  "chunk_id": "...",
  "similarity": 0.86,
  "content": "片段正文...",
  "snippet": "片段正文...",
  "meta_fields": {"部门": "零售金融部"}
}
```

### Step 4 — Agent 回答（agent-turn）

1. 读 `query.retrieval.json` 的 `citations`（或 `.citations.md`）。
2. **仅基于检索片段**生成回答；关键句标注 `[1][2]`。
3. 文末必须附 **「参考来源」**，展示文件名 + 片段 + 相似度。
4. `present_files` 分享 `query.retrieval.json` 和 `query.retrieval.citations.md`。

### 溯源字段说明（来自 RAGFlow）

| 字段 | 含义 |
|------|------|
| `document_name` / `document_keyword` | 源文件名 |
| `document_id` | 源文档 ID |
| `chunk_id` | 片段 ID |
| `content` | 召回的正文片段 |
| `similarity` | 综合相似度 |
| `meta_fields.部门` | 部门 metadata |
| `highlight` | 高亮命中词（retrieve 加 `--highlight` 时有） |

## 错误处理

| 错误 | 含义 | 处理 |
|------|------|------|
| `RAGFLOW_BASE_URL is not set` | 缺少服务地址 | 在 skill 目录 `.env` 设置 `RAGFLOW_BASE_URL`，或传 `--base-url` |
| `RAGFLOW_API_KEY is not set` | 缺少 API Key | 在 skill 目录 `.env` 设置 `RAGFLOW_API_KEY`，或传 `--api-key` |
| rerank 模型不存在 / 检索失败 | 租户 rerank 名称不匹配 | 设 `rerank_id: "auto"` 或运行 `list-models` 查 `default_rerank_id`；脚本会自动 fallback 到无 rerank |
| `Internal server error`（HTTP 500） | `rerank_id` 格式错误或模型不可用 | RAGFlow 对错误 rerank 常返回 500 而非明确错误码。勿只填模型名，需完整 ID（如 `BAAI/bge-reranker-v2-m3@Builtin`）；或设 `"rerank_id": "auto"` / `"rerank_enabled": false` |
| `code=102, Datasets use different embedding models` | 跨 dataset embedding 不一致 | 只选相同 embedding 的 dataset |
| `code=102, You don't own the dataset` | 无权限 | 确认 API Key 对应租户 |
| HTTP 401 | 鉴权失败 | 检查 API Key |
| 空 chunks + 有过滤条件 | 无匹配文档 | 放宽条件或检查 metadata 是否已写入 |
| `unknown intent` / `dataset_id` 为空 | `routing.json` 未配置 | 填写各 intent 的 `dataset_id` 或使用 `--resolve-names` |
| `ambiguous` | 信贷/制度无法区分 | 请用户澄清，不要猜测检索 |

## 绝不主动扩大范围

- 不主动上传/解析文档
- 不主动修改 dataset metadata
- 不主动创建 chat/agent
- **不向用户索要 metadata 过滤文件路径**（用 `route.json` + `run` 自动加载）
- 用户明确要求时再执行上述操作

## 附加资源

- 元数据过滤完整格式：[references/metadata_filter.md](references/metadata_filter.md)
- RAGFlow 源码参考：`ragflow-0.26.1/api/apps/restful_apis/chunk_api.py`（retrieval）、`ragflow-0.26.1/common/metadata_utils.py`（filter 逻辑）
