# Offline Benchmark Suite (Layered Raw Templates)

本目录提供可直接走 `import_academic_eval_dataset.py` 的离线基准分层模板：

- `core_top_venue_accept_reject_raw.json`
  - Core 层：top venue accept/reject，用于 `AUC / ECE / Brier` 校准评测。
- `failure_mode_hard_negatives_raw.json`
  - Failure-mode 层：hard negatives（七大风险类：引用幻觉 / 过度主张 / 数值漂移 / 证据链断裂 / 风格不符 / 表面回应 / 伦理缺口）。
- `domain_ai_cs_raw.json`
- `domain_biomed_raw.json`
- `domain_cross_discipline_raw.json`
  - Domain split 层：`ai_cs`、`biomed`、`cross_discipline`。

每条 case 均包含评测器需要字段（citations/claims/numbers/reviewer ids/venue checklist/cross-modal/revision/failure_modes）。

## 重新生成分层模板

```bash
cd backend
uv run python scripts/build_academic_offline_benchmark_suite.py --overwrite
```

或在仓库根目录：

```bash
make build-academic-offline-benchmark-suite OVERWRITE=1
```

## 一次性批量导入为标准化 dataset

```bash
cd backend
uv run python scripts/import_academic_eval_dataset.py \
  --input src/evals/academic/templates/offline_benchmark_suite \
  --dataset-name offline_benchmark \
  --dataset-version 2026_03 \
  --batch-pattern "*.json" \
  --output-dir src/evals/academic/datasets \
  --overwrite
```

## 从 OpenReview 导出构建离线 raw 集（可选）

```bash
cd backend
uv run python scripts/build_openreview_offline_benchmark.py \
  --input /path/to/openreview-export.jsonl \
  --output src/evals/academic/templates/offline_benchmark_suite/openreview_top_venue_raw.json \
  --dataset-name openreview_top_venue \
  --overwrite
```

## 一键跑离线回归门禁（Core + Domain split + 红队）

```bash
cd backend
uv run python scripts/run_academic_offline_regression.py \
  --input-dir src/evals/academic/templates/offline_benchmark_suite \
  --output-dir src/evals/academic/datasets/offline_regression \
  --dataset-version 2026_03 \
  --strict-gate \
  --overwrite
```

会输出：
- `offline-benchmark-regression.json`
- `offline-benchmark-regression.md`

## 一键跑在线回归（按提交 + 按周漂移）

```bash
cd backend
uv run python scripts/run_academic_online_regression.py \
  --input-dir src/evals/academic/templates/offline_benchmark_suite \
  --output-dir src/evals/academic/datasets/online_regression \
  --branch main \
  --commit-sha your-commit-sha \
  --strict-gate \
  --overwrite
```

会输出：
- `online-regression-current.json`
- `online-regression-drift.json`
- `online-regression-drift.md`
- `online-regression-history.json`（用于后续 run 的 commit/week 对比基线）

