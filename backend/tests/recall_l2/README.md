# L2 召回评测(recall_l2)

> 真实 embedding + 标注集 + IR 指标。手动 / nightly 用,**不进 PR gate**。

## 它是什么 / 为什么独立于 L1

`tests/recall/`(L1)用的是 `ControlledEmbedder` —— 把目标 chunk 和 query
锚到同一向量。结果就是 `Recall@K` 恒为 100%,只能验证**管道工程正确性**
(接通、排序确定、租户隔离、配置生效)。

要回答"召回率到底是多少"这个**质量**问题,就得用真实 embedding 跑标注
集。这套就是 L2:

- 真实 embedding 模型(走 `config.yaml` 里的 `rag.embedding_model`,
  生产怎么配它就怎么跑)
- 人工标注的 query → relevant_doc_ids 三元组
- IR 指标:Recall@{1, 3, 5, 10}、MRR、nDCG@10
- 与 baseline 对比,任何指标下降 > 5% 自动标记回归

L2 慢、要外网、要 API key、可能花钱,所以**不接 PR**,只接本地手动 +
GitHub Actions `workflow_dispatch`。

## 怎么跑

### 本地

前置条件:`.venv/` 已经 `make install` 装好,`config.yaml` 在项目根目录,
环境变量 `OPENAI_API_KEY`(或代理 key)已 export。

```bash
cd backend

# 第一次跑 —— 索引语料 + 算分,生成 reports/run-{timestamp}.json
make eval-recall

# 看着指标合理后冻结基线(后续跑批与之 diff)
make eval-recall-update-baseline

# 之后每次跑 —— 与 baseline 比较,任何指标下降 > 5% 退出码非 0
make eval-recall
```

退出码:

| code | 含义 |
|------|------|
| 0    | 成功 + 无回归 |
| 1    | 成功但检测到指标回归(> 5% 下降) |
| 2    | 配置/运行时致命错误(API key 缺失、corpus 空、embedding 抛错等) |

### GitHub Actions

`.github/workflows/recall-l2.yml` 提供 `workflow_dispatch` 触发,在
secrets 里读 `OPENAI_API_KEY`,跑完上传 `reports/run-*.json` 作为 artifact。

```bash
gh workflow run recall-l2.yml
gh run watch
```

## 数据集格式

```text
dataset/
  corpus/                 # 被索引的语料,每个文件按 anchor 切成段
    equipment_runbook.md
    fault_diagnosis.md
    ...
  queries.jsonl           # 一行一个 query 标注
```

### corpus markdown

用 HTML 注释 `<!-- anchor: NAME -->` 标记**可被检索的段**。脚本切段后,
段名会作为 `doc_id` 的一部分写入 chunk metadata。

```markdown
# 设备运维手册

<!-- anchor: vibration -->
## 振动诊断
当 RMS 超过 4.5 mm/s 时...

<!-- anchor: lubrication -->
## 润滑维护
...
```

切完得到 `equipment_runbook.md#vibration` 和
`equipment_runbook.md#lubrication` 两个段。**第一个 anchor 之前的内容会
被丢弃**,确保每个被索引的 chunk 都有合法 `doc_id`。

### queries.jsonl

一行一个 JSON,字段:

| 字段 | 类型 | 说明 |
|------|------|------|
| `qid` | string | 稳定 ID,报告里用它定位回归 |
| `query` | string | 中文/英文自然语言查询 |
| `relevant_doc_ids` | string[] | chunk 级标注,格式 `{file_name}#{anchor}` |
| `notes` | string | 人读注释,不参与计算(可选) |

例:

```jsonl
{"qid": "q-001", "query": "电机振动过大如何排查", "relevant_doc_ids": ["equipment_runbook.md#vibration"], "notes": "命中 RMS > 4.5 处置流程"}
{"qid": "q-008", "query": "周末团建烧烤适合什么样的肉", "relevant_doc_ids": [], "notes": "负例 — 故意不应命中任何文档"}
```

