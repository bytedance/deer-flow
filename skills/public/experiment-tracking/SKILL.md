---
name: experiment-tracking
description: Use this skill when the user needs to set up experiment tracking, manage ML experiment runs, log hyperparameters and metrics, compare model performance across runs, or ensure reproducibility of scientific experiments. Supports MLflow, Weights & Biases (W&B), and lightweight local tracking. Trigger on queries like "track my experiment", "set up MLflow", "log experiment results", "compare model runs", "experiment reproducibility", or any request involving systematic experiment management.
---

# Experiment Tracking Skill

## Overview

This skill provides workflows for systematic experiment tracking in scientific research. It supports setting up experiment tracking infrastructure, logging hyperparameters and metrics, comparing runs, and generating reproducibility artifacts (requirements.txt, Dockerfile, seed management).

## When to Use This Skill

**Always load this skill when:**

- User needs to set up experiment tracking (MLflow / W&B / local)
- User wants to log and compare experiment results systematically
- User needs reproducibility artifacts (requirements.txt, Dockerfile, random seeds)
- User is running ML experiments and needs to track hyperparameters/metrics
- User wants to compare performance across multiple model configurations
- User asks about experiment management best practices

## Core Capabilities

| Capability | Description |
|-----------|-------------|
| **MLflow Setup** | Local MLflow server, experiment creation, run logging |
| **W&B Integration** | wandb init, run logging, sweep configuration |
| **Local Tracking** | Lightweight JSON/CSV-based experiment logging |
| **Hyperparameter Logging** | Structured parameter recording with types |
| **Metrics Tracking** | Per-step and per-epoch metric logging |
| **Run Comparison** | Tabular comparison of experiment runs |
| **Reproducibility** | requirements.txt, Dockerfile, seed management, config snapshots |
| **Experiment Reports** | Auto-generated markdown reports with charts |

## Workflow

### Step 1: Choose Tracking Backend

| Backend | Best For | Setup Complexity |
|---------|---------|-----------------|
| **Local JSON** | Quick experiments, no dependencies | None |
| **MLflow** | Team projects, model registry, full lifecycle | Medium |
| **W&B** | Cloud-based, rich visualization, collaboration | Low (needs API key) |

### Step 2: Initialize Experiment Tracking

#### Option A: Local JSON Tracking (Zero Dependencies)

```python
import json
import os
import hashlib
from datetime import datetime

class ExperimentTracker:
    def __init__(self, experiment_name, base_dir="/mnt/user-data/workspace/experiments"):
        self.experiment_name = experiment_name
        self.base_dir = os.path.join(base_dir, experiment_name)
        os.makedirs(self.base_dir, exist_ok=True)
        self.run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.run_dir = os.path.join(self.base_dir, self.run_id)
        os.makedirs(self.run_dir, exist_ok=True)
        self.params = {}
        self.metrics = {}
        self.artifacts = []

    def log_params(self, params: dict):
        self.params.update(params)
        self._save()

    def log_metric(self, name: str, value: float, step: int = None):
        if name not in self.metrics:
            self.metrics[name] = []
        entry = {"value": value, "timestamp": datetime.now().isoformat()}
        if step is not None:
            entry["step"] = step
        self.metrics[name].append(entry)
        self._save()

    def log_artifact(self, path: str):
        self.artifacts.append(path)
        self._save()

    def _save(self):
        data = {
            "experiment": self.experiment_name,
            "run_id": self.run_id,
            "params": self.params,
            "metrics": {k: v for k, v in self.metrics.items()},
            "artifacts": self.artifacts,
            "timestamp": datetime.now().isoformat(),
        }
        with open(os.path.join(self.run_dir, "run.json"), "w") as f:
            json.dump(data, f, indent=2)

    def compare_runs(self):
        runs = []
        for run_dir in sorted(os.listdir(self.base_dir)):
            run_file = os.path.join(self.base_dir, run_dir, "run.json")
            if os.path.exists(run_file):
                with open(run_file) as f:
                    runs.append(json.load(f))
        return runs
```

#### Option B: MLflow Setup

```bash
pip install mlflow

# Start local MLflow tracking server
mlflow server --host 0.0.0.0 --port 5000 --backend-store-uri sqlite:///mlflow.db &
```

```python
import mlflow

mlflow.set_tracking_uri("http://localhost:5000")
mlflow.set_experiment("my-research-experiment")

with mlflow.start_run(run_name="baseline_v1"):
    mlflow.log_params({
        "model": "random_forest",
        "n_estimators": 100,
        "max_depth": 10,
        "learning_rate": 0.01,
        "random_seed": 42,
    })

    # ... training code ...

    mlflow.log_metrics({
        "accuracy": 0.92,
        "f1_score": 0.89,
        "auc_roc": 0.95,
        "train_time_seconds": 45.2,
    })

    mlflow.log_artifact("model.pkl")
    mlflow.log_artifact("confusion_matrix.png")
```

#### Option C: Weights & Biases Setup

```bash
pip install wandb
wandb login  # requires API key
```

