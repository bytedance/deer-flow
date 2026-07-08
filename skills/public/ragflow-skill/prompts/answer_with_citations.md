# 回答 + 溯源片段（Agent 专用）

检索完成后，**必须**基于召回片段回答，并在文末返回参考来源。

## 输入文件

| 文件 | 内容 |
|------|------|
| `query.retrieval.json` | 完整检索结果，含 `data.chunks` 和 `citations` |
| `query.retrieval.citations.md` | 人类可读的溯源 Markdown（`run` 自动生成） |
| `query.retrieval.citations.json` | 结构化溯源 JSON（`run` 自动生成） |

## Agent 回复结构（必须）

```markdown
## 回答

{基于检索片段的综合回答。关键结论后用 [1][2] 标注引用。}

## 检索路由

- 知识库：{intent / label}
- 部门：{部门列表，或「全库」}

## 参考来源

{直接粘贴 query.retrieval.citations.md 的内容，或按 citations 数组逐条展示}

- [1] {document_name}（相似度 {similarity}）
  > {content 摘要}
```

## 规则

1. **只依据** `citations` / `data.chunks` 中的内容回答；chunks 为空时明确说「未检索到相关内容」。
2. 每条来源必须包含：**文件名**（`document_name`）、**片段正文**（`content` / `snippet`，不可省略）、**相似度**（`similarity`）。禁止只列文件名。
3. 若 metadata 含 `部门`，在来源里一并展示。
4. 用 `present_files` 分享：
   - `query.retrieval.json`
   - `query.retrieval.citations.md`
5. 不要省略参考来源；用户需要看到「答案从哪份文件的哪段来的」。

## 若 run 未生成 citations 侧车文件

```bash
python /mnt/skills/public/ragflow-retrieval/scripts/ragflow_client.py format-citations \
  --input /mnt/user-data/outputs/query.retrieval.json \
  --citations-md-out /mnt/user-data/outputs/query.retrieval.citations.md \
  --citations-json-out /mnt/user-data/outputs/query.retrieval.citations.json
```