`relevant_doc_ids: []` 表示**负例 query**,会被排除在 Recall/MRR/nDCG
聚合之外,但仍然走一遍检索,在报告里标注 `negative_query_count`。

## 指标含义

- **Recall@K**:前 K 个检索结果中命中 ≥ 1 个相关 doc 的 query 占比
- **MRR**(Mean Reciprocal Rank):第一个命中位置的倒数取平均,衡量
  "对的答案排得有多靠前"。位置 1 命中得 1.0,位置 2 命中得 0.5,
  没命中得 0
- **nDCG@10**(Normalized Discounted Cumulative Gain):带位置折损的
  累计增益除以理论最优,综合"命中数 + 排序质量"。当前用 0/1 二值
  标注,等同于 binary nDCG

只对**有标注的 query**(`relevant_doc_ids` 非空)算分。`judged_query_count`
和 `negative_query_count` 在报告 `aggregate` 里都给出来,方便审计。

## 怎么扩数据

加新 query:

1. 在 `dataset/corpus/` 下放 markdown(或编辑现有的),加 anchor 注释
2. 在 `dataset/queries.jsonl` 末尾追加一行 JSON,`relevant_doc_ids`
   填 `{file}#{anchor}`
3. 跑 `make eval-recall` 生成新 baseline,看着合理就
   `make eval-recall-update-baseline` 冻结

加现实业务文档时建议:

- corpus 文件命名用业务领域(如 `pump_maintenance.md`),anchor 用
  紧凑英文 slug(`bearing_replace`)
- query 写真实用户口吻,不要写"标题党"式 query
- 每个新 query 至少配一条相关 doc(避免变成单纯的负例),负例总占比
  控制在 10–15% 以内(留来验证阈值/低分提示行为)
- `notes` 字段帮你自己以后看,值得多写两句:为什么标这条相关、
  期望命中哪个段

## 报告结构

`reports/run-{timestamp}.json`:

```json
{
  "metadata": {
    "started_at": "2026-...Z",
    "duration_ms": 12345,
    "embedding_model": "openai:text-embedding-v4",
    "embedding_base_url": "https://aiapi.shenguyun.com/v1",
    "vector_backend": "chroma",
    "chunk_size": 1000,
    "chunk_overlap": 200,
    "chunk_strategy": "recursive",
    "top_k": 20,
    "corpus_section_count": 13,
    "indexed_chunk_count": 17,
    "query_count": 8
  },
  "aggregate": {
    "recall_at_k": {"1": 0.71, "3": 0.86, "5": 0.86, "10": 1.0},
    "mrr": 0.79,
    "ndcg_at_10": 0.83,
    "judged_query_count": 7,
    "negative_query_count": 1
  },
  "per_query": [
    {
      "qid": "q-001",
      "query": "...",
      "relevant_doc_ids": ["..."],
      "retrieved_doc_ids": ["...", "..."],
      "retrieved_scores": [0.87, 0.71, ...],
      "hit_positions": [0],
      "top1_score": 0.87,
      "notes": "..."
    }
  ]
}
```

## 隔离 / 不污染

每次跑都会:

1. `set_current_tenant_id("recall-l2-eval")` —— 切到独立租户,绝不和
   生产/默认租户共用 collection
2. `tempfile.mkdtemp(prefix="recall_l2_chroma_")` —— 临时 chroma 目录,
   通过 `RagConfig(chroma_persist_dir=...)` 注入,跑完 `shutil.rmtree`

即便脚本异常退出,临时目录在 `finally` 里也会清理。

## 不在范围内

- **不**改任何生产代码 —— 整个 L2 完全是 `tests/` 下的旁路工具
- **不**接 PR gate —— 这是 nightly/手动工具,接 PR 会让 CI 不稳定且烧钱
- **不**做 LLM-as-judge —— 那是另一层(答案质量),与召回率正交
- **不**做 latency / throughput 评测 —— 设计稿里 `tests/perf/` 是另一套

如果要研究 L1(纯工程正确性、Recall 恒 100%、不需要 API key、CI 友好),
看 `tests/recall/`。
