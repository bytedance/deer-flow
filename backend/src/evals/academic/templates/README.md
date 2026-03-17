# Academic Eval Raw Dataset Template

使用模板：`raw_accept_reject_template.json`

新增：分层离线基准模板目录 `offline_benchmark_suite/`（Core / Failure-mode / Domain split），可用于构建“离线基准 + 红队”评测闭环。

## 一键导入（单文件）

```bash
cd backend
uv run python scripts/import_academic_eval_dataset.py \
  --input src/evals/academic/templates/raw_accept_reject_template.json \
  --dataset-name top_tier_accept_reject_real \
  --dataset-version 2026_03 \
  --output-dir src/evals/academic/datasets \
  --overwrite
```

## 一键导入（目录批量）

```bash
cd backend
uv run python scripts/import_academic_eval_dataset.py \
  --input /abs/path/to/raw-datasets \
  --dataset-name top_tier_accept_reject_real \
  --dataset-version 2026_03 \
  --batch-pattern "*.json" \
  --output-dir src/evals/academic/datasets
```

若使用分层离线基准模板目录：

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

配套离线回归门禁（Core 校准 + Domain split + Failure-mode 红队）：

```bash
cd backend
uv run python scripts/run_academic_offline_regression.py \
  --input-dir src/evals/academic/templates/offline_benchmark_suite \
  --output-dir src/evals/academic/datasets/offline_regression \
  --strict-gate \
  --overwrite
```

在线回归自动化（commit-to-commit + week-to-week 漂移告警）：

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

## 仅做导入前校验（不落地 dataset）

```bash
cd backend
uv run python scripts/import_academic_eval_dataset.py \
  --input /abs/path/to/raw-datasets \
  --dataset-name top_tier_accept_reject_real \
  --dataset-version 2026_03 \
  --validate-only \
  --validation-report-mode both \
  --output-dir src/evals/academic/datasets
```

你也可以在仓库根目录使用：

```bash
make import-academic-eval \
  RAW_DATA=/abs/path/to/raw-datasets \
  DATASET_NAME=top_tier_accept_reject_real \
  DATASET_VERSION=2026_03 \
  VALIDATE_ONLY=1
```

## 开启自动修复预处理器（低风险字段修复）

```bash
make import-academic-eval \
  RAW_DATA=/abs/path/to/raw-datasets \
  DATASET_NAME=top_tier_accept_reject_real \
  DATASET_VERSION=2026_03 \
  AUTOFIX=1 \
  AUTOFIX_LEVEL=balanced
```

自动修复会在导入前执行低风险处理，例如：
- 字段重命名：`outcome -> decision`、`journal -> venue`
- 数组包裹：`claims` 单对象包裹成数组
- 别名合并：`reviewer_comments` / `review_comments` 合并到 `reviewer_comment_ids`

白名单级别：
- `safe`：仅执行最保守的字段别名映射与合并
- `balanced`：在 `safe` 基础上增加常见数组包裹与二维结构修正
- `aggressive`：在 `balanced` 基础上增加分隔符拆分与更激进的 claims 标准化

导入后会生成：
- `<dataset_name>.json`：标准化评测集（可用于 `dataset_name` 评测）
- `<dataset_name>.manifest.json`：导入元数据（版本、计数、fingerprint、告警）
- `<dataset_name>.validation.json`：导入前字段校验详情（error/warning 明细）
- `<dataset_name>.validation.md`：可读校验报告（按字段统计 + 问题清单 + 字段修复建议）
- `<dataset_name>.autofix.input.json`：自动修复后的中间输入（仅 AUTOFIX=1）
- `<dataset_name>.autofix.report.json`：自动修复动作明细（仅 AUTOFIX=1）
- `<dataset_name>.autofix.report.md`：可读自动修复报告（仅 AUTOFIX=1）
- `import-summary-*.json`：批处理汇总