```python
import wandb

wandb.init(
    project="my-research",
    name="experiment-v1",
    config={
        "model": "transformer",
        "learning_rate": 1e-4,
        "epochs": 50,
        "batch_size": 32,
    }
)

# During training
for epoch in range(50):
    train_loss = train_one_epoch()
    val_loss, val_acc = evaluate()
    wandb.log({
        "epoch": epoch,
        "train_loss": train_loss,
        "val_loss": val_loss,
        "val_accuracy": val_acc,
    })

wandb.finish()
```

### Step 3: Generate Reproducibility Artifacts

#### requirements.txt Generation

```bash
pip freeze > /mnt/user-data/outputs/requirements.txt
```

Or more targeted:
```python
import pkg_resources

key_packages = [
    "numpy", "pandas", "scipy", "scikit-learn", "statsmodels",
    "matplotlib", "seaborn", "torch", "tensorflow", "transformers",
    "mlflow", "wandb", "hydra-core", "omegaconf",
]
installed = {pkg.key: pkg.version for pkg in pkg_resources.working_set}

with open("/mnt/user-data/outputs/requirements.txt", "w") as f:
    for pkg in key_packages:
        if pkg in installed:
            f.write(f"{pkg}=={installed[pkg]}\n")
```

#### Dockerfile Generation

```dockerfile
FROM python:3.12-slim

WORKDIR /experiment

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONHASHSEED=42
CMD ["python", "main.py"]
```

#### Seed Management

```python
import random
import numpy as np

def set_seed(seed: int = 42):
    """Set all random seeds for reproducibility."""
    random.seed(seed)
    np.random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)

    try:
        import torch
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
    except ImportError:
        pass

    try:
        import tensorflow as tf
        tf.random.set_seed(seed)
    except ImportError:
        pass
```

#### Experiment Config Snapshot (Hydra-style)

```python
import json
from datetime import datetime

config = {
    "experiment": {
        "name": "my_experiment",
        "seed": 42,
        "timestamp": datetime.now().isoformat(),
    },
    "model": {
        "type": "random_forest",
        "n_estimators": 100,
        "max_depth": 10,
    },
    "data": {
        "train_path": "data/train.csv",
        "test_path": "data/test.csv",
        "val_split": 0.2,
    },
    "training": {
        "epochs": 50,
        "batch_size": 32,
        "learning_rate": 1e-4,
        "optimizer": "adam",
    },
}

with open("/mnt/user-data/outputs/experiment_config.json", "w") as f:
    json.dump(config, f, indent=2)
```

### Step 4: Compare Experiment Runs

Generate a comparison report:

```python
import json
import os
import pandas as pd

def compare_experiments(experiment_dir):
    runs = []
    for run_dir in sorted(os.listdir(experiment_dir)):
        run_file = os.path.join(experiment_dir, run_dir, "run.json")
        if os.path.exists(run_file):
            with open(run_file) as f:
                data = json.load(f)
            row = {"run_id": data["run_id"]}
            row.update(data.get("params", {}))
            for metric_name, values in data.get("metrics", {}).items():
                if values:
                    row[metric_name] = values[-1]["value"]
            runs.append(row)

    df = pd.DataFrame(runs)
    print(df.to_markdown(index=False))
    return df
```

### Step 5: Generate Experiment Report

```markdown
# Experiment Report: [Experiment Name]

## Configuration
| Parameter | Value |
|-----------|-------|
| Model | [type] |
| Learning Rate | [value] |
| Epochs | [value] |
| Random Seed | [value] |

## Results Summary
| Run | Accuracy | F1 | AUC | Time (s) |
|-----|:--------:|:--:|:---:|:--------:|
| baseline | 0.85 | 0.82 | 0.90 | 30 |
| tuned_v1 | 0.89 | 0.87 | 0.93 | 45 |
| tuned_v2 | **0.92** | **0.89** | **0.95** | 52 |

## Best Configuration
[Details of best run]

## Reproducibility Artifacts
- `requirements.txt` — Python dependencies
- `experiment_config.json` — Full configuration
- `Dockerfile` — Container setup
- `random_seed.py` — Seed management utilities
```

## Integration with Other Skills

- **statistical-analysis**: Use to analyze experiment results statistically
- **academic-writing**: Export experiment results for inclusion in papers
- **academic-ppt**: Create presentation slides showing experiment comparisons
- **chart-visualization**: Visualize training curves and comparison charts

**Automated Result Analysis via Subagents:**
When running in subagent mode, you can delegate experiment result analysis to the `statistical-analyst` subagent for automated hypothesis testing and APA-formatted reporting. Example workflow:
1. Log experiment metrics using the tracking backend above
2. Export results to CSV/JSON
3. Delegate to `statistical-analyst`: "Perform paired t-tests comparing baseline vs. tuned model across all metrics, report in APA format with effect sizes and 95% CIs"
4. The subagent returns publication-ready statistical summaries that can be directly embedded in your manuscript

## Notes

- Always log random seeds for every experiment run
- Save the full configuration, not just the changed parameters
- Use meaningful run names that describe the experiment variation
- For long-running experiments, log metrics at each epoch/step
- Keep experiment artifacts organized by experiment name and run ID
